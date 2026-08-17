"""Multi-model review harness for v1.0 candidate Tasks.

Reviews query/anchoring quality only. Grams and portion keys are PortionFact
table values: the harness never second-guesses them (that is the judge /
resolver). Anomalous candidates are marked for human review (issue 10).

Sampling
--------
Every candidate is reviewed by every configured model. Pipeline pools keep
≤3 candidates (``MAX_PER_POOL``), so full review is cheap enough. There is
no subset sampling.

Injection
---------
``make_reviewer(models={model_id: fn})`` is the grams_gate-style seam.
``fn`` is ``ReviewFn``: ``(user_prompt: str) -> raw text``. Tests inject
stubs; they never call the network. Omit ``models`` to bind live callers
for ``model_ids`` (default ``DEFAULT_MODEL_IDS``, a cheap subset of the
expander/judge pool).

Input
-----
A sequence of realized ``Task`` objects (``Reviewer`` protocol). Resolved
items are taken from ``oracle.ledger_tail`` (log) or ``oracle.last_plan``
(evaluate), with names/keys recovered from ``task.s0.catalog``.

Per-model output (JSON the model must return)
---------------------------------------------
``{"consistency": 0-5, "naturalness": 0-5, "entailment": 0-5, "reason": str}``

- consistency: does the query actually speak the resolved PortionFact
  amounts? High if spoken measures match the key/quantity (query "a cup"
  vs key ``cup``). Low if they do not ("a piece" vs ``cup``; "half" vs
  2.0×).
- naturalness: is the query natural user speech? Recorded, but a low
  score alone does **not** mark an anomaly.
- entailment: high = no hidden contradiction; low = the query implies
  something incompatible with the stated amounts (or names a food that
  is not in the resolved items).

Unparseable model output is retried once (same as the io/judge layer),
then recorded as ``unparseable`` on that model. The pipeline does not
crash.

Harness output (``Reviewer`` / ``run_batch`` shape)
---------------------------------------------------
::

    {
      "anomalies": [{"id": task_id, "reasons": [str, ...]}, ...],
      "per_candidate": {
        task_id: {
          "models": {
            model_id: {
              "consistency": float | None,
              "naturalness": float | None,
              "entailment": float | None,
              "reason": str,
              "unparseable": True,   # only when the reply would not parse
            },
            ...
          },
          "aggregate": {
            "consistency": float | None,   # mean of parseable models
            "naturalness": float | None,
            "entailment": float | None,
            "disagreement": float,         # max (max-min) across axes
            "unparseable": [model_id, ...],
            "reasons": [str, ...],         # anomaly codes, may be empty
          },
          "anomaly": False | str,          # False, or ",".join(reasons)
        },
        ...
      },
    }

``anomalies`` lists only the flagged candidates (stable ``id`` order).
Non-anomalous candidates still appear in ``per_candidate`` with
``anomaly is False`` — they pass through for freeze.

Anomaly rules (thresholds are module constants)
-----------------------------------------------
Flag if any of:

- mean consistency < ``LOW_CONSISTENCY`` (2.0)
- mean entailment < ``LOW_ENTAILMENT`` (2.0)
- disagreement > ``DISAGREEMENT_THRESHOLD`` (2.0)
- any model unparseable after retry

Reason codes: ``low_consistency``, ``low_entailment``, ``disagreement``,
``unparseable``.

Smoke: ``python -m nutrienv.bench.pipeline.review_harness`` prints usage.
Live calls belong in a one-off probe, not in tests.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from nutrienv.bench.pipeline.types import QUANTITY_MULTIPLES, Reviewer
from nutrienv.bench.realize import Task
from nutrienv.io.chat import (
    DASHSCOPE_CHAT_URL,
    DEEPSEEK_CHAT_URL,
    JUDGE_RETRY_ON,
    post_chat_completion,
)
from nutrienv.io.dotenv import load_dotenv_keys

__all__ = [
    "AXES",
    "DEFAULT_MODEL_IDS",
    "DISAGREEMENT_THRESHOLD",
    "LOW_CONSISTENCY",
    "LOW_ENTAILMENT",
    "MAX_TOKENS",
    "PARSE_RETRIES",
    "REASON_DISAGREEMENT",
    "REASON_LOW_CONSISTENCY",
    "REASON_LOW_ENTAILMENT",
    "REASON_UNPARSEABLE",
    "REVIEW_SYSTEM",
    "ReviewFn",
    "TEMPERATURE",
    "aggregate_reviews",
    "call_reviewer",
    "format_review_prompt",
    "make_reviewer",
    "parse_review",
    "resolved_items",
    "review_candidates",
    "review_once",
]

_ROOT = Path(__file__).resolve().parents[4]

#: Cheap 2-model subset of the expander/judge pool. Inject ``models`` or
#: ``model_ids`` to use a different set.
DEFAULT_MODEL_IDS: tuple[str, ...] = (
    "deepseek-v4-flash",
    "qwen3.7-flash-2026-07-15",
)

AXES: tuple[str, ...] = ("consistency", "naturalness", "entailment")
TEMPERATURE = 0.2
MAX_TOKENS = 256
PARSE_RETRIES = 1
LOW_CONSISTENCY = 2.0
LOW_ENTAILMENT = 2.0
DISAGREEMENT_THRESHOLD = 2.0

REASON_LOW_CONSISTENCY = "low_consistency"
REASON_LOW_ENTAILMENT = "low_entailment"
REASON_DISAGREEMENT = "disagreement"
REASON_UNPARSEABLE = "unparseable"

REVIEW_SYSTEM = """You review a candidate nutrition-diary exam item.

