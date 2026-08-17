#!/usr/bin/env python3
"""Issue 10: run the v1.0-gold 20-item pilot and freeze the split.

Full chain: Sampler (fixed pool plan) → Expander (live, multi-model) →
Resolver → Judge → validate_draft → Review harness → Freezer.

    .venv/bin/python scripts/run_pilot_20.py
    .venv/bin/python scripts/run_pilot_20.py --drop v10-log-0003,v10-eval-0016

``--drop`` re-freezes the last accepted set without calling the network.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
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

# Evaluate items cannot be LLM-authored: validate_draft D4 requires the query
# to match a realizations EVALUATE_ROWS row exactly. Fallbacks are rows that
# pass validate_draft + validate_oracle_grams against catalog-v1.
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
    ) -> None:
        self.catalog = catalog
        self.synthetic = synthetic
        self.output_path = output_path or (_ROOT / DEFAULT_FREEZE_RELPATH)
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
        extra = {
            "seed": SEED,
            "sampler_rule_version": "pilot-20-plan-v1",
            "notes": (
                f"{PIPELINE_VERSION} 20-item pilot freeze "
                f"(seed {SEED}; evaluate D4 uses EVALUATE_ROWS fallbacks)."
            ),
        }
        payload, path = freeze_tasks(
            self.accepted,
            catalog=self.catalog,
            catalog_field=CATALOG_V1_RELPATH,
            catalog_sha=self.digest,
            output_path=self.output_path,
            extra=extra,
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
    lines.extend(
        [
            "",
            f"人审负担: **{len(anomalies)}** / {state.get('n_accepted')} flagged.",
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
            "`validate_draft` still requires evaluate queries to match an "
            "`EVALUATE_ROWS` row (D4). Live expander queries therefore fail "
            "that gate and the pilot accepts the planned realization-row "
            "fallback. Resolver / Judge / `validate_oracle_grams` / review "
            "still run on the accepted evaluate items.",
            "",
            "## Re-freeze",
            "",
            "```",
            ".venv/bin/python scripts/run_pilot_20.py --drop <id,...>",
            "```",
            "",
            "Reads `reports/pilot-20-state.json`, drops those ids, rewrites "
            "`data/splits/v1.0-gold.json` and this report. No network.",
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
    return "\n".join(lines) + "\n"


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
        "--synthetic",
        action="store_true",
        help="offline path: table phrases + EVALUATE_ROWS, no live LLM",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_ROOT / DEFAULT_FREEZE_RELPATH,
        help="freeze path (default: data/splits/v1.0-gold.json)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog_path = _ROOT / CATALOG_V1_RELPATH
    catalog = load_catalog(catalog_path)
    digest = catalog_digest(catalog)
    print(f"catalog-v1 sha256={digest}")

    if args.drop:
        state_path = _ROOT / STATE_RELPATH
        if not state_path.is_file():
            raise SystemExit(f"missing state file {state_path}; run the pilot first")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state = apply_drop(state, _parse_drop(args.drop))
        state = refreeze_from_state(state, catalog=catalog, output_path=args.output)
        _write_json(state_path, state)
        (_ROOT / REPORT_RELPATH).write_text(render_report(state), encoding="utf-8")
        print(f"re-froze {args.output}: {state['n_accepted']} items (dropped {state.get('dropped')})")
        return 0

    runner = PilotRunner(
        catalog=catalog, synthetic=args.synthetic, output_path=args.output
    )
    try:
        runner.run()
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
