"""Two-stage review committee for mill candidates.

Stage A is a code hard-gate (table grams, pinned windows, reason-set) then
k=3 blind votes on whether one person could eat the plate at one meal.
Voters do not see the query and do not judge table-gram correctness.
Code-gate failure drops the candidate without an LLM vote.

Stage B is code plus speech: a leak scan for leftover/allergy/
remaining-kcal inconsistencies on Recommend candidates (code fail drops),
then k=3 votes on the spoken request (query + food names) for every
candidate that survives the leak scan. LLM majority-fail alarms first;
it does not silently pass and it does not drop.

Each stage votes across three distinct model families (cross-stage family
reuse exists; no single vendor carries a stage's majority alone).

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
from nutrienv.world.types import ledger_totals, normalize_tags

__all__ = [
    "DEFAULT_MODEL_IDS",
    "MAX_TOKENS",
    "PARSE_RETRIES",
    "REASON_GRAMS_OFF_TABLE",
    "REASON_LEAK_ALLERGY",
    "REASON_LEAK_LEFTOVER",
    "REASON_LEAK_REMAINING_KCAL",
    "REASON_WINDOWS_EMPTY",
    "REASON_WINDOWS_OUT_OF_BOUNDS",
    "REASON_WINDOWS_UNPASSABLE",
    "STAGE_A_MODEL_IDS",
    "STAGE_A_SYSTEM",
    "STAGE_B_MODEL_IDS",
    "STAGE_B_SYSTEM",
    "TEMPERATURE",
    "ReviewFn",
    "call_reviewer",
    "format_stage_a_prompt",
    "format_stage_b_prompt",
    "make_reviewer",
    "resolved_items",
    "review_candidates",
    "stage_a_code_gate",
    "stage_b_leak_scan",
]

_ROOT = Path(__file__).resolve().parents[4]

# One id per family per stage: a >=2 majority must span at least two vendors.
STAGE_A_MODEL_IDS: tuple[str, ...] = (
    "qwen3.8-max",
    "deepseek-v4-flash-0731",
    "glm-5.2",
)
STAGE_B_MODEL_IDS: tuple[str, ...] = (
    "kimi-k2.7-code",
    "deepseek-v4-pro-0813",
    "qwen3.8-2.4t-a95b",
)
DEFAULT_MODEL_IDS: tuple[str, ...] = STAGE_A_MODEL_IDS

TEMPERATURE = 0.2
MAX_TOKENS = 256
PARSE_RETRIES = 1

REASON_GRAMS_OFF_TABLE = "grams_off_table"
REASON_WINDOWS_EMPTY = "windows_empty"
REASON_WINDOWS_OUT_OF_BOUNDS = "windows_out_of_bounds"
REASON_WINDOWS_UNPASSABLE = "windows_unpassable"
REASON_LEAK_LEFTOVER = "leak_leftover"
REASON_LEAK_ALLERGY = "leak_allergy"
REASON_LEAK_REMAINING_KCAL = "leak_remaining_kcal"

STAGE_A_SYSTEM = """You review a plate listed as food and grams.

Could one person eat this at one meal? Large plates are allowed.
Vote whether the plate is eatable, not whether it is wise or healthy.
Do not judge whether the gram amounts are the table-correct portion fact.
You do not see a user query or nutrient windows.

Answer with a single JSON object and nothing else:
{"eatable": true or false, "reason": "<one short sentence>"}"""

STAGE_B_SYSTEM = """You review one user's spoken food request.

Could one person eat this at one meal? Large plates are allowed.
Vote whether the request is eatable, not whether it is wise or healthy.
You see the spoken query and the food names. Do not judge gram amounts,
table-correct portion facts, or nutrient windows.