You do NOT judge whether the gram amounts are plausible or correct.
Grams and portion keys are authoritative PortionFact table values. Never
second-guess them.

Score three axes as numbers from 0 to 5:

- consistency: does the user's query actually name the resolved portion
  amounts? High if spoken measures match the PortionFact keys/quantities
  (e.g. query says "a cup" and the resolved key is cup). Low if the query
  says a different measure or quantity than the resolved items
  (e.g. "a piece" vs resolved key cup; "half" vs resolved 2.0×).
- naturalness: is the query natural user speech for a food diary or meal
  plan, not catalog jargon or exam-author prose.
- entailment: does the query imply a hidden contradiction with the stated
  amounts? High = no contradiction (the query is compatible with the
  facts). Low = the query entails something incompatible with the
  resolved items (e.g. "half a cup" while the resolved amount is 2.0×
  cup; the query names a food that is not in the resolved items).

Answer with a single JSON object and nothing else:
{"consistency": <0-5>, "naturalness": <0-5>, "entailment": <0-5>, "reason": "<one short sentence>"}"""

ReviewFn = Callable[[str], str]


def parse_review(text: str) -> dict[str, object] | None:
    """Return ``{consistency, naturalness, entailment, reason}`` or ``None``."""
    if not text or not str(text).strip():
        return None
    blob = _json_blob(str(text))
    if blob is None:
        return None
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    scores: dict[str, object] = {}
    for axis in AXES:
        number = _score(payload.get(axis))
        if number is None:
            return None
        scores[axis] = number
    reason = payload.get("reason", "")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        reason = str(reason)
    scores["reason"] = reason.strip()
    return scores


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


def format_review_prompt(task: Task) -> str:
    """User message: query + resolved PortionFacts + persona. Grams are facts."""
    lines: list[str] = []
    for item in resolved_items(task):
        key = item["portion_key"]
        key_text = "none" if key is None else str(key)
        lines.append(
            f"- {item['name']} ({item['food_id']}): {item['expression']}, "
            f"portion key={key_text}, {item['grams']:g} g"
        )
    block = "\n".join(lines) if lines else "- (no resolved items)"
    return (
        f"Task id: {task.id}\n"
        f"Family: {task.family}\n"
        f"Persona: {task.persona}\n"
        f"Query: {task.query}\n"
        f"Resolved PortionFacts (authoritative; do not second-guess grams):\n"
        f"{block}\n"
    )


def review_once(
    prompt: str,
    model_fn: ReviewFn,
    *,
    parse_retries: int = PARSE_RETRIES,
) -> tuple[dict[str, object] | None, str]:
    """Call ``model_fn`` until a review parses. Empty replies retry once."""
    text = ""
    for _attempt in range(1 + parse_retries):
        text = model_fn(prompt) or ""
        parsed = parse_review(text)
        if parsed is not None:
            return parsed, text
    return None, text


def aggregate_reviews(model_scores: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    """Mean per axis, disagreement = max axis spread, plus anomaly reasons."""
    per_axis: dict[str, list[float]] = {axis: [] for axis in AXES}
    unparseable: list[str] = []
    for model_id in sorted(model_scores):
        scores = model_scores[model_id]
        if scores.get("unparseable") or scores.get("consistency") is None:
            unparseable.append(model_id)
            continue
        for axis in AXES:
            per_axis[axis].append(float(scores[axis]))
    means = {
        axis: (sum(vals) / len(vals) if vals else None) for axis, vals in per_axis.items()
    }
    spreads = [
        (max(vals) - min(vals) if len(vals) >= 2 else 0.0) for vals in per_axis.values()
    ]
    disagreement = max(spreads) if spreads else 0.0
    reasons: list[str] = []
    if unparseable:
        reasons.append(REASON_UNPARSEABLE)
    consistency = means["consistency"]
    if consistency is not None and consistency < LOW_CONSISTENCY:
        reasons.append(REASON_LOW_CONSISTENCY)
    entailment = means["entailment"]
    if entailment is not None and entailment < LOW_ENTAILMENT:
        reasons.append(REASON_LOW_ENTAILMENT)
    if disagreement > DISAGREEMENT_THRESHOLD:
        reasons.append(REASON_DISAGREEMENT)
    return {
        "consistency": means["consistency"],
        "naturalness": means["naturalness"],
        "entailment": means["entailment"],
        "disagreement": disagreement,
        "unparseable": unparseable,
        "reasons": reasons,
    }


def review_candidates(
    candidates: Sequence[Task],
    *,
    models: Mapping[str, ReviewFn],
    parse_retries: int = PARSE_RETRIES,
) -> dict[str, object]:
    """Review every candidate with every model. ``models`` must be injected."""
    if not models:
        raise ValueError("review_candidates requires at least one model")
    per_candidate: dict[str, dict[str, object]] = {}
    anomalies: list[dict[str, object]] = []
    for task in candidates:
        model_scores: dict[str, dict[str, object]] = {}
        prompt = format_review_prompt(task)
        for model_id in sorted(models):
            parsed, _raw = review_once(
                prompt, models[model_id], parse_retries=parse_retries
            )
            model_scores[model_id] = _model_record(parsed)
        summary = aggregate_reviews(model_scores)
        reasons = list(summary["reasons"])
        flagged = bool(reasons)
        per_candidate[task.id] = {
            "models": model_scores,
            "aggregate": summary,
            "anomaly": ",".join(reasons) if flagged else False,
        }
        if flagged:
            anomalies.append({"id": task.id, "reasons": reasons})
    return {"anomalies": anomalies, "per_candidate": per_candidate}


def make_reviewer(
    models: Mapping[str, ReviewFn] | None = None,
    *,
    model_ids: Sequence[str] | None = None,
    parse_retries: int = PARSE_RETRIES,
) -> Reviewer:
    """Bind per-model callables (or live ``model_ids``) into a ``Reviewer``."""
    if models is not None:
        bound = dict(models)
    else:
        ids = tuple(model_ids) if model_ids is not None else DEFAULT_MODEL_IDS
        bound = {model_id: _live_caller(model_id) for model_id in ids}
    if not bound:
        raise ValueError("make_reviewer requires models or model_ids")

    def reviewer(candidates: Sequence[Task]) -> dict[str, object]:
        return review_candidates(
            candidates, models=bound, parse_retries=parse_retries
        )

    return reviewer


def call_reviewer(model_id: str, prompt: str) -> str:
    """One chat completion for ``model_id``. Network noise is retried three times."""
    load_dotenv_keys(_ROOT / ".env.local")
    url, api_key = _route(model_id)
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": REVIEW_SYSTEM},
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


def _route(model_id: str) -> tuple[str, str]:
    lowered = model_id.lower()
    dashscope = any(
        tag in lowered for tag in ("qwen", "glm", "kimi", "dashscope", "aliyuncs")
    )
    if dashscope:
        key = os.environ.get("DASHSCOPE_API_KEY")
        if not key:
            raise RuntimeError("DASHSCOPE_API_KEY is not set")
        return DASHSCOPE_CHAT_URL, key
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    return DEEPSEEK_CHAT_URL, key


def _oracle_pairs(task: Task) -> list[tuple[str, float]]:
    oracle = getattr(task, "oracle", None)
    if oracle is None:
        return []
    tail = getattr(oracle, "ledger_tail", None) or []
    pairs: list[tuple[str, float]] = []
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


def _model_record(parsed: dict[str, object] | None) -> dict[str, object]:
    if parsed is None:
        return {
            "consistency": None,
            "naturalness": None,
            "entailment": None,
            "reason": "unparseable",
            "unparseable": True,
        }
    return {
        "consistency": parsed["consistency"],
        "naturalness": parsed["naturalness"],
        "entailment": parsed["entailment"],
        "reason": parsed["reason"],
    }


def _json_blob(text: str) -> str | None:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]


def _score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0.0 or number > 5.0:
        return None
    return number


if __name__ == "__main__":
    print(
        "review_harness usage: inject make_reviewer(models={...}) as "
        "run_batch(..., reviewer=...). Tests never call the network. "
        f"Default live pool: {', '.join(DEFAULT_MODEL_IDS)}."
    )
