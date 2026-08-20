"""Materialize a frozen increment from the realization tables.

The exam is never hand-authored. Every new item is derived from a row in
``bench/realizations.py`` plus the live catalog, and its query/oracle pair is
built by the public ``realize(material, query)`` seam, so a frozen file
cannot drift from the table that produced it.

Each increment copies its parent's items unchanged and appends a reviewed
slice. Every published increment stays reproducible from this one file:

    .venv/bin/python scripts/materialize_split.py v0.2
    .venv/bin/python scripts/materialize_split.py v0.3
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

from nutrienv.bench.realize import GOLD_WINDOWS, material_from_row, realize, spoken_query
from nutrienv.bench.realizations import (
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    FUZZY_ROWS,
    LEDGER_GAP_ROWS,
    LEFTOVER_ROWS,
    MULTI_ITEM_LOG_ROWS,
    NEAR_SYNONYM_ROWS,
    RECOMMEND_ROWS,
    UNIT_CONVERT_ROWS,
    UPDATE_ROWS,
)
from nutrienv.bench.split import _item as split_item
from nutrienv.bench.validator import validate_oracle_grams
from nutrienv.world.catalog import canonical_food_id
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import OUNCE_GRAMS, resolve_portion


ROOT = Path(__file__).resolve().parents[1]
SPLITS = ROOT / "data" / "splits"
CATALOG = ROOT / "data" / "fdc" / "catalog.sqlite"

_MASS_IN_QUERY = re.compile(
    r"\b(?P<quantity>\d+(?:\.\d+)?|half|quarter|one|two|three|four)"
    r"\s*(?:an?\s+)?(?P<unit>g|grams?|oz|ounces?)\b",
    re.IGNORECASE,
)
_QUARTER_PORTION_IN_QUERY = re.compile(
    r"\b(?:a\s+)?quarter(?:\s+of\s+a)?\s+"
    r"(?:cups?|tablespoons?|tbsp|teaspoons?|tsp|slices?|pieces?|cans?)\b",
    re.IGNORECASE,
)
_QUERY_QUANTITIES = {
    "half": 0.5,
    "quarter": 0.25,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
}


INCREMENTS = {
    "v0.2": {
        "parent": "v0.1-gold",
        # Chosen for coverage, not count: the update allergens and condition
        # tags are all ones gold does not already carry, and the conflict rows
        # are spread across the table instead of three neighbours off the same
        # arithmetic ramp.
        "leftover": (
            "lo-tuna-lunch", "lo-avocado-rice", "lo-dinner-logged",
            "lo-skip-breakfast", "lo-almond-snack", "lo-peanut-allergy",
            "lo-milk-allergy", "lo-cut-tight", "lo-potato-lunch",
            "lo-pb-breakfast", "lo-beef-pasta", "lo-late-snack-only",
            "lo-three-carb-debt", "lo-gym-protein-in", "lo-shrimp-lunch",
            "lo-cut-breakfast-only",
        ),
        "update": (
            "up-milk", "up-soy-tofu", "up-fish-salmon", "up-tree-nut-almonds",
            "up-kcal-plus-300", "up-protein-plus-30", "up-milk-kcal-200",
            "up-cut-400",
        ),
        "condition": ("co-milk", "co-tofu", "co-eggs", "co-salmon", "co-almonds"),
        "conflict": ("cf-50-70", "cf-70-90", "cf-90-110"),
        "evaluate": (
            "ev-tuna-rice", "ev-yogurt-banana", "ev-chicken-potato", "ev-tofu-rice",
        ),
        "notes": (
            "v0.1-gold 64 KEEP plus the second increment: 16 leftover recommends, "
            "8 profile updates, 5 condition + 3 conflict constrains, and 4 evaluate "
            "transcriptions, all materialized from realizations.py against the live "
            "catalog. Reviewed by validate_draft plus an LLM reviewer; not reviewed "
            "item-by-item by a human. Destination exam is 240 (ADR 0009). Do not "
            "treat this file as the 240."
        ),
    },
    "v0.3": {
        "parent": "v0.2-gold",
        # evaluate completes its 48-slot allocation here. The six cf-55-75
        # .. cf-85-105 rows stay out: they walk one arithmetic ramp and
        # admitting them would be padding, which ADR 0009 forbids.
        "log": ("fz-almond-half", "fz-rice-half"),
        "update": (
            "up-egg", "up-kcal-minus-200", "up-soy-kcal-300", "up-egg-protein-20",
            "up-fish-protein-30", "up-almond-kcal-minus-200", "up-milk-protein-30",
            "up-egg-kcal-300",
        ),
        "condition": ("co-peanuts", "co-soy-milk"),
        "conflict": ("cf-near-200-56", "cf-near-400-111", "cf-near-800-221"),
        # 41 of the 48 available rows, landing evaluate exactly on its 48-item
        # allocation. The 7 held back are a review reserve, the way v0.1 kept a
        # band. ev-long-chicken-rice-broc-oil is held because it repeats
        # ev-gold-plan's exact food set, and a "long" row whose only claim is
        # length adds nothing over an item gold already froze. The beef-pasta
        # rows it displaced duplicate nothing and are admitted instead.
        # ev-pair-oats-oz-banana and ev-syn-oatmeal-banana share a food set but
        # are both kept: their portions differ (56.7 g vs 80 g of oats) and they
        # test different things -- ounce conversion versus synonym resolution --
        # which is the food/portion geometry ADR 0006 asks rows to differ on.
        "evaluate": (
            "ev-single-tofu-g", "ev-single-oats-cup", "ev-single-potato-piece",
            "ev-single-tuna-can", "ev-single-cheddar-slice", "ev-single-pb-tbsp",
            "ev-single-almond-oz",
            "ev-pair-chicken-rice", "ev-pair-banana-pb", "ev-pair-cheddar-apple",
            "ev-pair-tuna-spinach", "ev-pair-potato-broccoli",
            "ev-pair-oats-oz-banana", "ev-pair-avocado-egg", "ev-pair-tofu-spinach",
            "ev-pair-yogurt-apple", "ev-pair-potato-oil", "ev-pair-milk-oats-oz",
            "ev-tri-eggs-oats-banana", "ev-tri-tuna-potato-spin",
            "ev-tri-beef-pasta-spin", "ev-tri-salmon-potato-broc",
            "ev-tri-yogurt-banana-apple", "ev-tri-chicken-spin-rice",
            "ev-tri-shrimp-rice-broc", "ev-tri-pb-banana-oats",
            "ev-tri-cheddar-apple-yogurt", "ev-tri-avocado-eggs-spin",
            "ev-tri-milk-oats-banana",
            "ev-long-beef-pasta-broc-oil", "ev-long-oats-milk-banana-pb",
            "ev-long-salmon-rice-spin-avo", "ev-long-tofu-rice-veg-oil",
            "ev-long-chicken-potato-fixings",
            "ev-fg-salmon", "ev-fg-beef", "ev-eg-beef-rice", "ev-fg-salmon-beef",
            "ev-syn-prawns", "ev-syn-oatmeal-banana", "ev-syn-yogurt-orange",
        ),
        "notes": (
            "v0.2-gold 100 KEEP plus the third increment: evaluate completes its "
            "48-item allocation (ADR 0009) across declared difficulty tiers, plus "
            "2 fuzzy logs, 8 profile updates, 2 condition and 3 near-miss conflict "
            "constrains. The near-miss conflicts are infeasible by only a few kcal "
            "against the catalog's best protein source, so validate_draft rechecks "
            "feasibility live and a catalog rebuild will turn the split test red "
            "rather than fail silently. Reviewed by validate_draft plus an LLM "
            "reviewer; not reviewed item-by-item by a human."
        ),
    },
    "v0.4": {
        "parent": "v0.3-gold",
        # recommend and constrain both land on their ADR 0009 allocation here.
        # 31 of the 34 available recommend rows: the three held back duplicate a
        # tag another admitted row already covers (soy twice, and wheat against
        # gluten, which overlap heavily in this catalog). All nine catalog
        # allergen tags stay covered by the 31.
        "recommend": (
            "rec-bfast-wide", "rec-lunch-milk", "rec-dinner-egg", "rec-lunch-fish",
            "rec-dinner-soy", "rec-snack-treenut", "rec-dinner-gluten",
            "rec-lunch-milk-egg", "rec-dinner-fish-shell",
            "rec-snack-peanut-soy-tn", "rec-dinner-milk-wheat-soy",
            "rec-lunch-tight", "rec-dinner-sodium", "rec-bfast-fiber",
            "rec-lunch-fat", "rec-snack-fiber", "rec-dinner-carb",
            "rec-cut-lunch-tight", "rec-cut-milk", "rec-cut-fiber",
            "rec-gym-peanut", "rec-gym-egg-milk", "rec-gym-sodium",
            "rec-flex-lunch", "rec-flex-fish", "rec-flex-fat", "rec-htn-lunch",
            "rec-htn-milk", "rec-htn-fiber", "rec-bfast-shellfish",
            "rec-dinner-fat-ceil",
        ),
        "condition": (
            "co-cheddar", "co-yogurt", "co-tuna", "co-pasta", "co-bread",
            "co-soy-sauce", "co-crab", "co-cashew-butter", "co-wheat-bran",
            "co-cream-cheese",
        ),
        # The six cf-55-75 .. cf-85-105 ramp rows stay out for the third time:
        # one arithmetic mechanism repeated is padding, which ADR 0009 forbids.
        "conflict": (
            "cf-fib-200-90", "cf-fib-150-80", "cf-fat-400-55", "cf-fat-600-82",
            "cf-fib-carb-40-45", "cf-near-250-70", "cf-near-350-97",
            "cf-near-180-50", "cf-near-fib-250-90", "cf-near-fat-500-67",
        ),
        "notes": (
            "v0.3-gold 156 KEEP plus the fourth increment: 31 recommends and "
            "20 constrains, landing both families on their ADR 0009 allocation. "
            "Recommend rows span persona, meal occasion, all nine catalog allergen "
            "tags and, on 13 of the 40 table rows, a third judged nutrient beyond "
            "kcal and protein -- an axis only one exam item used before. Conflict "
            "rows now differ in mechanism rather than walking one arithmetic ramp. "
            "Every item passes an achievability gate that searches for a fitting "
            "safe plan, so an unpassable item fails validation instead of freezing "
            "silently. Reviewed by validate_draft plus an LLM reviewer; not "
            "reviewed item-by-item by a human."
        ),
    },
    "v0.5": {
        "parent": "v0.4-gold",
        # The final increment: log 29 -> 48 and update 22 -> 36 complete the
        # 240. log was 79% fuzzy_portion because its other four situations were
        # each a single hardcoded instance in the generator; they are tables now
        # and this admits from them rather than adding 19 more fuzzy portions.
        "multi_item_log": (
            "mi-lunch-chicken-rice", "mi-bfast-eggs-oats-banana",
            "mi-dinner-tofu-four", "mi-snack-yogurt-almonds",
            "mi-dinner-beef-pasta-spin", "mi-bfast-milk-oats-banana-pb",
        ),
        # Five distinct conversion forms rather than five sizes of the same one:
        # whole ounces, a decimal ounce, a cup multiplier and a cup fraction.
        "unit_convert": (
            "uc-chicken-3oz", "uc-almond-1oz", "uc-salmon-3-5oz",
            "uc-rice-1-5cups", "uc-yogurt-quarter-cup",
        ),
        "near_synonym": (
            "ns-oatmeal", "ns-bean-curd", "ns-spaghetti",
            "ns-steamed-rice", "ns-evoo",
        ),
        "ledger_gap": ("lg-miss-breakfast", "lg-miss-dinner", "lg-miss-lunch-three"),
        # update had only ever added an allergen or moved both ends of one
        # window by the same amount. These are the axes it never touched.
        "update": (
            "up-rm-peanut", "up-rm-shellfish", "up-rm-milk",
            "up-floor-protein-20", "up-floor-protein-30", "up-ceil-kcal-200",
            "up-ceil-kcal-300", "up-floor-kcal-200",
            "up-two-kcal-200-prot-20", "up-two-kcal-300-prot-30",
            "up-add-milk-egg", "up-add-fish-treenut",
            "up-preset-cut-muscle", "up-preset-muscle-cut",
        ),
        "notes": (
            "v0.4-gold 207 KEEP plus the final increment: 19 logs and 14 profile "
            "updates complete the 240-item exam (ADR 0009). The log family was 79 "
            "percent fuzzy_portion because its other four situations each existed "
            "as one hardcoded instance; multi_item_log, unit_convert, near_synonym "
            "and ledger_gap are table-backed now and the family finishes balanced. "
            "The update rows cover axes the family had never exercised: removing an "
            "allergy, moving one bound rather than both, two windows in one "
            "request, several allergens at once, and a plan_preset change -- each "
            "declared by its row and cross-checked against the spoken query in both "
            "directions. Reviewed by validate_draft plus an LLM reviewer; not "
            "reviewed item-by-item by a human."
        ),
    },
}


def _rows(table, wanted):
    index = {row.seed_id: row for row in table}
    missing = [seed_id for seed_id in wanted if seed_id not in index]
    if missing:
        raise SystemExit(f"admitted rows not in table: {missing}")
    return [index[seed_id] for seed_id in wanted]


def _profile_json(profile) -> dict:
    out: dict = {
        "user_id": profile.user_id,
        "allergies": list(profile.allergies),
        "windows": {key: list(bounds) for key, bounds in profile.windows.items()},
    }
    if profile.plan_preset:
        out["plan_preset"] = copy.deepcopy(profile.plan_preset)
    return out


def _window_json(windows: dict) -> dict:
    return {key: list(bounds) for key, bounds in windows.items()}


def log_items(catalog: dict, wanted, tag: str) -> list[dict]:
    items = []
    for row in _rows(FUZZY_ROWS, wanted):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        tail = task.oracle.ledger_tail[0]
        items.append({
            "id": task.id,
            "family": task.family,
            "persona": task.persona,
            "situations": list(task.situations),
            "query": task.query,
            "s0": {
                "profile": _profile_json(task.s0.profile),
                "ledger": [
                    {"food_id": food_id, "grams": grams, "eaten_at": eaten_at}
                    for food_id, grams, eaten_at in material.ledger
                ],
            },
            "oracle": {
                "ledger_tail": [
                    {"food_id": row.food_id, "grams": tail.grams, "eaten_at": row.slot}
                ],
                "profile": "s0",
                "ledger": "s0_plus_tail",
            },
        })
    return items


def leftover_items(catalog: dict, wanted, tag: str) -> list[dict]:
    items = []
    for row in _rows(LEFTOVER_ROWS, wanted):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        items.append({
            "id": task.id,
            "family": task.family,
            "persona": task.persona,
            "situations": list(task.situations),
            "query": task.query,
            "s0": {
                "profile": _profile_json(task.s0.profile),
                # Serialize the table's slugs, matching v0.1's file style; the
                # loader canonicalizes to FDC ids when it reads the split.
                "ledger": [
                    {"food_id": food_id, "grams": grams, "eaten_at": eaten_at}
                    for food_id, grams, eaten_at in row.ledger
                ],
            },
            "oracle": {
                "profile": "s0",
                "last_plan": [],
                "plan_must_be_safe": True,
                "plan_must_fit_windows": True,
                "plan_windows": _window_json(task.oracle.plan_windows),
                "ledger": "s0",
            },
        })
    return items


def update_items(catalog: dict, wanted, tag: str) -> list[dict]:
    items = []
    for row in _rows(UPDATE_ROWS, wanted):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        diff: dict = {}
        if task.oracle.profile.allergies != task.s0.profile.allergies:
            diff["allergies"] = list(task.oracle.profile.allergies)
        moved = {
            key: list(bounds)
            for key, bounds in task.oracle.profile.windows.items()
            if bounds != task.s0.profile.windows.get(key)
        }
        if moved:
            diff["windows"] = moved
        if task.oracle.profile.plan_preset != task.s0.profile.plan_preset:
            diff["plan_preset"] = copy.deepcopy(task.oracle.profile.plan_preset)
        items.append({
            "id": task.id,
            "family": task.family,
            "persona": task.persona,
            "situations": list(task.situations),
            "query": task.query,
            "s0": {"profile": _profile_json(task.s0.profile), "ledger": []},
            "oracle": {"profile": diff, "ledger": "s0"},
        })
    return items


def recommend_items(catalog: dict, wanted, tag: str) -> list[dict]:
    items = []
    for row in _rows(RECOMMEND_ROWS, wanted):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        items.append({
            "id": task.id,
            "family": task.family,
            "persona": task.persona,
            "situations": list(task.situations),
            "query": task.query,
            "s0": {"profile": _profile_json(task.s0.profile), "ledger": []},
            "oracle": {
                "profile": "s0",
                "last_plan": [],
                "plan_must_be_safe": True,
                "plan_must_fit_windows": True,
                "ledger": "s0",
            },
        })
    return items


def _freeze_log(task, material, tail: list[dict]) -> dict:
    return {
        "id": task.id,
        "family": task.family,
        "persona": task.persona,
        "situations": list(task.situations),
        "query": task.query,
        "s0": {
            "profile": {
                "user_id": task.s0.profile.user_id,
                "allergies": list(task.s0.profile.allergies),
                "windows": {key: list(bounds) for key, bounds in GOLD_WINDOWS.items()},
            },
            "ledger": [
                {"food_id": food_id, "grams": grams, "eaten_at": eaten_at}
                for food_id, grams, eaten_at in material.ledger
            ],
        },
        "oracle": {
            "ledger_tail": tail,
            "profile": "s0",
            "ledger": "s0_plus_tail",
        },
    }


def multi_item_items(catalog: dict, wanted, tag: str) -> list[dict]:
    items = []
    for row in _rows(MULTI_ITEM_LOG_ROWS, wanted):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        tail = [
            {"food_id": food_id, "grams": item.grams, "eaten_at": row.slot}
            for (food_id, _phrase), item in zip(row.items, task.oracle.ledger_tail)
        ]
        items.append(_freeze_log(task, material, tail))
    return items


def unit_convert_items(catalog: dict, wanted, tag: str) -> list[dict]:
    items = []
    for row in _rows(UNIT_CONVERT_ROWS, wanted):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        tail = [{
            "food_id": row.food_id,
            "grams": task.oracle.ledger_tail[0].grams,
            "eaten_at": row.slot,
        }]
        items.append(_freeze_log(task, material, tail))
    return items


def near_synonym_items(catalog: dict, wanted, tag: str) -> list[dict]:
    items = []
    for row in _rows(NEAR_SYNONYM_ROWS, wanted):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        tail = [{
            "food_id": row.food_id,
            "grams": task.oracle.ledger_tail[0].grams,
            "eaten_at": row.slot,
        }]
        items.append(_freeze_log(task, material, tail))
    return items


def ledger_gap_items(catalog: dict, wanted, tag: str) -> list[dict]:
    items = []
    for row in _rows(LEDGER_GAP_ROWS, wanted):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        food_id, _phrase, slot = row.missing
        tail = [{
            "food_id": food_id,
            "grams": task.oracle.ledger_tail[0].grams,
            "eaten_at": slot,
        }]
        items.append(_freeze_log(task, material, tail))
    return items


def constrain_items(catalog: dict, conditions, conflicts, tag: str) -> list[dict]:
    items = []
    for row in _rows(CONSTRAIN_ROWS, conditions):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        items.append({
            "id": task.id,
            "family": task.family,
            "persona": task.persona,
            "situations": list(task.situations),
            "query": task.query,
            "s0": {"profile": _profile_json(task.s0.profile), "ledger": []},
            "oracle": {
                "profile": "s0",
                "last_plan": [],
                "plan_must_be_safe": True,
                "plan_must_fit_windows": True,
                "allow_empty_plan": False,
                "ledger": "s0",
            },
        })
    for row in _rows(CONSTRAIN_ROWS, conflicts):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        items.append({
            "id": task.id,
            "family": task.family,
            "persona": task.persona,
            "situations": list(task.situations),
            "query": task.query,
            "s0": {
                "profile": _profile_json(task.s0.profile),
                "ledger": [],
                "last_plan": [
                    {"food_id": food_id, "grams": grams}
                    for food_id, grams in row.last_plan
                ],
            },
            # last_plan omitted on purpose: the loader reads a missing key as
            # None, which is the "plans are not judged" sentinel gold uses.
            "oracle": {
                "profile": "s0",
                "plan_must_fit_windows": True,
                "allow_empty_plan": True,
                "ledger": "s0",
            },
        })
    return items


def evaluate_items(catalog: dict, wanted, tag: str) -> list[dict]:
    items = []
    for row in _rows(EVALUATE_ROWS, wanted):
        material = material_from_row(row, tag=tag, catalog=catalog)
        task = realize(material, spoken_query(row), catalog=catalog)
        grams = {item["food_id"]: item["grams"] for item in task.oracle.last_plan}
        plan = [
            {"food_id": food_id, "grams": grams[canonical_food_id(catalog, food_id)]}
            for food_id, _phrase in row.items
        ]
        items.append({
            "id": task.id,
            "family": task.family,
            "persona": task.persona,
            "situations": list(task.situations),
            "query": task.query,
            "s0": {"profile": _profile_json(task.s0.profile), "ledger": []},
            "oracle": {
                "profile": "s0",
                "last_plan": plan,
                "plan_must_fit_windows": True,
                "ledger": "s0",
            },
        })
    return items


def _query_mass_grams(query: str) -> set[float]:
    """Return gram amounts directly and unambiguously stated in ``query``."""
    values = set()
    for match in _MASS_IN_QUERY.finditer(query):
        raw_quantity = match.group("quantity").lower()
        quantity = _QUERY_QUANTITIES.get(raw_quantity)
        if quantity is None:
            quantity = float(raw_quantity)
        unit = match.group("unit").lower()
        grams = quantity if unit in {"g", "gram", "grams"} else quantity * OUNCE_GRAMS
        values.add(round(grams, 2))
    return values


def _query_anchors_item(task, food_id: str, grams: float) -> bool:
    if round(float(grams), 2) in _query_mass_grams(task.query):
        return True
    for match in _QUARTER_PORTION_IN_QUERY.finditer(task.query):
        resolved = resolve_portion(food_id, match.group(0), task.s0.catalog)
        if resolved is not None and round(float(grams), 2) == round(resolved, 2):
            return True
    return False


def _portion_anchor_task(task):
    """Project away grams already anchored explicitly by the spoken query."""
    ledger_tail = task.oracle.ledger_tail
    if ledger_tail:
        ledger_tail = [
            row
            for row in ledger_tail
            if not _query_anchors_item(task, row.food_id, row.grams)
        ]
    last_plan = task.oracle.last_plan
    if last_plan:
        last_plan = [
            item
            for item in last_plan
            if not _query_anchors_item(
                task, str(item["food_id"]), float(item["grams"])
            )
        ]
    return replace(
        task,
        oracle=replace(
            task.oracle,
            ledger_tail=ledger_tail,
            last_plan=last_plan,
        ),
    )


def freeze_split(payload: dict, target: Path, catalog) -> None:
    """Validate Oracle gram anchors, then write one frozen split payload."""
    issues = []
    for raw_item in payload["items"]:
        task = _portion_anchor_task(split_item(raw_item, catalog))
        issues.extend(
            f"{task.id}: {issue}" for issue in validate_oracle_grams(task)
        )
    if issues:
        raise ValueError("oracle grams gate failed:\n" + "\n".join(issues))
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build(version: str, *, target: Path | None = None) -> Path:
    spec = INCREMENTS[version]
    tag = "v" + version[1:].replace(".", "")      # v0.2 -> v02
    catalog = load_catalog(CATALOG)
    parent_path = SPLITS / f"{spec['parent']}.json"
    parent = json.loads(parent_path.read_text(encoding="utf-8"))

    wanted_eval = spec.get("evaluate", ())

    new = (
        log_items(catalog, spec.get("log", ()), tag)
        + multi_item_items(catalog, spec.get("multi_item_log", ()), tag)
        + unit_convert_items(catalog, spec.get("unit_convert", ()), tag)
        + near_synonym_items(catalog, spec.get("near_synonym", ()), tag)
        + ledger_gap_items(catalog, spec.get("ledger_gap", ()), tag)
        + leftover_items(catalog, spec.get("leftover", ()), tag)
        + recommend_items(catalog, spec.get("recommend", ()), tag)
        + update_items(catalog, spec.get("update", ()), tag)
        + constrain_items(catalog, spec.get("condition", ()), spec.get("conflict", ()), tag)
        + evaluate_items(catalog, wanted_eval, tag)
    )
    payload = {
        "version": f"{version}-gold",
        "catalog": "data/fdc/catalog.sqlite",
        "catalog_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        "parent": spec["parent"],
        "notes": spec["notes"],
        "items": parent["items"] + new,
    }
    dest = target if target is not None else SPLITS / f"{version}-gold.json"
    freeze_split(payload, dest, catalog)
    print(
        f"wrote {dest}: {len(parent['items'])} KEEP + "
        f"{len(new)} new = {len(payload['items'])}"
    )
    return dest


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in INCREMENTS:
        raise SystemExit(f"usage: materialize_split.py {{{'|'.join(INCREMENTS)}}}")
    build(sys.argv[1])
