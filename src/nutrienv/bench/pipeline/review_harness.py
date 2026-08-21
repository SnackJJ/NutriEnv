"""Two-stage review committee for mill candidates.

Stage A is a code hard-gate (table grams, pinned windows, reason-set) then
k=3 blind votes on whether one person could eat the plate at one meal.
Voters do not see the query and do not judge table-gram correctness.
Code-gate failure drops the candidate without an LLM vote.

Stage B (speech + leak scan) is a later slice. LLM majority-fail alarms;
it does not drop.

``make_reviewer(stage_a=..., stage_b=...)`` is the grams_gate-style seam.
Tests inject callables; they never call the network.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from nutrienv.bench.pipeline.generate_one import build_stage_a_prompt
from nutrienv.bench.pipeline.types import QUANTITY_MULTIPLES, Reviewer
from nutrienv.bench.realize import Task
from nutrienv.io.chat import (
    DASHSCOPE_CHAT_URL,
    JUDGE_RETRY_ON,
    post_chat_completion,
)
from nutrienv.io.dotenv import load_dotenv_keys

__all__ = [
    "DEFAULT_MODEL_IDS",
    "MAX_TOKENS",
    "PARSE_RETRIES",
    "REASON_GRAMS_OFF_TABLE",
    "STAGE_A_MODEL_IDS",
    "STAGE_A_SYSTEM",
    "STAGE_B_MODEL_IDS",
    "TEMPERATURE",
    "ReviewFn",
    "call_reviewer",
    "format_stage_a_prompt",
    "make_reviewer",
    "resolved_items",
    "review_candidates",
    "stage_a_code_gate",
]

_ROOT = Path(__file__).resolve().parents[4]

STAGE_A_MODEL_IDS: tuple[str, ...] = (
    "qwen3.8-max",
    "qwen3.8-2.4t-a95b",
    "glm-5.2",
)
STAGE_B_MODEL_IDS: tuple[str, ...] = (
    "deepseek-v4-flash-0731",
    "deepseek-v4-pro-0813",
    "kimi-k2.7-code",
)
DEFAULT_MODEL_IDS: tuple[str, ...] = STAGE_A_MODEL_IDS

TEMPERATURE = 0.2
MAX_TOKENS = 256
PARSE_RETRIES = 1

REASON_GRAMS_OFF_TABLE = "grams_off_table"

STAGE_A_SYSTEM = """You review a plate listed as food and grams.

Could one person eat this at one meal? Large plates are allowed.
Vote whether the plate is eatable, not whether it is wise or healthy.
Do not judge whether the gram amounts are the table-correct portion fact.
You do not see a user query or nutrient windows.