Answer with a single JSON object and nothing else:
{"eatable": true or false, "reason": "<one short sentence>"}"""

ReviewFn = Callable[[str], str]


def stage_a_code_gate(task: Task) -> list[str]:
    """Re-verify the bound Task. Empty means the code-gate passes.

    Window reasons apply only when the oracle pins ``plan_windows``; log
    tasks and other unpinned oracles skip them.
    """
    reasons: list[str] = []
    catalog = getattr(getattr(task, "s0", None), "catalog", None) or {}
    for food_id, grams in _oracle_pairs(task):
        if _match_portion(
            (catalog.get(food_id) or {}).get("portions") if isinstance(catalog, Mapping) else {},
            grams,
        ) == (None, None):
            reasons.append(REASON_GRAMS_OFF_TABLE)
            break
    reasons.extend(_window_reasons(task))
    return reasons


_ATWATER_KCAL_PER_G = {"protein_g": 4.0, "carb_g": 4.0, "fat_g": 9.0}


def _window_reasons(task: Task) -> list[str]:
    """Window reasons across the oracle and every composite child.

    Mirrors ``_oracle_pairs``: a composite container itself pins nothing, so
    each child oracle that pins ``plan_windows`` is gated on its own.
    """
    reasons: list[str] = []
    for oracle in _window_oracles(task):
        windows = getattr(oracle, "plan_windows", None)
        if windows is None or not isinstance(windows, Mapping):
            continue
        for reason in _single_window_reasons(task, windows):
            if reason not in reasons:
                reasons.append(reason)
    return reasons


def _window_oracles(task: Task) -> list:
    oracle = getattr(task, "oracle", None)
    if oracle is None:
        return []
    children = getattr(oracle, "sub_oracles", None) or ()
    return list(children) if children else [oracle]


def _single_window_reasons(task: Task, windows: Mapping) -> list[str]:
    profile = getattr(getattr(task, "s0", None), "profile", None)
    daily = getattr(profile, "windows", None) or {}
    for lo, hi in windows.values():
        if float(lo) > float(hi):
            return [REASON_WINDOWS_EMPTY]
    for key, (lo, hi) in windows.items():
        bounds = daily.get(key)
        if bounds is None:
            continue
        daily_hi = float(bounds[1])
        if float(lo) < 0.0 or float(hi) > daily_hi or float(lo) > daily_hi:
            return [REASON_WINDOWS_OUT_OF_BOUNDS]
    if _kcal_infeasible(windows):
        return [REASON_WINDOWS_UNPASSABLE]
    return []


def _kcal_infeasible(windows: Mapping) -> bool:
    """No food combination can satisfy the kcal window given macro floors/ceilings.

    Every kcal comes from protein/carb/fat at Atwater rates (4/4/9 kcal per g,
    matching ``nutrienv.bench.windows.KCAL_RATIO_CAP``). Macro floors force a
    minimum kcal; macro ceilings cap the reachable kcal. The check is physics,
    so it needs no catalog. An absent macro span is unconstrained, not zero:
    it adds nothing to the forced minimum but leaves the reachable kcal
    unbounded.
    """
    kcal = windows.get("kcal")
    if not isinstance(kcal, (tuple, list)) or len(kcal) != 2:
        return False
    kcal_lo, kcal_hi = float(kcal[0]), float(kcal[1])
    forced = 0.0
    reachable = 0.0
    unbounded = False
    for key, rate in _ATWATER_KCAL_PER_G.items():
        span = windows.get(key)
        if not isinstance(span, (tuple, list)) or len(span) != 2:
            unbounded = True
            continue
        forced += rate * max(0.0, float(span[0]))
        reachable += rate * max(0.0, float(span[1]))
    if forced > kcal_hi + 1e-6:
        return True
    return not unbounded and reachable + 1e-6 < kcal_lo


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


def stage_b_leak_scan(task: Task) -> list[str]:
    """Code leak scan for Recommend candidates. Empty means clean.

    Mapped to the landed 07/08 realizations:
    - leftover (``realize._leftover_from_row``): a non-empty S0 ledger must be
      bound into scoring through pinned ``plan_windows``; an eaten timeline
      with unpinned windows leaks the leftover context.
    - remaining-kcal (``nutrienv.world.daily_windows.meal_slot_and_remainder``
      as applied by ``generate_one._recommend_from_template``): pinned windows
      may never budget more of a nutrient than the day still has left after
      the ledger.
    - allergy: S0 ledger foods and oracle/s0 plan items carrying a
      profile-banned allergen tag make the world or the named dish unsafe.
      The tag-vs-profile comparison mirrors ``realize.bind_evaluate_reasons``
      (which applies it to the evaluated plate); here it covers the ledger
      and both plan sides so a Recommend whose named-dish plan item carries a
      banned allergen is flagged even with an empty ledger.
    Naturalness alone never drops; that is what the Stage B votes are for.
    """
    if task.family != "recommend":
        return []
    s0 = task.s0
    oracle = task.oracle
    catalog = s0.catalog if isinstance(s0.catalog, Mapping) else {}
    profile = getattr(s0, "profile", None)
    daily = dict(getattr(profile, "windows", None) or {})
    allergies = set(normalize_tags(list(getattr(profile, "allergies", None) or [])))
    ledger = list(getattr(s0, "ledger", None) or [])
    pinned = getattr(oracle, "plan_windows", None)
    reasons: list[str] = []
    if ledger:
        if pinned is None:
            reasons.append(REASON_LEAK_LEFTOVER)
        else:
            eaten = ledger_totals(ledger, catalog)
            for key, (lo, hi) in daily.items():
                used = eaten.get(key, 0.0)
                remaining_hi = round(max(0.0, float(hi) - used), 2)
                span = pinned.get(key)
                if not isinstance(span, (tuple, list)) or len(span) != 2:
                    continue
                if float(span[1]) > remaining_hi + 1e-6:
                    reasons.append(REASON_LEAK_REMAINING_KCAL)
                    break
    food_ids = [row.food_id for row in ledger]
    for plan in (
        getattr(oracle, "last_plan", None) or [],
        getattr(oracle, "evaluated_plan", None) or [],
        getattr(s0, "last_plan", None) or [],
    ):
        for item in plan:
            if isinstance(item, Mapping) and item.get("food_id") is not None:
                food_ids.append(str(item["food_id"]))
    for food_id in food_ids:
        entry = catalog.get(food_id) or {}
        tags = set(normalize_tags(list(entry.get("allergen_tags") or [])))
        if tags & allergies:
            reasons.append(REASON_LEAK_ALLERGY)
            break
    return reasons


def format_stage_b_prompt(task: Task) -> str:
    """Speech view: query + food names. No grams, no windows."""
    names = [str(item["name"]) for item in resolved_items(task)]
    lines = ["Here is one user's spoken request.", f"Query: {task.query}"]
    if names:
        lines.append("Foods involved: " + ", ".join(names))
    return "\n".join(lines)


def review_candidates(
    candidates: Sequence[Task],
    *,
    stage_a: Mapping[str, ReviewFn],
    stage_b: Mapping[str, ReviewFn],
    parse_retries: int = PARSE_RETRIES,
) -> dict[str, object]:
    """Stage A code-gate, then Stage A votes, then Stage B.

    Code fail (Stage A gate or Stage B leak scan) drops without an LLM vote.
    LLM majority-fail raises an alarm; it never silently passes and never
    drops. The leak scan is recommend-only; the speech vote runs for every
    candidate that survives the leak scan, because Stage A deliberately
    hides the query.
    """
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
            "stage_a": {"code_gate": list(gate), "votes": {}, "majority": "none"},
            "stage_b": {"leak_scan": [], "votes": {}, "majority": "none"},
            "dropped": bool(gate),
            "alarm": False,
            "anomaly": False,
        }
        if gate:
            dropped.append({"id": task.id, "reasons": list(gate), "stage": "stage_a"})
            entry["verdict"] = "drop_code_gate"
            per_candidate[task.id] = entry
            continue
        result_a, anomalies_a = _run_stage_vote(stage_a, format_stage_a_prompt(task), parse_retries)
        entry["stage_a"].update(result_a)
        if anomalies_a:
            entry["anomaly"] = True
            anomalies.append({"id": task.id, "stage": "stage_a"})
        if result_a["majority"] != "pass":
            entry["alarm"] = True
        leaks = stage_b_leak_scan(task)
        entry["stage_b"]["leak_scan"] = list(leaks)
        if leaks:
            entry["dropped"] = True
            entry["verdict"] = "drop_leak_scan"
            dropped.append({"id": task.id, "reasons": list(leaks), "stage": "stage_b"})
            per_candidate[task.id] = entry
            continue
        result_b, anomalies_b = _run_stage_vote(
            stage_b, format_stage_b_prompt(task), parse_retries
        )
        entry["stage_b"].update(result_b)
        if anomalies_b:
            entry["anomaly"] = True
            anomalies.append({"id": task.id, "stage": "stage_b"})
        if result_b["majority"] != "pass":
            entry["alarm"] = True
        if entry["alarm"]:
            entry["verdict"] = "alarm_majority"
        else:
            entry["verdict"] = "pass"
        per_candidate[task.id] = entry
    return {
        "anomalies": anomalies,
        "dropped": dropped,
        "per_candidate": per_candidate,
    }


def _run_stage_vote(
    voters: Mapping[str, ReviewFn], prompt: str, parse_retries: int
) -> tuple[dict[str, object], int]:
    """k=3 vote collection + JSON parsing + majority. Returns (result, unparsed count)."""
    votes: dict[str, dict[str, object]] = {}
    unparsed = 0
    for model_id in sorted(voters):
        text = ""
        vote: tuple[bool, str] | None = None
        for _attempt in range(1 + parse_retries):
            text = voters[model_id](prompt) or ""
            vote = _parse_vote(text)
            if vote is not None:
                break
        if vote is None:
            unparsed += 1
            votes[model_id] = {"raw": text, "eatable": None, "reason": ""}
        else:
            votes[model_id] = {"raw": text, "eatable": vote[0], "reason": vote[1]}
    yes = sum(1 for v in votes.values() if v["eatable"] is True)
    no = sum(1 for v in votes.values() if v["eatable"] is False)
    if yes >= 2:
        majority = "pass"
    elif no >= 2:
        majority = "fail"
    else:
        majority = "undecided"
    return {"votes": votes, "majority": majority}, unparsed


def _parse_vote(text: str) -> tuple[bool, str] | None:
    """Extract {"eatable": bool, "reason": str} from one voter reply."""
    blob = _json_blob(text or "")
    if blob is None:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, Mapping):
        return None
    eatable = data.get("eatable")
    if not isinstance(eatable, bool):
        return None
    reason = data.get("reason", "")
    reason = "" if reason is None else str(reason)
    return True if eatable else False, reason


def make_reviewer(
    stage_a: Mapping[str, ReviewFn] | None = None,
    stage_b: Mapping[str, ReviewFn] | None = None,
    *,
    parse_retries: int = PARSE_RETRIES,
) -> Reviewer:
    """Bind per-stage callables (or live model ids) into a ``Reviewer``."""
    bound_a = dict(stage_a) if stage_a is not None else {
        model_id: _live_caller(model_id, STAGE_A_SYSTEM) for model_id in STAGE_A_MODEL_IDS
    }
    bound_b = dict(stage_b) if stage_b is not None else {
        model_id: _live_caller(model_id, STAGE_B_SYSTEM) for model_id in STAGE_B_MODEL_IDS
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


def _live_caller(model_id: str, system: str = STAGE_A_SYSTEM) -> ReviewFn:
    def call(prompt: str, *, _id: str = model_id, _system: str = system) -> str:
        return call_reviewer(_id, prompt, system=_system)

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
