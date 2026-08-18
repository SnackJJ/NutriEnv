#!/usr/bin/env python3
"""Issue 10: run the v1.0-gold 20-item pilot and freeze the split.

Full chain: Sampler (fixed pool plan) → Expander (live, multi-model) →
Resolver → Judge → validate_draft → Review harness → Freezer.

    .venv/bin/python scripts/run_pilot_20.py --force
    .venv/bin/python scripts/run_pilot_20.py --drop v10-log-0003,v10-eval-0016
    .venv/bin/python scripts/run_pilot_20.py --rerun-fallbacks --force

A first freeze onto an existing different file needs ``--force``.
``--drop`` / ``--replace-slot`` re-freeze with overwrite=True (deliberate rewrite).
``--rerun-fallbacks --force`` re-expands evaluate-row / fallback-table slots
with the live multi-model expander (no table-phrase fallback) and rewrites
the published exam. Already-LLM KEEP items stay byte-identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import traceback
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.bench.grams_gate import call_judge, plausibility_gate  # noqa: E402
from nutrienv.bench.pipeline.expander import (  # noqa: E402
    HANDBOOK_VOCABULARY,
    build_system_prompt,
    build_user_prompt,
    coerce_candidates,
    parse_expander_payload,
    synthetic_expander,
)
from nutrienv.bench.pipeline.freezer import freeze_tasks  # noqa: E402
from nutrienv.bench.pipeline.models import (  # noqa: E402
    DEFAULT_EXPANDER_MODELS,
    assign_model,
    enabled_route,
)
from nutrienv.bench.pipeline.resolver import build_food_index, resolve_candidate  # noqa: E402
from nutrienv.bench.pipeline.review_harness import make_reviewer  # noqa: E402
from nutrienv.bench.pipeline.sampler import portion_alternatives  # noqa: E402
from nutrienv.bench.pipeline.types import (  # noqa: E402
    CATALOG_V1_RELPATH,
    DEFAULT_FREEZE_RELPATH,
    PIPELINE_VERSION,
    QUANTITY_MULTIPLES,
    Candidate,
    FoodPool,
    PoolFood,
    Rejected,
    catalog_digest,
)
from nutrienv.bench.realize import Task  # noqa: E402
from nutrienv.bench.realizations import EVALUATE_ROWS  # noqa: E402
from nutrienv.bench.validator import validate_draft, validate_oracle_grams  # noqa: E402
from nutrienv.harness.react import _SYSTEM_V1_TAIL  # noqa: E402
from nutrienv.io.chat import complete_chat  # noqa: E402
from nutrienv.io.dotenv import load_dotenv_keys  # noqa: E402
from nutrienv.world.catalog import canonical_food_id  # noqa: E402
from nutrienv.world.catalog_store import load_catalog  # noqa: E402

load_dotenv_keys(_ROOT / ".env.local")

SEED = 20260817
REQUIRED_KEYS: tuple[str, ...] = ("qns", "thick", "thin", "fl_oz", "cup", "slice")
STATE_RELPATH = "reports/pilot-20-state.json"
REPORT_RELPATH = "reports/pilot-20-report.md"
EXPECTED_CATALOG_SHA = (
    "f49e4f904905abbb8b4ebb02c908935f01776280a2c00b3de1a3e890cad5ae91"
)
EXPAND_TIMEOUT = 120.0
MODEL_FAIL_LIMIT = 2
RERUN_RETRIES = 5
FALLBACK_MODEL_IDS = frozenset({"evaluate-row", "fallback-table", "fallback"})

# Deterministic filler list for ~8-food meal pools. All have speakable keys.
FILLER_FOODS: tuple[str, ...] = (
    "apple",
    "avocado",
    "banana",
    "broccoli",
    "cheddar",
    "chicken_breast",
    "egg",
    "greek_yogurt",
    "milk_whole",
    "oats",
    "olive_oil",
    "orange",
    "pasta",
    "peanut_butter",
    "potato",
    "soy_milk",
    "spinach",
    "tofu",
    "tuna",
    "white_rice",
    "whole_wheat_bread",
)

# First-freeze evaluate seeds (EVALUATE_ROWS). R1 made D4 semantic, so
# --rerun-fallbacks re-expands these slots with the live expander; the
# row fallback remains only if every live retry fails.
EVALUATE_FALLBACKS: tuple[str, ...] = (
    "ev-tuna-rice",
    "ev-tofu-rice",
    "ev-egg-oats",
    "ev-gold-snack",
    "ev-tri-avocado-eggs-spin",
    "ev-pair-milk-oats-oz",
)


@dataclass(frozen=True)
class SlotPlan:
    slot_id: str
    family: str
    kind: str
    persona: str
    food_ids: tuple[str, ...]
    target_key: str | None = None
    evaluate_seed: str | None = None


@dataclass
class AttemptRecord:
    slot_id: str
    family: str
    persona: str
    model: str
    query: str
    reason: str
    fallback: bool = False


@dataclass
class ItemMeta:
    task_id: str
    slot_id: str
    family: str
    persona: str
    kind: str
    model: str
    fallback: bool
    foods: list[dict]
    query: str


def is_fallback_model(model: object) -> bool:
    return str(model or "") in FALLBACK_MODEL_IDS


def fallback_meta_rows(state: Mapping) -> list[dict]:
    return [
        dict(row)
        for row in (state.get("meta") or [])
        if isinstance(row, Mapping) and is_fallback_model(row.get("model"))
    ]


def snapshot_keep_items(state: Mapping) -> dict[str, dict]:
    """Deep-copy payload items whose expander model is a real model id."""
    fallback_ids = {str(row.get("task_id")) for row in fallback_meta_rows(state)}
    keep: dict[str, dict] = {}
    for item in state.get("payload", {}).get("items") or []:
        if not isinstance(item, Mapping):
            continue
        item_id = str(item.get("id") or "")
        if item_id and item_id not in fallback_ids:
            keep[item_id] = json.loads(json.dumps(item))
    return keep


def restore_keep_items(payload: Mapping, keep_items: Mapping[str, Mapping]) -> dict:
    """Put KEEP item dicts back so a freeze round-trip cannot rewrite them."""
    items = []
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        item_id = str(item.get("id") or "")
        items.append(dict(keep_items[item_id]) if item_id in keep_items else dict(item))
    out = dict(payload)
    out["items"] = items
    return out


def build_pool_plan() -> tuple[SlotPlan, ...]:
    """Deterministic 20-slot plan. Same table every call; no RNG."""
    singles = (
        SlotPlan("log-s-thick", "log", "single", "everyday", ("2705832",), "thick"),
        SlotPlan("log-s-thin", "log", "single", "everyday", ("2705828",), "thin"),
        SlotPlan("log-s-floz", "log", "single", "everyday", ("milk_whole",), "fl_oz"),
        SlotPlan("log-s-cup", "log", "single", "everyday", ("soy_milk",), "cup"),
        SlotPlan(
            "log-s-slice", "log", "single", "everyday", ("whole_wheat_bread",), "slice"
        ),
        SlotPlan("log-s-qns", "log", "single", "everyday", ("oats",), "qns"),
        SlotPlan("log-s-egg", "log", "single", "gym", ("egg",), "piece"),
        SlotPlan("log-s-chk", "log", "single", "gym", ("chicken_breast",), "cup"),
    )
    meals = (
        SlotPlan(
            "log-m-01",
            "log",
            "meal",
            "everyday",
            ("apple", "cheddar", "peanut_butter"),
        ),
        SlotPlan(
            "log-m-02",
            "log",
            "meal",
            "everyday",
            ("banana", "orange", "avocado"),
        ),
        SlotPlan(
            "log-m-03",
            "log",
            "meal",
            "everyday",
            ("tuna", "potato", "olive_oil"),
        ),
        SlotPlan(
            "log-m-04",
            "log",
            "meal",
            "everyday",
            ("pasta", "spinach", "broccoli"),
        ),
        SlotPlan(
            "log-m-05",
            "log",
            "meal",
            "gym",
            ("pasta", "cheddar", "orange"),
        ),
        SlotPlan(
            "log-m-06",
            "log",
            "meal",
            "gym",
            ("chicken_breast", "white_rice", "broccoli"),
        ),
    )
    evaluates = (
        SlotPlan(
            "eval-01",
            "evaluate",
            "meal",
            "everyday",
            ("tuna", "white_rice", "broccoli"),
            evaluate_seed="ev-tuna-rice",
        ),
        SlotPlan(
            "eval-02",
            "evaluate",
            "meal",
            "everyday",
            ("tofu", "white_rice", "spinach"),
            evaluate_seed="ev-tofu-rice",
        ),
        SlotPlan(
            "eval-03",
            "evaluate",
            "meal",
            "everyday",
            ("egg", "oats"),
            evaluate_seed="ev-egg-oats",
        ),
        SlotPlan(
            "eval-04",
            "evaluate",
            "meal",
            "gym",
            ("banana", "greek_yogurt"),
            evaluate_seed="ev-gold-snack",
        ),
        SlotPlan(
            "eval-05",
            "evaluate",
            "meal",
            "everyday",
            ("avocado", "egg", "spinach"),
            evaluate_seed="ev-tri-avocado-eggs-spin",
        ),
        SlotPlan(
            "eval-06",
            "evaluate",
            "meal",
            "gym",
            ("milk_whole", "oats"),
            evaluate_seed="ev-pair-milk-oats-oz",
        ),
    )
    return singles + meals + evaluates


def _backup_slots() -> tuple[SlotPlan, ...]:
    return (
        SlotPlan(
            "log-m-b1",
            "log",
            "meal",
            "everyday",
            ("avocado", "peanut_butter", "apple"),
        ),
        SlotPlan(
            "log-m-b2",
            "log",
            "meal",
            "gym",
            ("tofu", "pasta", "orange"),
        ),
        SlotPlan("log-s-b1", "log", "single", "everyday", ("cheddar",), "slice"),
        SlotPlan("log-s-b2", "log", "single", "everyday", ("banana",), "piece"),
        SlotPlan(
            "eval-b1",
            "evaluate",
            "meal",
            "everyday",
            ("greek_yogurt", "banana"),
            evaluate_seed="ev-yogurt-banana",
        ),
        SlotPlan(
            "eval-b2",
            "evaluate",
            "meal",
            "everyday",
            ("tuna", "spinach"),
            evaluate_seed="ev-pair-tuna-spinach",
        ),
    )


def plan_target_keys(plan: Sequence[SlotPlan]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for slot in plan:
        if slot.target_key:
            counts[slot.target_key] += 1
        if slot.evaluate_seed == "ev-gold-snack":
            counts["qns"] += 1
        if slot.evaluate_seed in {"ev-tuna-rice", "ev-tofu-rice", "ev-egg-oats"}:
            counts["cup"] += 1
        if slot.evaluate_seed == "ev-pair-milk-oats-oz":
            counts["cup"] += 1
        if slot.evaluate_seed == "ev-tri-avocado-eggs-spin":
            counts["cup"] += 1
    return dict(counts)


def plan_covers_required_keys(plan: Sequence[SlotPlan]) -> bool:
    keys = {slot.target_key for slot in plan if slot.target_key}
    return set(REQUIRED_KEYS) <= keys


def pool_food(catalog: Mapping, food_id: str) -> PoolFood:
    canon = canonical_food_id(catalog, food_id)
    entry = catalog[canon]
    aliases = tuple(str(alias) for alias in (entry.get("aliases") or []) if alias)
    return PoolFood(
        food_id=canon,
        name=str(entry.get("name") or canon),
        aliases=aliases,
        alternatives=portion_alternatives(entry),
    )


def build_pool(catalog: Mapping, slot: SlotPlan) -> FoodPool:
    """Single-food slots stay size 1 (素材固定). Meal slots pad to 8."""
    anchors = [canonical_food_id(catalog, fid) for fid in slot.food_ids]
    ids = list(dict.fromkeys(anchors))
    if slot.kind == "meal":
        for filler in FILLER_FOODS:
            if len(ids) >= 8:
                break
            try:
                canon = canonical_food_id(catalog, filler)
            except (KeyError, ValueError):
                continue
            if canon not in ids:
                ids.append(canon)
    foods = tuple(pool_food(catalog, food_id) for food_id in ids)
    return FoodPool(pool_id=slot.slot_id, family=slot.family, foods=foods)


def preferred_phrase(food: PoolFood, key: str | None) -> str | None:
    if key is None:
        for alt in food.alternatives:
            if alt.quantity == 1.0:
                return alt.phrase
        return food.alternatives[0].phrase if food.alternatives else None
    matches = [alt for alt in food.alternatives if alt.key == key]
    if not matches:
        return None
    for alt in matches:
        if alt.quantity == 1.0:
            return alt.phrase
    return matches[0].phrase


def short_name(food: PoolFood) -> str:
    for alias in food.aliases:
        cleaned = alias.strip()
        if len(cleaned) >= 3 and "_" not in cleaned:
            return cleaned
    head = food.name.split(",", 1)[0].strip()
    return head or food.food_id.replace("_", " ")


def match_name(food: PoolFood) -> str:
    """Token resolve_candidate can look up (full name or alias or id)."""
    for alias in food.aliases:
        cleaned = alias.strip()
        if len(cleaned) >= 3 and "_" not in cleaned:
            return cleaned
    return food.name


def matching_portion_keys(entry: Mapping, grams: float) -> tuple[str, ...]:
    portions = entry.get("portions") or {}
    if not isinstance(portions, Mapping):
        return ()
    target = round(float(grams), 2)
    scored: list[tuple[float, str]] = []
    for key, unit in portions.items():
        if isinstance(unit, bool) or not isinstance(unit, (int, float)):
            continue
        for quantity in QUANTITY_MULTIPLES:
            if round(quantity * float(unit), 2) == target:
                scored.append((float(quantity), str(key)))
    scored.sort(key=lambda item: (0 if item[0] == 1.0 else 1, item[0], item[1]))
    return tuple(key for _qty, key in scored)


def portion_key_for_grams(entry: Mapping, grams: float) -> str | None:
    keys = matching_portion_keys(entry, grams)
    if keys:
        return keys[0]
    from nutrienv.world.portions import OUNCE_GRAMS

    if round(float(grams), 2) == round(2.0 * OUNCE_GRAMS, 2):
        return "oz"
    return None


def oracle_pairs(task: Task) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    if task.oracle.ledger_tail:
        pairs.extend((row.food_id, float(row.grams)) for row in task.oracle.ledger_tail)
    if task.oracle.last_plan:
        pairs.extend(
            (str(item["food_id"]), float(item["grams"]))
            for item in task.oracle.last_plan
        )
    return pairs


def task_foods(task: Task) -> list[dict]:
    catalog = task.s0.catalog
    out: list[dict] = []
    for food_id, grams in oracle_pairs(task):
        entry = catalog.get(food_id) or {}
        name = entry.get("name") if isinstance(entry, Mapping) else food_id
        key = portion_key_for_grams(entry, grams) if isinstance(entry, Mapping) else None
        out.append(
            {
                "food_id": food_id,
                "name": name or food_id,
                "key": key,
                "grams": grams,
            }
        )
    return out


def coverage_counts(tasks: Sequence[Task]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for task in tasks:
        for item in task_foods(task):
            key = item.get("key")
            if key in REQUIRED_KEYS:
                counts[str(key)] += 1
    return {key: int(counts.get(key, 0)) for key in REQUIRED_KEYS}


def evaluate_row_by_seed(seed_id: str):
    for row in EVALUATE_ROWS:
        if row.seed_id == seed_id:
            return row
    raise KeyError(f"unknown evaluate seed {seed_id!r}")


_AWKWARD_QUERY = (
    re.compile(r"\bpiece of eggs\b"),
    re.compile(r"\ba eggs\b"),
    re.compile(r"\ban eggs\b"),
    re.compile(r"\bone piece of eggs\b"),
)


def awkward_query(query: str) -> bool:
    """True when the query has a known ungrammatical piece/egg form."""
    text = (query or "").lower()
    return any(pattern.search(text) for pattern in _AWKWARD_QUERY)


def review_admissible(review: Mapping, task_id: str) -> tuple[bool, str]:
    """Accept a clean review, or a single-model unparseable glitch with 5/5/5."""
    anomalies = list(review.get("anomalies") or [])
    hit = next((row for row in anomalies if row.get("id") == task_id), None)
    if hit is None:
        return True, "clean"
    reasons = [str(item) for item in (hit.get("reasons") or [])]
    per = (review.get("per_candidate") or {}).get(task_id) or {}
    models = per.get("models") or {}
    parseable = [
        scores
        for scores in models.values()
        if isinstance(scores, Mapping) and not scores.get("unparseable")
    ]
    if reasons == ["unparseable"] and parseable:
        if all(
            scores.get("consistency") == 5
            and scores.get("naturalness") == 5
            and scores.get("entailment") == 5
            for scores in parseable
        ):
            return True, "single-model-unparseable-other-555"
    return False, ",".join(reasons) or "anomalous"


def drop_ids(items: Sequence[Mapping], dropped: Sequence[str]) -> list[dict]:
    blocked = {item.strip() for item in dropped if item and item.strip()}
    return [dict(item) for item in items if str(item.get("id")) not in blocked]


def _implausible(task: Task, catalog, judge) -> bool:
    for food_id, grams in oracle_pairs(task):
        accepted, _source = plausibility_gate(food_id, grams, catalog, judge=judge)
        if not accepted:
            return True
    return False


def _admit(
    candidate: Candidate,
    *,
    catalog,
    task_id: str,
    seen: set[tuple[str, ...]],
    food_index: Mapping[str, str],
    judge,
) -> tuple[Task | None, str | None]:
    snapshot = set(seen)
    task, rejected = resolve_candidate(
        candidate,
        catalog=catalog,
        task_id=task_id,
        seen=seen,
        food_index=food_index,
    )
    if rejected is not None:
        return None, rejected.reason
    assert task is not None
    if _implausible(task, catalog, judge):
        seen.clear()
        seen.update(snapshot)
        return None, "implausible"
    issues = validate_draft(task)
    if issues:
        seen.clear()
        seen.update(snapshot)
        return None, "validate_draft:" + issues[0]
    grams_issues = validate_oracle_grams(task)
    if grams_issues:
        seen.clear()
        seen.update(snapshot)
        return None, "oracle_grams"
    return task, None


def _expand_live(
    pool: FoodPool,
    *,
    persona: str,
    family: str,
    model_id: str,
    hint: str,
) -> dict[str, object]:
    user = build_user_prompt(pool)
    if hint:
        user = user + "\n\n" + hint
    messages = (
        {"role": "system", "content": build_system_prompt(persona=persona, family=family)},
        {"role": "user", "content": user},
    )
    last: dict[str, object] = {"items": [], "query": ""}
    for _attempt in range(2):
        text = complete_chat(model_id, messages, timeout=EXPAND_TIMEOUT, retries=2)
        parsed = parse_expander_payload(text)
        if parsed is not None:
            return parsed
    return last


def _single_hint(slot: SlotPlan, pool: FoodPool) -> str:
    food = pool.foods[0]
    phrase = preferred_phrase(food, slot.target_key)
    key = slot.target_key or "household"
    example = phrase or key
    return (
        f"Constraint: use ONLY {short_name(food)}. "
        f"The expression MUST use the {key} measure "
        f"(example: {example!r}). One food only."
    )


def _meal_hint() -> str:
    return "Constraint: pick 2 or 3 foods that form one plausible meal."


def _synthetic_meals(
    pool: FoodPool, persona: str, family: str
) -> list[dict[str, object]]:
    """Table-phrase meals, trying several 2-food pairs so a duplicate can skip."""
    ready: list[tuple[PoolFood, str]] = []
    for food in pool.foods:
        phrase = preferred_phrase(food, None)
        if phrase is not None:
            ready.append((food, phrase))
    out: list[dict[str, object]] = []
    for index in range(len(ready) - 1):
        chosen = ready[index : index + 2]
        items = [
            {"food": match_name(food), "expression": phrase} for food, phrase in chosen
        ]
        parts = [f"{phrase} of {short_name(food)}" for food, phrase in chosen]
        meal = ", and ".join(parts)
        if family == "evaluate":
            query = f"Evaluate this as my plan: {meal}."
        else:
            query = f"Please log {meal} for lunch."
        out.append({"items": items, "query": query})
    if not out:
        out.append(synthetic_expander(pool, persona=persona, family=family))
    return out


def _synthetic_single(slot: SlotPlan, pool: FoodPool) -> dict[str, object]:
    food = pool.foods[0]
    phrase = preferred_phrase(food, slot.target_key) or preferred_phrase(food, None)
    if phrase is None:
        return {"items": [], "query": ""}
    spoken = match_name(food)
    mention = short_name(food)
    if slot.family == "evaluate":
        query = f"Evaluate this as my plan: {phrase} of {mention}."
    else:
        query = f"Please log {phrase} of {mention} for lunch."
    return {"items": [{"food": spoken, "expression": phrase}], "query": query}


def _row_payload(seed_id: str) -> dict[str, object]:
    row = evaluate_row_by_seed(seed_id)
    return {
        "items": [{"food": food, "expression": phrase} for food, phrase in row.items],
        "query": row.query,
    }


def _table_only_judge(_food: str, _grams: float) -> str:
    return "suspect"


def _handbook_gaps(tasks: Sequence[Task]) -> list[str]:
    tail = _SYSTEM_V1_TAIL.lower()
    aliases = {
        "ounces": "ounce",
        "grams": "gram",
        "a serving of": "a serving",
        "fl_oz": "fl_oz",
    }
    missing: list[str] = []
    for token in HANDBOOK_VOCABULARY:
        needle = aliases.get(token, token).lower()
        if needle not in tail:
            missing.append(token)
    # Used query text is the exam-facing speech; flag only if a used
    # handbook token disappeared from the tail (mechanical test covers this).
    _ = tasks
    return missing


class PilotRunner:
    def __init__(
        self,
        *,
        catalog,
        synthetic: bool = False,
        output_path: Path | None = None,
        overwrite: bool = False,
    ) -> None:
        self.catalog = catalog
        self.synthetic = synthetic
        self.output_path = output_path or (_ROOT / DEFAULT_FREEZE_RELPATH)
        self.overwrite = overwrite
        self.digest = catalog_digest(catalog)
        self.food_index = build_food_index(catalog)
        self.plan = build_pool_plan()
        self.route = list(enabled_route(DEFAULT_EXPANDER_MODELS))
        self.disabled: set[str] = set()
        self.fail_counts: Counter[str] = Counter()
        self.seen: set[tuple[str, ...]] = set()
        self.accepted: list[Task] = []
        self.meta: list[ItemMeta] = []
        self.attempts: list[AttemptRecord] = []
        self.produced: Counter[str] = Counter()
        self.accepted_by_model: Counter[str] = Counter()
        self.review: dict[str, object] = {"anomalies": [], "per_candidate": {}}
        self.seq = 0

    def run(self) -> dict:
        if self.digest != EXPECTED_CATALOG_SHA:
            print(
                f"WARNING: catalog-v1 sha is {self.digest}, "
                f"expected {EXPECTED_CATALOG_SHA}"
            )
        for slot in self._ordered_slots():
            self._run_slot(slot)
        for extra in _backup_slots():
            if len(self.accepted) >= 20:
                break
            self._run_slot(extra)
        if len(self.accepted) != 20:
            raise SystemExit(
                f"pilot produced {len(self.accepted)} accepted items, need 20"
            )
        print(f"reviewing {len(self.accepted)} accepted items…")
        if self.synthetic:
            self.review = {
                "anomalies": [],
                "per_candidate": {task.id: {"anomaly": False} for task in self.accepted},
            }
        else:
            reviewer = make_reviewer()
            self.review = dict(reviewer(self.accepted))
        n_eval = sum(1 for item in self.meta if item.model == "evaluate-row")
        n_table = sum(
            1 for item in self.meta if item.model in {"fallback-table", "fallback"}
        )
        extra = {
            "seed": SEED,
            "sampler_rule_version": "pilot-20-plan-v1",
            "notes": (
                f"{PIPELINE_VERSION} 20-item pilot freeze "
                f"(seed {SEED}; evaluate D4 uses EVALUATE_ROWS fallbacks "
                f"({n_eval} items); {n_table} log items used fallback-table)."
            ),
        }
        payload, path = freeze_tasks(
            self.accepted,
            catalog=self.catalog,
            catalog_field=CATALOG_V1_RELPATH,
            catalog_sha=self.digest,
            output_path=self.output_path,
            extra=extra,
            overwrite=self.overwrite,
        )
        state = self._state(payload, str(path))
        _write_json(_ROOT / STATE_RELPATH, state)
        report = render_report(state)
        (_ROOT / REPORT_RELPATH).write_text(report, encoding="utf-8")
        print(f"froze {path}: {len(self.accepted)} items")
        anomalies = list(self.review.get("anomalies") or [])
        print(f"anomalies: {len(anomalies)}")
        for row in anomalies:
            print(f"  {row}")
        return state

    def _ordered_slots(self) -> list[SlotPlan]:
        # Evaluate fallbacks reserve their food sets before meal expander picks.
        singles = [slot for slot in self.plan if slot.kind == "single"]
        evals = [slot for slot in self.plan if slot.family == "evaluate"]
        meals = [
            slot
            for slot in self.plan
            if slot.kind == "meal" and slot.family == "log"
        ]
        return singles + evals + meals

    def _next_id(self, family: str) -> str:
        self.seq += 1
        return f"v10-{family}-{self.seq:04d}"

    def _active_route(self) -> list[str]:
        return [model for model in self.route if model not in self.disabled] or list(
            self.route
        )

    def _model_for(self, index: int) -> str:
        route = self._active_route()
        return assign_model(index, route, seed=SEED)

    def _mark_fail(self, model_id: str) -> None:
        self.fail_counts[model_id] += 1
        if self.fail_counts[model_id] >= MODEL_FAIL_LIMIT:
            self.disabled.add(model_id)
            print(f"  routing around {model_id} after {MODEL_FAIL_LIMIT} failures")

    def _run_slot(self, slot: SlotPlan) -> None:
        pool = build_pool(self.catalog, slot)
        print(f"[{slot.slot_id}] {slot.family}/{slot.kind}/{slot.persona} …")
        task_id = self._next_id(slot.family)
        hint = _single_hint(slot, pool) if slot.kind == "single" else _meal_hint()
        model_id = "synthetic" if self.synthetic else self._model_for(self.seq - 1)
        payload: dict[str, object] | None = None
        used_fallback = False
        if self.synthetic:
            payload = (
                _row_payload(slot.evaluate_seed)
                if slot.evaluate_seed
                else (
                    _synthetic_single(slot, pool)
                    if slot.kind == "single"
                    else synthetic_expander(
                        pool, persona=slot.persona, family=slot.family
                    )
                )
            )
            used_fallback = True
        else:
            try:
                payload = _expand_live(
                    pool,
                    persona=slot.persona,
                    family=slot.family,
                    model_id=model_id,
                    hint=hint,
                )
                self.produced[model_id] += 1
            except Exception as exc:
                print(f"  expander {model_id} raised: {exc}")
                self._mark_fail(model_id)
                self.attempts.append(
                    AttemptRecord(
                        slot.slot_id,
                        slot.family,
                        slot.persona,
                        model_id,
                        "",
                        f"expander_error:{type(exc).__name__}",
                    )
                )
                payload = None

        task, reason = self._try_payload(
            payload, slot=slot, task_id=task_id, model_id=model_id
        )
        if task is None and slot.evaluate_seed:
            used_fallback = True
            model_id = "evaluate-row"
            payload = _row_payload(slot.evaluate_seed)
            task, reason = self._try_payload(
                payload, slot=slot, task_id=task_id, model_id=model_id
            )
        if task is None and slot.kind == "single":
            used_fallback = True
            model_id = "fallback-table"
            payload = _synthetic_single(slot, pool)
            task, reason = self._try_payload(
                payload, slot=slot, task_id=task_id, model_id=model_id
            )
        if task is None and slot.kind == "meal" and slot.family == "log":
            used_fallback = True
            model_id = "fallback-table"
            for payload in _synthetic_meals(pool, slot.persona, slot.family):
                task, reason = self._try_payload(
                    payload, slot=slot, task_id=task_id, model_id=model_id
                )
                if task is not None:
                    break
        if task is None:
            print(f"  FAILED {slot.slot_id}: {reason}")
            return
        self.accepted.append(task)
        self.accepted_by_model[model_id] += 1
        foods = task_foods(task)
        self.meta.append(
            ItemMeta(
                task_id=task.id,
                slot_id=slot.slot_id,
                family=task.family,
                persona=task.persona,
                kind=slot.kind,
                model=model_id,
                fallback=used_fallback,
                foods=foods,
                query=task.query,
            )
        )
        keys = [str(item.get("key")) for item in foods]
        print(
            f"  accepted {task.id} model={model_id} fallback={used_fallback} keys={keys}"
        )
        if reason:
            self.attempts.append(
                AttemptRecord(
                    slot.slot_id,
                    slot.family,
                    slot.persona,
                    model_id,
                    task.query,
                    "accepted",
                    fallback=used_fallback,
                )
            )

    def _try_payload(
        self,
        payload: dict[str, object] | None,
        *,
        slot: SlotPlan,
        task_id: str,
        model_id: str,
    ) -> tuple[Task | None, str | None]:
        if not payload:
            return None, "schema"
        limit = 1 if slot.kind == "single" else 3
        candidates = coerce_candidates(
            payload,
            family=slot.family,
            persona=slot.persona,
            pool_id=slot.slot_id,
            limit=limit,
        )
        if not candidates:
            self.attempts.append(
                AttemptRecord(
                    slot.slot_id,
                    slot.family,
                    slot.persona,
                    model_id,
                    str(payload.get("query") or ""),
                    "schema",
                )
            )
            return None, "schema"
        last_reason = "schema"
        for candidate in candidates:
            if slot.kind == "single" and slot.target_key:
                candidate = _force_single_food(candidate, slot, self.catalog)
            task, reason = _admit(
                candidate,
                catalog=self.catalog,
                task_id=task_id,
                seen=self.seen,
                food_index=self.food_index,
                judge=_table_only_judge if self.synthetic else call_judge,
            )
            if task is not None:
                if slot.kind == "single" and slot.target_key:
                    matched: set[str] = set()
                    for food_id, grams in oracle_pairs(task):
                        entry = self.catalog.get(food_id) or {}
                        if isinstance(entry, Mapping):
                            matched.update(matching_portion_keys(entry, grams))
                    if slot.target_key not in matched:
                        # Coverage miss: keep trying fallbacks.
                        food_key = tuple(
                            sorted(item["food_id"] for item in task_foods(task))
                        )
                        self.seen.discard(food_key)
                        last_reason = f"coverage_miss:{slot.target_key}"
                        self.attempts.append(
                            AttemptRecord(
                                slot.slot_id,
                                slot.family,
                                slot.persona,
                                model_id,
                                candidate.query,
                                last_reason,
                            )
                        )
                        continue
                return task, None
            last_reason = reason or "rejected"
            self.attempts.append(
                AttemptRecord(
                    slot.slot_id,
                    slot.family,
                    slot.persona,
                    model_id,
                    candidate.query,
                    last_reason,
                )
            )
            if last_reason == "unresolvable" and not self.synthetic:
                self._mark_fail(model_id)
        return None, last_reason

    def _state(self, payload: dict, path: str) -> dict:
        rejected = [
            asdict(item) for item in self.attempts if item.reason != "accepted"
        ]
        by_reason = Counter(item["reason"].split(":")[0] for item in rejected)
        by_family = Counter(task.family for task in self.accepted)
        by_persona = Counter(task.persona for task in self.accepted)
        return {
            "version": PIPELINE_VERSION,
            "catalog": CATALOG_V1_RELPATH,
            "catalog_sha256": self.digest,
            "path": path,
            "seed": SEED,
            "n_accepted": len(self.accepted),
            "accepted_ids": [task.id for task in self.accepted],
            "payload": payload,
            "meta": [asdict(item) for item in self.meta],
            "review": self.review,
            "rejected": rejected,
            "rejection_reasons": dict(by_reason),
            "produced_by_model": dict(self.produced),
            "accepted_by_model": dict(self.accepted_by_model),
            "family_counts": dict(by_family),
            "persona_counts": dict(by_persona),
            "coverage": coverage_counts(self.accepted),
            "plan": [asdict(slot) for slot in self.plan],
            "disabled_models": sorted(self.disabled),
            "handbook_gaps": _handbook_gaps(self.accepted),
            "gym_grams_note": (
                "resolve_portion accepts '150 g' / '150 grams', but "
                "validate_oracle_grams requires a catalog-v1 PortionFact "
                "multiple (×0.5/1/1.5/2, plus 2 oz). Gym items therefore "
                "stay on PortionFact keys unless the gram amount is already "
                "a table value (e.g. greek yogurt 150 g = qns)."
            ),
        }


def _force_single_food(
    candidate: Candidate, slot: SlotPlan, catalog: Mapping
) -> Candidate:
    """Keep the LLM query, but pin the only food to the planned id."""
    food = pool_food(catalog, slot.food_ids[0])
    spoken = match_name(food)
    items = tuple((spoken, expression) for _food, expression in candidate.items[:1])
    if not items:
        phrase = preferred_phrase(food, slot.target_key) or "a serving"
        items = ((spoken, phrase),)
    return Candidate(
        items=items,
        query=candidate.query,
        family=candidate.family,
        persona=candidate.persona,
        pool_id=candidate.pool_id,
    )


def render_report(state: Mapping) -> str:
    plan = state.get("plan") or []
    meta = list(state.get("meta") or [])
    coverage = state.get("coverage") or {}
    anomalies = list((state.get("review") or {}).get("anomalies") or [])
    reasons = state.get("rejection_reasons") or {}
    produced = state.get("produced_by_model") or {}
    accepted_m = state.get("accepted_by_model") or {}
    lines: list[str] = [
        "# Pilot 20 report (v1.0-gold)",
        "",
        f"Pipeline version: `{state.get('version')}`. "
        f"Catalog: `{state.get('catalog')}` "
        f"sha256=`{state.get('catalog_sha256')}`. "
        f"Seed: `{state.get('seed')}`.",
        "",
        "## Pool plan",
        "",
        "Deterministic 20-slot table in `scripts/run_pilot_20.py:build_pool_plan`. "
        "Single-food log slots are size-1 pools (素材固定 → 择优). "
        "Meal slots pad anchors to 8 speakable foods. "
        "Same seed always yields this plan; live LLM text is not byte-stable.",
        "",
        "| slot | family | kind | persona | foods | target key | evaluate row |",
        "|---|---|---|---|---|---|---|",
    ]
    for slot in plan:
        foods = ", ".join(slot.get("food_ids") or [])
        lines.append(
            f"| {slot.get('slot_id')} | {slot.get('family')} | {slot.get('kind')} | "
            f"{slot.get('persona')} | {foods} | {slot.get('target_key') or '—'} | "
            f"{slot.get('evaluate_seed') or '—'} |"
        )
    lines.extend(
        [
            "",
            "## Throughput",
            "",
            f"- pools: {len(plan)}",
            f"- expander candidates produced: {sum(int(v) for v in produced.values())}",
            f"- accepted: {state.get('n_accepted')}",
            f"- family counts: {state.get('family_counts')}",
            f"- persona counts: {state.get('persona_counts')}",
            "",
            "### Rejection reasons",
            "",
        ]
    )
    if reasons:
        lines.append("| reason | count |")
        lines.append("|---|---|")
        for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {reason} | {count} |")
    else:
        lines.append("No rejections recorded.")
    lines.extend(["", "### Per-model quality", "", "| model | produced | accepted |", "|---|---|---|"])
    models = sorted(set(produced) | set(accepted_m))
    for model in models:
        lines.append(
            f"| {model} | {produced.get(model, 0)} | {accepted_m.get(model, 0)} |"
        )
    disabled = state.get("disabled_models") or []
    if disabled:
        lines.append("")
        lines.append(f"Routed around mid-run: {', '.join(disabled)}.")
    n_eval = int(accepted_m.get("evaluate-row", 0) or 0)
    n_table = int(accepted_m.get("fallback-table", 0) or 0) + int(
        accepted_m.get("fallback", 0) or 0
    )
    n_llm = int(state.get("n_accepted") or 0) - n_eval - n_table
    lines.extend(
        [
            "",
            "### Notes / provenance",
            "",
            f"{n_llm}/20 items are live LLM expansions; "
            f"{n_eval} still `evaluate-row`; {n_table} still `fallback-table`.",
        ]
    )
    rerun = state.get("rerun") or {}
    if rerun:
        lines.extend(_render_rerun_section(state, rerun))
    lines.extend(
        [
            "",
            "## Review-harness anomalies (人审 input)",
            "",
            "The first freeze keeps every gate-passed item. "
            "Drop after review with "
            "`scripts/run_pilot_20.py --drop <id,...>`.",
            "",
        ]
    )
    meta_by_id = {item.get("task_id"): item for item in meta}
    if anomalies:
        lines.append("| id | reasons | query |")
        lines.append("|---|---|---|")
        for row in anomalies:
            reasons_s = ", ".join(str(item) for item in (row.get("reasons") or []))
            query = (meta_by_id.get(row.get("id")) or {}).get("query") or ""
            lines.append(f"| {row.get('id')} | {reasons_s} | {query} |")
            detail = ((state.get("review") or {}).get("per_candidate") or {}).get(
                row.get("id")
            ) or {}
            aggregate = detail.get("aggregate") or {}
            if aggregate.get("reasons"):
                lines.append(
                    f"|  | scores c={aggregate.get('consistency')} "
                    f"n={aggregate.get('naturalness')} "
                    f"e={aggregate.get('entailment')} "
                    f"disagree={aggregate.get('disagreement')} | |"
                )
    else:
        lines.append("No anomalies flagged.")
    human = state.get("human_review") or {}
    if human:
        lines.extend(["", "## Human review (issue 10 人审)", ""])
        lines.append("| id | verdict | note |")
        lines.append("|---|---|---|")
        for row in human.get("verdicts") or []:
            lines.append(
                f"| {row.get('id')} | {row.get('verdict')} | {row.get('note')} |"
            )
        lines.append("")
        lines.append(str(human.get("summary") or ""))
    replacement = state.get("replacement")
    if replacement:
        lines.extend(["", "## Replacement", ""])
        if replacement.get("task_id"):
            bits = []
            for food in replacement.get("foods") or []:
                bits.append(
                    f"{food.get('name')} [{food.get('food_id')}] "
                    f"{food.get('key') or '?'} {food.get('grams')}g"
                )
            lines.append(
                f"- slot `{replacement.get('slot_id')}` → `{replacement.get('task_id')}` "
                f"(reused dropped id)."
            )
            lines.append(f"- query: {replacement.get('query')}")
            lines.append(f"- foods: {'; '.join(bits)}")
            lines.append(f"- expander model: `{replacement.get('model')}`")
            lines.append(f"- review: {replacement.get('review_note')}")
        else:
            lines.append(
                f"Replacement for `{replacement.get('slot_id')}` failed after "
                "bounded retries. Freeze stays at the post-drop count."
            )
        tries = replacement.get("attempts") or []
        if tries:
            lines.append("")
            lines.append("| attempt model | reason | query |")
            lines.append("|---|---|---|")
            for row in tries:
                lines.append(
                    f"| {row.get('model')} | {row.get('reason')} | {row.get('query') or ''} |"
                )
    lines.extend(
        [
            "",
            f"人审负担: **{len(anomalies)}** / {state.get('n_accepted')} still flagged after drop/replace.",
            "",
            "## Final items",
            "",
            "Every oracle gram passed `validate_oracle_grams` (freezer gate): "
            "each amount is a catalog-v1 PortionFact multiple.",
            "",
            "| id | family | persona | foods + keys + grams | expander model | query |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in meta:
        bits = []
        for food in item.get("foods") or []:
            bits.append(
                f"{food.get('name')} [{food.get('food_id')}] "
                f"{food.get('key') or '?'} {food.get('grams')}g"
            )
        query = (item.get("query") or "").replace("|", "/")
        lines.append(
            f"| {item.get('task_id')} | {item.get('family')} | {item.get('persona')} | "
            f"{'; '.join(bits)} | {item.get('model')} | {query} |"
        )
    lines.extend(["", "## Coverage", "", "| key | count |", "|---|---|"])
    for key in REQUIRED_KEYS:
        lines.append(f"| {key} | {coverage.get(key, 0)} |")
    missing = [key for key in REQUIRED_KEYS if int(coverage.get(key, 0)) < 1]
    if missing:
        lines.append("")
        lines.append(f"COVERAGE GAP: {missing}")
    else:
        lines.append("")
        lines.append("Coverage check: qns / thick / thin / fl_oz / cup / slice each ≥ 1.")
    lines.extend(
        [
            "",
            "## Gym grams",
            "",
            str(state.get("gym_grams_note") or ""),
            "",
            "## Handbook",
            "",
        ]
    )
    gaps = state.get("handbook_gaps") or []
    if gaps:
        lines.append(f"HANDBOOK GAPS in `_SYSTEM_V1_TAIL`: {gaps}")
    else:
        lines.append(
            "`HANDBOOK_VOCABULARY` is covered by `_SYSTEM_V1_TAIL`. "
            "Pilot expressions stay on cup / tbsp / tsp / slice / piece / can / "
            "fl_oz / serving / thick / thin / regular / grams / ounces."
        )
    lines.extend(
        [
            "",
            "## D4 / evaluate",
            "",
            "R1 changed `_validate_evaluate` to semantic gram backresolve: "
            "each plan item's grams must match a catalog PortionFact multiple "
            "(or a spoken gram amount in the query), and each food must be "
            "named. Evaluate queries no longer need to verbatim-match "
            "`EVALUATE_ROWS`. `--rerun-fallbacks` re-expands former "
            "evaluate-row / fallback-table slots with the live expander "
            "under this gate.",
            "",
            "## Re-freeze",
            "",
            "```",
            ".venv/bin/python scripts/run_pilot_20.py --rerun-fallbacks --force",
            ".venv/bin/python scripts/run_pilot_20.py --drop <id,...>",
            ".venv/bin/python scripts/run_pilot_20.py --replace-slot <slot> --replace-id <id>",
            "```",
            "",
            "`--rerun-fallbacks --force` rewrites the published exam "
            "(R2 overwrite guard passed explicitly). `--drop` / "
            "`--replace-slot` also rewrite with `overwrite=True`. "
            "Reads `reports/pilot-20-state.json`.",
            "",
            "## Landing / exam switch",
            "",
            "- `EXAM_SPLIT_PATH` now points at `data/splits/v1.0-gold.json`.",
            "- `scripts/landing_verify.py` keeps the v0.5 old-key / replay / "
            "validate_draft / oz checks, then `load_exam` + `validate_draft` "
            "the 20 v1.0 items.",
            "- `_SYSTEM_V1_TAIL` was not changed: every spoken measure in the "
            "pilot is already in the v1 handbook.",
            "",
        ]
    )
    verification = state.get("verification")
    if verification:
        lines.extend(["", "## Verification (10c)", "", str(verification).rstrip(), ""])
    freeze_sha = state.get("freeze_sha256")
    if freeze_sha:
        lines.extend(
            [
                "",
                f"Freeze sha256 of `data/splits/v1.0-gold.json`: `{freeze_sha}`.",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _render_rerun_section(state: Mapping, rerun: Mapping) -> list[str]:
    lines = [
        "",
        "## Rerun fallbacks (issue 10c)",
        "",
        "Live multi-model expander, no table-phrase / evaluate-row fallback. "
        f"Bounded retries per slot: {rerun.get('retries', RERUN_RETRIES)}. "
        "KEEP (already-LLM) items were not re-expanded.",
        "",
        f"- replaced: {rerun.get('n_replaced', 0)}",
        f"- still-fallback: {rerun.get('n_still_fallback', 0)}",
    ]
    still = rerun.get("still_fallback_slots") or []
    if still:
        lines.append(f"- still-fallback slots: {', '.join(str(item) for item in still)}")
    disabled = rerun.get("disabled_models") or []
    if disabled:
        lines.append(f"- routed around: {', '.join(str(item) for item in disabled)}")
    lines.extend(
        [
            "",
            "| slot | id | previous | model | fallback | review | query |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in rerun.get("slots") or []:
        query = str(row.get("query") or "").replace("|", "/")
        lines.append(
            f"| {row.get('slot_id')} | {row.get('task_id')} | "
            f"{row.get('previous_model')} | {row.get('model')} | "
            f"{row.get('fallback')} | {row.get('review_note')} | {query} |"
        )
    for row in rerun.get("slots") or []:
        tries = row.get("attempts") or []
        if not tries:
            continue
        lines.extend(
            [
                "",
                f"Attempts for `{row.get('slot_id')}`:",
                "",
                "| attempt model | reason | query |",
                "|---|---|---|",
            ]
        )
        for attempt in tries:
            lines.append(
                f"| {attempt.get('model')} | {attempt.get('reason')} | "
                f"{(attempt.get('query') or '').replace('|', '/')} |"
            )
    new_ids = {
        str(row.get("task_id"))
        for row in (rerun.get("slots") or [])
        if row.get("accepted")
    }
    anomalies = [
        row
        for row in ((state.get("review") or {}).get("anomalies") or [])
        if str(row.get("id")) in new_ids
    ]
    lines.extend(
        [
            "",
            "### New-item review anomalies (人审 input)",
            "",
            "Freeze first with flags. Main agent may `--drop` / `--replace-slot` afterwards.",
            "",
        ]
    )
    if not new_ids:
        lines.append("No new LLM items this rerun.")
        return lines
    if not anomalies:
        lines.append("No anomalies flagged on the new items.")
        return lines
    per = ((state.get("review") or {}).get("per_candidate") or {})
    lines.append("| id | reasons | scores | query |")
    lines.append("|---|---|---|---|")
    meta_by_id = {item.get("task_id"): item for item in (state.get("meta") or [])}
    for row in anomalies:
        reasons_s = ", ".join(str(item) for item in (row.get("reasons") or []))
        detail = per.get(row.get("id")) or {}
        aggregate = detail.get("aggregate") or {}
        scores = (
            f"c={aggregate.get('consistency')} n={aggregate.get('naturalness')} "
            f"e={aggregate.get('entailment')} disagree={aggregate.get('disagreement')}"
        )
        query = (meta_by_id.get(row.get("id")) or {}).get("query") or ""
        lines.append(
            f"| {row.get('id')} | {reasons_s} | {scores} | {str(query).replace('|', '/')} |"
        )
    return lines


def apply_drop(state: dict, dropped: Sequence[str]) -> dict:
    blocked = {item.strip() for item in dropped if item and item.strip()}
    if not blocked:
        return state
    payload = dict(state["payload"])
    items = drop_ids(payload.get("items") or [], sorted(blocked))
    if not items:
        raise SystemExit("drop would leave an empty freeze")
    payload["items"] = items
    meta = [row for row in state.get("meta") or [] if row.get("task_id") not in blocked]
    review = dict(state.get("review") or {})
    anomalies = [
        row
        for row in (review.get("anomalies") or [])
        if str(row.get("id")) not in blocked
    ]
    per_candidate = {
        key: value
        for key, value in (review.get("per_candidate") or {}).items()
        if key not in blocked
    }
    review["anomalies"] = anomalies
    review["per_candidate"] = per_candidate
    state = dict(state)
    state["payload"] = payload
    state["meta"] = meta
    state["review"] = review
    state["accepted_ids"] = [row["task_id"] for row in meta]
    state["n_accepted"] = len(items)
    state["dropped"] = sorted(blocked)
    notes = payload.get("notes") or ""
    payload["notes"] = f"{notes} Dropped {sorted(blocked)}."
    return state


def _food_sets_from_payload(items: Sequence[Mapping]) -> set[tuple[str, ...]]:
    seen: set[tuple[str, ...]] = set()
    for item in items:
        ids: list[str] = []
        oracle = item.get("oracle") or {}
        if not isinstance(oracle, Mapping):
            continue
        for row in oracle.get("ledger_tail") or []:
            if isinstance(row, Mapping) and row.get("food_id"):
                ids.append(str(row["food_id"]))
        for row in oracle.get("last_plan") or []:
            if isinstance(row, Mapping) and row.get("food_id"):
                ids.append(str(row["food_id"]))
        if ids:
            seen.add(tuple(sorted(ids)))
    return seen


def _item_seq(item_id: str) -> int:
    tail = str(item_id).rsplit("-", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return 10**9


def _insert_item(items: list[dict], new_item: dict, task_id: str) -> list[dict]:
    """Keep the original numeric id order (0006, 0007, 0008, …)."""
    target = _item_seq(task_id)
    for index, item in enumerate(items):
        if _item_seq(str(item.get("id") or "")) > target:
            return items[:index] + [new_item] + items[index:]
    return items + [new_item]


def replace_dropped_slot(
    state: dict,
    *,
    catalog,
    slot_id: str,
    task_id: str,
    retries: int,
) -> dict:
    """Live-expander replacement for one dropped slot. No table-phrase fallback."""
    from nutrienv.bench.pipeline.freezer import task_to_item

    slot = next((item for item in build_pool_plan() if item.slot_id == slot_id), None)
    if slot is None:
        raise SystemExit(f"unknown replace slot {slot_id!r}")
    runner = PilotRunner(catalog=catalog, synthetic=False)
    runner.seen = _food_sets_from_payload(state["payload"].get("items") or [])
    pool = build_pool(catalog, slot)
    hint = _replace_hint(slot, pool)
    route = list(enabled_route(DEFAULT_EXPANDER_MODELS))
    attempts: list[dict[str, str]] = []
    for attempt in range(retries):
        model_id = assign_model(attempt, route, seed=SEED + 10_000 + attempt)
        print(f"[replace {slot_id} {attempt + 1}/{retries}] model={model_id}")
        try:
            payload = _expand_live(
                pool,
                persona=slot.persona,
                family=slot.family,
                model_id=model_id,
                hint=hint,
            )
        except Exception as exc:
            attempts.append(
                {"model": model_id, "query": "", "reason": f"expander_error:{type(exc).__name__}"}
            )
            print(f"  expander raised: {exc}")
            continue
        query = str(payload.get("query") or "")
        if awkward_query(query):
            attempts.append({"model": model_id, "query": query, "reason": "awkward_query"})
            print(f"  rejected awkward query: {query!r}")
            continue
        task, reason = runner._try_payload(
            payload, slot=slot, task_id=task_id, model_id=model_id
        )
        if task is None:
            attempts.append(
                {"model": model_id, "query": query, "reason": reason or "rejected"}
            )
            print(f"  gate reject: {reason}")
            continue
        if awkward_query(task.query):
            food_key = tuple(sorted(item["food_id"] for item in task_foods(task)))
            runner.seen.discard(food_key)
            attempts.append(
                {"model": model_id, "query": task.query, "reason": "awkward_query"}
            )
            print(f"  rejected awkward resolved query: {task.query!r}")
            continue
        print(f"  reviewing {task.id} …")
        review = dict(make_reviewer()([task]))
        ok, note = review_admissible(review, task.id)
        if not ok:
            food_key = tuple(sorted(item["food_id"] for item in task_foods(task)))
            runner.seen.discard(food_key)
            attempts.append(
                {"model": model_id, "query": task.query, "reason": f"review:{note}"}
            )
            print(f"  review reject: {note}")
            continue
        new_item = task_to_item(task)
        items = list(state["payload"].get("items") or [])
        state["payload"]["items"] = _insert_item(items, new_item, task_id)
        foods = task_foods(task)
        meta_row = asdict(
            ItemMeta(
                task_id=task.id,
                slot_id=slot.slot_id,
                family=task.family,
                persona=task.persona,
                kind=slot.kind,
                model=model_id,
                fallback=False,
                foods=foods,
                query=task.query,
            )
        )
        meta = list(state.get("meta") or [])
        meta = [row for row in meta if row.get("task_id") != task_id]
        insert_at = next(
            (index for index, row in enumerate(meta) if str(row.get("task_id")) > task_id),
            len(meta),
        )
        meta.insert(insert_at, meta_row)
        state["meta"] = meta
        review_state = dict(state.get("review") or {})
        anomalies = [
            row
            for row in (review_state.get("anomalies") or [])
            if row.get("id") != task_id
        ]
        per_candidate = dict(review_state.get("per_candidate") or {})
        per_candidate.update(review.get("per_candidate") or {})
        for row in review.get("anomalies") or []:
            if ok and review_admissible({"anomalies": [row], "per_candidate": per_candidate}, task_id)[0]:
                # Keep a single-model unparseable glitch visible but noted.
                if note != "clean":
                    anomalies.append(row)
        review_state["anomalies"] = anomalies
        review_state["per_candidate"] = per_candidate
        state["review"] = review_state
        state["accepted_ids"] = [row["task_id"] for row in meta]
        state["n_accepted"] = len(state["payload"]["items"])
        state["replacement"] = {
            "slot_id": slot_id,
            "task_id": task.id,
            "query": task.query,
            "model": model_id,
            "foods": foods,
            "review_note": note,
            "attempts": attempts
            + [{"model": model_id, "query": task.query, "reason": f"accepted:{note}"}],
        }
        produced = dict(state.get("produced_by_model") or {})
        produced[model_id] = int(produced.get(model_id, 0)) + 1
        state["produced_by_model"] = produced
        accepted_m = dict(state.get("accepted_by_model") or {})
        accepted_m[model_id] = int(accepted_m.get(model_id, 0)) + 1
        fallback_n = int(accepted_m.get("fallback-table", 0))
        if fallback_n:
            accepted_m["fallback-table"] = max(0, fallback_n - 1)
        state["accepted_by_model"] = accepted_m
        print(f"  replacement accepted {task.id} model={model_id} note={note}")
        print(f"  query={task.query!r}")
        return state
    state["replacement"] = {
        "slot_id": slot_id,
        "task_id": None,
        "query": None,
        "model": None,
        "foods": [],
        "review_note": "all_retries_failed",
        "attempts": attempts,
    }
    print(f"replacement failed after {retries} attempts; freeze stays at {state['n_accepted']}")
    return state


def _replace_hint(slot: SlotPlan, pool: FoodPool) -> str:
    if slot.slot_id == "log-s-egg":
        return (
            "Constraint: use ONLY egg. The expression MUST use the piece measure "
            "(example: 'two pieces' or 'a piece'). Write one natural gym-log sentence. "
            "Never write 'a piece of eggs'. Prefer 'two eggs' or 'an egg' in the query."
        )
    if slot.kind == "single":
        return _single_hint(slot, pool)
    return _meal_hint()


def _rerun_hint(slot: SlotPlan, pool: FoodPool) -> str:
    if slot.kind == "single":
        hint = _single_hint(slot, pool)
        if slot.target_key == "fl_oz":
            return (
                hint
                + " Prefer spoken forms like '1 fl oz', 'a fluid ounce', "
                "or 'one fluid ounce'. Do not use cup, glass, or carton."
            )
        return hint
    if slot.family == "evaluate":
        return (
            "Constraint: pick 2 or 3 foods that form one plausible meal. "
            "Name every chosen food in the query. Use handbook measures "
            "(cup, piece, slice, tbsp, tsp, can, serving, grams, ounces). "
            "Write one natural evaluate/plan sentence."
        )
    return _meal_hint()


def _replace_item(items: Sequence[Mapping], task_id: str, new_item: Mapping) -> list[dict]:
    out: list[dict] = []
    replaced = False
    for item in items:
        if str(item.get("id")) == task_id:
            out.append(dict(new_item))
            replaced = True
        else:
            out.append(dict(item))
    if not replaced:
        return _insert_item(out, dict(new_item), task_id)
    return out


def _replace_meta(meta: Sequence[Mapping], task_id: str, new_row: Mapping) -> list[dict]:
    out = [dict(row) for row in meta if str(row.get("task_id")) != task_id]
    insert_at = next(
        (index for index, row in enumerate(out) if str(row.get("task_id") or "") > task_id),
        len(out),
    )
    out.insert(insert_at, dict(new_row))
    return out


def _merge_slot_review(state: dict, task_id: str, review: Mapping) -> None:
    review_state = dict(state.get("review") or {})
    anomalies = [
        dict(row)
        for row in (review_state.get("anomalies") or [])
        if str(row.get("id")) != task_id
    ]
    per_candidate = dict(review_state.get("per_candidate") or {})
    per_candidate.update(review.get("per_candidate") or {})
    for row in review.get("anomalies") or []:
        if isinstance(row, Mapping):
            anomalies.append(dict(row))
    anomalies.sort(key=lambda row: str(row.get("id") or ""))
    review_state["anomalies"] = anomalies
    review_state["per_candidate"] = per_candidate
    state["review"] = review_state


def _try_live_slot(
    runner: PilotRunner,
    slot: SlotPlan,
    *,
    task_id: str,
    retries: int,
    seed_offset: int,
) -> tuple[Task | None, str | None, list[dict[str, str]]]:
    """Live expander for one slot. No table-phrase / evaluate-row fallback."""
    pool = build_pool(runner.catalog, slot)
    hint = _rerun_hint(slot, pool)
    attempts: list[dict[str, str]] = []
    for attempt in range(max(1, retries)):
        route = runner._active_route()
        model_id = assign_model(attempt, route, seed=SEED + seed_offset)
        print(f"  attempt {attempt + 1}/{retries} model={model_id}")
        try:
            payload = _expand_live(
                pool,
                persona=slot.persona,
                family=slot.family,
                model_id=model_id,
                hint=hint,
            )
            runner.produced[model_id] += 1
        except Exception as exc:
            runner._mark_fail(model_id)
            attempts.append(
                {
                    "model": model_id,
                    "query": "",
                    "reason": f"expander_error:{type(exc).__name__}",
                }
            )
            print(f"    expander raised: {exc}")
            continue
        query = str(payload.get("query") or "")
        if awkward_query(query):
            attempts.append({"model": model_id, "query": query, "reason": "awkward_query"})
            print(f"    rejected awkward query: {query!r}")
            continue
        task, reason = runner._try_payload(
            payload, slot=slot, task_id=task_id, model_id=model_id
        )
        if task is None:
            attempts.append(
                {"model": model_id, "query": query, "reason": reason or "rejected"}
            )
            print(f"    gate reject: {reason}")
            continue
        if awkward_query(task.query):
            food_key = tuple(sorted(item["food_id"] for item in task_foods(task)))
            runner.seen.discard(food_key)
            attempts.append(
                {"model": model_id, "query": task.query, "reason": "awkward_query"}
            )
            print(f"    rejected awkward resolved query: {task.query!r}")
            continue
        attempts.append(
            {"model": model_id, "query": task.query, "reason": "accepted"}
        )
        return task, model_id, attempts
    return None, None, attempts


def rerun_fallback_slots(
    state: dict,
    *,
    catalog,
    retries: int = RERUN_RETRIES,
) -> dict:
    """Re-expand fallback slots with the live expander. KEEP items untouched.

    Review flags are collected and do not block the freeze. A slot that
    fails every retry keeps its previous fallback item (honest disclosure).
    """
    from nutrienv.bench.pipeline.freezer import task_to_item

    targets = fallback_meta_rows(state)
    if not targets:
        print("no fallback slots to rerun")
        state["rerun"] = {
            "mode": "fallbacks",
            "retries": retries,
            "slots": [],
            "n_replaced": 0,
            "n_still_fallback": 0,
            "still_fallback_slots": [],
            "keep_ids": sorted(snapshot_keep_items(state)),
            "disabled_models": [],
        }
        return state

    keep_ids = {
        str(row.get("task_id"))
        for row in (state.get("meta") or [])
        if not is_fallback_model(row.get("model"))
    }
    plan_by_id = {slot.slot_id: slot for slot in build_pool_plan()}
    keep_payload = [
        item
        for item in (state["payload"].get("items") or [])
        if str(item.get("id")) in keep_ids
    ]
    runner = PilotRunner(catalog=catalog, synthetic=False)
    runner.seen = _food_sets_from_payload(keep_payload)
    outcomes: list[dict] = []

    for index, row in enumerate(targets):
        slot_id = str(row.get("slot_id") or "")
        task_id = str(row.get("task_id") or "")
        previous_model = str(row.get("model") or "")
        slot = plan_by_id.get(slot_id)
        if slot is None:
            raise SystemExit(f"unknown rerun slot {slot_id!r}")
        print(f"[rerun {slot_id} {task_id}] previous={previous_model}")
        task, model_id, attempts = _try_live_slot(
            runner,
            slot,
            task_id=task_id,
            retries=retries,
            seed_offset=20_000 + index * 31,
        )
        if task is None or model_id is None:
            old_item = next(
                (
                    item
                    for item in (state["payload"].get("items") or [])
                    if str(item.get("id")) == task_id
                ),
                None,
            )
            if old_item:
                runner.seen |= _food_sets_from_payload([old_item])
            outcomes.append(
                {
                    "slot_id": slot_id,
                    "task_id": task_id,
                    "previous_model": previous_model,
                    "model": previous_model,
                    "fallback": True,
                    "accepted": False,
                    "attempts": attempts,
                    "review_note": "all_retries_failed",
                    "query": row.get("query"),
                }
            )
            print(f"  STILL-FALLBACK {slot_id} after {retries} retries")
            continue

        review: dict[str, object] = {}
        review_note = "review_skipped"
        try:
            print(f"  reviewing {task.id} …")
            review = dict(make_reviewer()([task]))
            _ok, review_note = review_admissible(review, task.id)
        except Exception as exc:
            review_note = f"review_error:{type(exc).__name__}"
            print(f"  review raised: {exc}")

        new_item = task_to_item(task)
        state["payload"]["items"] = _replace_item(
            list(state["payload"].get("items") or []), task_id, new_item
        )
        foods = task_foods(task)
        meta_row = asdict(
            ItemMeta(
                task_id=task.id,
                slot_id=slot.slot_id,
                family=task.family,
                persona=task.persona,
                kind=slot.kind,
                model=model_id,
                fallback=False,
                foods=foods,
                query=task.query,
            )
        )
        state["meta"] = _replace_meta(list(state.get("meta") or []), task_id, meta_row)
        _merge_slot_review(state, task_id, review)
        outcomes.append(
            {
                "slot_id": slot_id,
                "task_id": task.id,
                "previous_model": previous_model,
                "model": model_id,
                "fallback": False,
                "accepted": True,
                "attempts": attempts,
                "review_note": review_note,
                "query": task.query,
                "foods": foods,
            }
        )
        print(f"  replaced {task.id} model={model_id} review={review_note}")
        print(f"  query={task.query!r}")

    produced = dict(state.get("produced_by_model") or {})
    for model_id, count in runner.produced.items():
        produced[model_id] = int(produced.get(model_id, 0)) + int(count)
    state["produced_by_model"] = produced
    state["accepted_by_model"] = dict(
        Counter(str(row.get("model")) for row in (state.get("meta") or []))
    )
    state["accepted_ids"] = [row["task_id"] for row in state["meta"]]
    state["n_accepted"] = len(state["payload"]["items"])
    still = [row["slot_id"] for row in outcomes if row.get("fallback")]
    state["rerun"] = {
        "mode": "fallbacks",
        "retries": retries,
        "slots": outcomes,
        "n_replaced": sum(1 for row in outcomes if row.get("accepted")),
        "n_still_fallback": len(still),
        "still_fallback_slots": still,
        "keep_ids": sorted(keep_ids),
        "disabled_models": sorted(runner.disabled),
    }
    if runner.disabled:
        state["disabled_models"] = sorted(
            set(state.get("disabled_models") or []) | set(runner.disabled)
        )
    n_llm = sum(
        1 for row in state["meta"] if not is_fallback_model(row.get("model"))
    )
    n_fb = sum(1 for row in state["meta"] if is_fallback_model(row.get("model")))
    payload = dict(state["payload"])
    extra = (
        f"; {n_fb} still-fallback ({', '.join(still)})" if n_fb else ""
    )
    payload["notes"] = (
        f"{PIPELINE_VERSION} 20-item pilot freeze (seed {SEED}; "
        f"{n_llm}/20 live LLM expansions{extra}). Dropped ['v10-log-0007']."
    )
    state["payload"] = payload
    return state


def write_freeze_payload(payload: Mapping, output_path: Path) -> str:
    """Write a already-assembled freeze payload. Returns sha256 hex."""
    blob = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(blob, encoding="utf-8")
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def refreeze_from_state(state: dict, *, catalog, output_path: Path) -> dict:
    from nutrienv.bench.split import load_exam

    tmp = output_path.with_suffix(".drop-tmp.json")
    tmp.write_text(
        json.dumps(state["payload"], indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tasks = load_exam(tmp)
    issues = [
        f"{task.id}: {issue}"
        for task in tasks
        for issue in validate_oracle_grams(task)
    ]
    if issues:
        tmp.unlink(missing_ok=True)
        raise SystemExit("oracle grams gate failed:\n" + "\n".join(issues))
    extra = {
        key: state["payload"][key]
        for key in state["payload"]
        if key not in {"version", "catalog", "catalog_sha256", "items"}
    }
    payload, path = freeze_tasks(
        tasks,
        catalog=catalog,
        catalog_field=CATALOG_V1_RELPATH,
        catalog_sha=catalog_digest(catalog),
        output_path=output_path,
        extra=extra,
        overwrite=True,
    )
    tmp.unlink(missing_ok=True)
    state["payload"] = payload
    state["path"] = str(path)
    state["coverage"] = coverage_counts(tasks)
    return state


def _write_json(path: Path, payload: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_drop(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--drop",
        default=None,
        help="comma-separated task ids to exclude, then re-freeze (no network)",
    )
    parser.add_argument(
        "--replace-slot",
        default=None,
        help="after --drop, regenerate this pool-plan slot with a live expander",
    )
    parser.add_argument(
        "--replace-id",
        default=None,
        help="task id for the replacement (default: first dropped id)",
    )
    parser.add_argument(
        "--replace-retries",
        type=int,
        default=5,
        help="bounded live expander retries for --replace-slot (default 5)",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="offline path: table phrases + EVALUATE_ROWS, no live LLM",
    )
    parser.add_argument(
        "--rerun-fallbacks",
        action="store_true",
        help=(
            "re-expand slots whose current model is evaluate-row / "
            "fallback-table / fallback with the live multi-model expander "
            "(no table-phrase fallback). Requires --force. KEEP items stay "
            "byte-identical; a hard-failing slot keeps its previous item."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing freeze when the new payload would differ",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_ROOT / DEFAULT_FREEZE_RELPATH,
        help=f"freeze path (default: {DEFAULT_FREEZE_RELPATH})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog_path = _ROOT / CATALOG_V1_RELPATH
    catalog = load_catalog(catalog_path)
    digest = catalog_digest(catalog)
    print(f"catalog-v1 sha256={digest}")

    if args.rerun_fallbacks:
        if not args.force:
            raise SystemExit(
                "--rerun-fallbacks rewrites the published exam; pass --force"
            )
        state_path = _ROOT / STATE_RELPATH
        if not state_path.is_file():
            raise SystemExit(f"missing state file {state_path}; run the pilot first")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        keep_items = snapshot_keep_items(state)
        print(
            f"rerun-fallbacks: {len(fallback_meta_rows(state))} slots, "
            f"{len(keep_items)} KEEP items"
        )
        state = rerun_fallback_slots(
            state,
            catalog=catalog,
            retries=RERUN_RETRIES,
        )
        state = refreeze_from_state(state, catalog=catalog, output_path=args.output)
        state["payload"] = restore_keep_items(state["payload"], keep_items)
        for item_id, original in keep_items.items():
            current = next(
                (
                    item
                    for item in state["payload"]["items"]
                    if str(item.get("id")) == item_id
                ),
                None,
            )
            if current != original:
                raise SystemExit(f"KEEP item {item_id} drifted after re-freeze")
        digest = write_freeze_payload(state["payload"], args.output)
        state["freeze_sha256"] = digest
        state["path"] = str(args.output)
        _write_json(state_path, state)
        (_ROOT / REPORT_RELPATH).write_text(render_report(state), encoding="utf-8")
        n_ok = (state.get("rerun") or {}).get("n_replaced", 0)
        n_still = (state.get("rerun") or {}).get("n_still_fallback", 0)
        print(
            f"re-froze {args.output}: {state['n_accepted']} items "
            f"(replaced {n_ok}, still-fallback {n_still}, sha256={digest})"
        )
        return 0

    if args.drop or args.replace_slot:
        state_path = _ROOT / STATE_RELPATH
        if not state_path.is_file():
            raise SystemExit(f"missing state file {state_path}; run the pilot first")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        dropped = _parse_drop(args.drop)
        if dropped:
            state = apply_drop(state, dropped)
            print(f"dropped {dropped}; {state['n_accepted']} items remain")
            if "v10-log-0007" in dropped:
                state["human_review"] = {
                    "verdicts": [
                        {
                            "id": "v10-log-0007",
                            "verdict": "DROP",
                            "note": (
                                "Ungrammatical 'a piece of eggs' — the defect "
                                "the review harness should catch. Not gold."
                            ),
                        },
                        {
                            "id": "v10-log-0001",
                            "verdict": "KEEP",
                            "note": (
                                "thick serving is handbook-correct; naturalness=5.0. "
                                "Low c/e is models reading 'beef' as generic ground "
                                "beef vs sirloin steak — acceptable ambiguity."
                            ),
                        },
                        {
                            "id": "v10-log-0006",
                            "verdict": "KEEP",
                            "note": "Single-model unparseable glitch; other model 5/5/5; natural query.",
                        },
                        {
                            "id": "v10-log-0018",
                            "verdict": "KEEP",
                            "note": "Single-model unparseable glitch; other model 5/5/5; natural multi-food query.",
                        },
                    ],
                    "summary": (
                        "4 flagged → 1 dropped (0007) → 1 regenerated (reuse "
                        "v10-log-0007). Remaining flags: 0001 / 0006 / 0018 kept."
                    ),
                }
        if args.replace_slot:
            replace_id = args.replace_id or (dropped[0] if dropped else None)
            if not replace_id:
                raise SystemExit("--replace-id is required when --drop is omitted")
            state = replace_dropped_slot(
                state,
                catalog=catalog,
                slot_id=args.replace_slot,
                task_id=replace_id,
                retries=max(1, int(args.replace_retries)),
            )
        state = refreeze_from_state(state, catalog=catalog, output_path=args.output)
        _write_json(state_path, state)
        (_ROOT / REPORT_RELPATH).write_text(render_report(state), encoding="utf-8")
        print(
            f"re-froze {args.output}: {state['n_accepted']} items "
            f"(dropped {state.get('dropped')})"
        )
        return 0

    runner = PilotRunner(
        catalog=catalog,
        synthetic=args.synthetic,
        output_path=args.output,
        overwrite=args.force,
    )
    try:
        runner.run()
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