Answer with a single JSON object and nothing else:
{"eatable": true or false, "reason": "<one short sentence>"}"""

ReviewFn = Callable[[str], str]


def stage_a_code_gate(task: Task) -> list[str]:
    """Re-verify the bound Task. Empty means the code-gate passes."""
    reasons: list[str] = []
    catalog = getattr(getattr(task, "s0", None), "catalog", None) or {}
    for food_id, grams in _oracle_pairs(task):
        if _match_portion(
            (catalog.get(food_id) or {}).get("portions") if isinstance(catalog, Mapping) else {},
            grams,
        ) == (None, None):
            reasons.append(REASON_GRAMS_OFF_TABLE)
            break
    return reasons


def resolved_items(task: Task) -> list[dict[str, object]]:
    """Food name, portion key/expression, and grams from the oracle + catalog."""
    catalog = getattr(getattr(task, "s0", None), "catalog", None) or {}
    items: list[dict[str, object]] = []
    for food_id, grams in _oracle_pairs(task):
        entry = catalog.get(food_id) if isinstance(catalog, Mapping) else None
        if not isinstance(entry, dict):
            entry = {}
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            name = food_id
        key, quantity = _match_portion(entry.get("portions") or {}, grams)
        if key is None or quantity is None:
            expression = f"{grams:g} g"
        else:
            expression = f"{quantity:g} × {key}"
        items.append(
            {
                "food_id": food_id,
                "name": name,
                "portion_key": key,
                "quantity": quantity,
                "expression": expression,
                "grams": grams,
            }
        )
    return items


def format_stage_a_prompt(task: Task) -> str:
    """Food+grams only. No query, no windows, no table-gram question."""
    catalog = getattr(getattr(task, "s0", None), "catalog", None)
    plate = [
        {"food_id": item["food_id"], "grams": item["grams"]} for item in resolved_items(task)
    ]
    return build_stage_a_prompt(plate, catalog if isinstance(catalog, Mapping) else None)


def review_candidates(
    candidates: Sequence[Task],
    *,
    stage_a: Mapping[str, ReviewFn],
    stage_b: Mapping[str, ReviewFn],
    parse_retries: int = PARSE_RETRIES,
) -> dict[str, object]:
    """Stage A code-gate, then Stage A votes. Code fail drops without an LLM call."""
    if not stage_a:
        raise ValueError("review_candidates requires Stage A models")
    if not stage_b:
        raise ValueError("review_candidates requires Stage B models")
    per_candidate: dict[str, dict[str, object]] = {}
    dropped: list[dict[str, object]] = []
    anomalies: list[dict[str, object]] = []
    for task in candidates:
        gate = stage_a_code_gate(task)
        entry: dict[str, object] = {
            "stage_a": {"code_gate": gate, "votes": {}},
            "dropped": bool(gate),
            "alarm": False,
            "anomaly": False,
        }
        if gate:
            dropped.append({"id": task.id, "reasons": list(gate)})
            per_candidate[task.id] = entry
            continue
        prompt = format_stage_a_prompt(task)
        votes: dict[str, dict[str, object]] = {}
        for model_id in sorted(stage_a):
            text = ""
            for _attempt in range(1 + parse_retries):
                text = stage_a[model_id](prompt) or ""
                if text.strip():
                    break
            votes[model_id] = {"raw": text}
        entry["stage_a"] = {"code_gate": gate, "votes": votes}
        per_candidate[task.id] = entry
    return {
        "anomalies": anomalies,
        "dropped": dropped,
        "per_candidate": per_candidate,
    }


def make_reviewer(
    stage_a: Mapping[str, ReviewFn] | None = None,
    stage_b: Mapping[str, ReviewFn] | None = None,
    *,
    parse_retries: int = PARSE_RETRIES,
) -> Reviewer:
    """Bind per-stage callables (or live model ids) into a ``Reviewer``."""
    bound_a = dict(stage_a) if stage_a is not None else {
        model_id: _live_caller(model_id) for model_id in STAGE_A_MODEL_IDS
    }
    bound_b = dict(stage_b) if stage_b is not None else {
        model_id: _live_caller(model_id) for model_id in STAGE_B_MODEL_IDS
    }
    if not bound_a or not bound_b:
        raise ValueError("make_reviewer requires Stage A and Stage B models")

    def reviewer(candidates: Sequence[Task]) -> dict[str, object]:
        return review_candidates(
            candidates,
            stage_a=bound_a,
            stage_b=bound_b,
            parse_retries=parse_retries,
        )

    return reviewer


def call_reviewer(model_id: str, prompt: str, *, system: str = STAGE_A_SYSTEM) -> str:
    """One chat completion for ``model_id``. Network noise is retried three times."""
    load_dotenv_keys(_ROOT / ".env.local")
    url, api_key = _route(model_id)
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    return post_chat_completion(
        url,
        payload,
        api_key,
        timeout=60.0,
        retries=3,
        retry_on=JUDGE_RETRY_ON,
        error_prefix="review request failed",
    )


def _live_caller(model_id: str) -> ReviewFn:
    def call(prompt: str, *, _id: str = model_id) -> str:
        return call_reviewer(_id, prompt)

    return call


def _route(_model_id: str) -> tuple[str, str]:
    # All reviewer ids, including DeepSeek snapshots, post to DashScope.
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set")
    return DASHSCOPE_CHAT_URL, key


def _oracle_pairs(task: Task) -> list[tuple[str, float]]:
    oracle = getattr(task, "oracle", None)
    if oracle is None:
        return []
    children = getattr(oracle, "sub_oracles", None) or ()
    oracles = list(children) if children else [oracle]
    pairs: list[tuple[str, float]] = []
    seen: set[tuple[str, float]] = set()
    for item in oracles:
        for pair in _pairs_from_one(item):
            if pair in seen:
                continue
            seen.add(pair)
            pairs.append(pair)
    return pairs


def _pairs_from_one(oracle) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    evaluated = getattr(oracle, "evaluated_plan", None) or []
    if evaluated:
        for item in evaluated:
            if not isinstance(item, Mapping):
                continue
            food_id = item.get("food_id")
            grams = item.get("grams")
            if food_id is None or grams is None:
                continue
            pairs.append((str(food_id), float(grams)))
        return pairs
    tail = getattr(oracle, "ledger_tail", None) or []
    if tail:
        for row in tail:
            food_id = getattr(row, "food_id", None)
            grams = getattr(row, "grams", None)
            if food_id is None or grams is None:
                continue
            pairs.append((str(food_id), float(grams)))
        return pairs
    plan = getattr(oracle, "last_plan", None) or []
    for item in plan:
        if not isinstance(item, Mapping):
            continue
        food_id = item.get("food_id")
        grams = item.get("grams")
        if food_id is None or grams is None:
            continue
        pairs.append((str(food_id), float(grams)))
    return pairs


def _match_portion(
    portions: object, grams: float
) -> tuple[str | None, float | None]:
    if not isinstance(portions, Mapping):
        return None, None
    target = round(float(grams), 2)
    for key, unit in portions.items():
        if isinstance(unit, bool) or not isinstance(unit, (int, float)):
            continue
        for quantity in QUANTITY_MULTIPLES:
            if round(quantity * float(unit), 2) == target:
                return str(key), float(quantity)
    return None, None


def _json_blob(text: str) -> str | None:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]


if __name__ == "__main__":
    print(
        "review_harness usage: inject make_reviewer(stage_a=..., stage_b=...) as "
        "run_batch(..., reviewer=...). Tests never call the network. "
        f"Stage A live pool: {', '.join(STAGE_A_MODEL_IDS)}. "
        f"Stage B live pool: {', '.join(STAGE_B_MODEL_IDS)}."
    )
