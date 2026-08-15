"""Materialize a frozen increment from the realization tables.

The exam is never hand-authored. Every new item is derived from a row in
``bench/realizations.py`` plus the live catalog, and its query/oracle pair is
built by the same ``Generator._*_from_row`` helpers the factory uses, so a
frozen file cannot drift from the table that produced it.

Each increment copies its parent's items unchanged and appends a reviewed
slice. Every published increment stays reproducible from this one file:

    .venv/bin/python scripts/materialize_split.py v0.2
    .venv/bin/python scripts/materialize_split.py v0.3
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

from nutrienv.bench.generator import Generator
from nutrienv.bench.realizations import (
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    FUZZY_ROWS,
    LEFTOVER_ROWS,
    RECOMMEND_ROWS,
    UPDATE_ROWS,
)
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.types import LedgerRow, Profile, WorldState

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ROOT / "data" / "splits"
CATALOG = ROOT / "data" / "fdc" / "catalog.sqlite"

GOLD_WINDOWS = {"kcal": (1800.0, 2200.0), "protein_g": (90.0, 140.0)}

# v0.1 curated the S0 of a fuzzy log item as three distractor rows: a
# yesterday row, a row in some other slot today, and a row in the target slot
# under a different food. Reused verbatim so log items stay one shape.
FUZZY_DISTRACTORS = {"apple": 182.0, "orange": 131.0, "oats": 60.0, "banana": 118.0}


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
}


def _rows(table, wanted):
    index = {row.seed_id: row for row in table}
    missing = [seed_id for seed_id in wanted if seed_id not in index]
    if missing:
        raise SystemExit(f"admitted rows not in table: {missing}")
    return [index[seed_id] for seed_id in wanted]


def _state(catalog: dict, user_id: str, allergies: tuple[str, ...]) -> WorldState:
    """A gold-style S0: profile only, empty ledger, no preset."""
    profile = Profile(
        user_id=user_id,
        allergies=allergies,
        windows=dict(GOLD_WINDOWS),
        plan_preset={},
    )
    return WorldState(profile=profile, ledger=[], catalog=catalog, last_plan=[])


def _profile_json(profile: Profile) -> dict:
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
    gen = Generator()
    items = []
    for row in _rows(FUZZY_ROWS, wanted):
        stem = row.seed_id.removeprefix("fz-")
        grams = gen._require_portion(row.food_id, row.phrase, catalog)
        # A distractor in the target slot must not be the food being logged,
        # or the oracle tail would be ambiguous with what S0 already holds.
        same_slot = "banana" if row.food_id == "oats" else "oats"
        other_slot = "today-lunch" if row.slot == "today-breakfast" else "today-breakfast"
        ledger = [
            {"food_id": "apple", "grams": FUZZY_DISTRACTORS["apple"], "eaten_at": "yesterday-snack"},
            {"food_id": "orange", "grams": FUZZY_DISTRACTORS["orange"], "eaten_at": other_slot},
            {"food_id": same_slot, "grams": FUZZY_DISTRACTORS[same_slot], "eaten_at": row.slot},
        ]
        items.append({
            "id": f"{tag}-log-fz-{stem}",
            "family": "log",
            "persona": "everyday",
            "situations": ["fuzzy_portion"],
            "query": row.utterance,
            "s0": {
                "profile": _profile_json(_state(catalog, f"{tag}-fz-{stem}", ("peanut",)).profile),
                "ledger": ledger,
            },
            "oracle": {
                "ledger_tail": [
                    {"food_id": row.food_id, "grams": grams, "eaten_at": row.slot}
                ],
                "profile": "s0",
                "ledger": "s0_plus_tail",
            },
        })
    return items


def leftover_items(catalog: dict, wanted, tag: str) -> list[dict]:
    gen = Generator()
    items = []
    for row in _rows(LEFTOVER_ROWS, wanted):
        stem = row.seed_id.removeprefix("lo-")
        # Leftover S0 carries no baseline allergy: the row is the whole story.
        s0 = _state(catalog, f"{tag}-lo-{stem}", ())
        query, oracle = gen._leftover_from_row(s0, row)
        items.append({
            "id": f"{tag}-rec-lo-{stem}",
            "family": "recommend",
            "persona": "leftover",
            "situations": [],
            "query": query,
            "s0": {
                "profile": _profile_json(s0.profile),
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
                "plan_windows": _window_json(oracle.plan_windows),
                "ledger": "s0",
            },
        })
    return items


def update_items(catalog: dict, wanted, tag: str) -> list[dict]:
    gen = Generator()
    items = []
    for row in _rows(UPDATE_ROWS, wanted):
        stem = row.seed_id.removeprefix("up-")
        s0 = _state(catalog, f"{tag}-upd-{stem}", ("peanut",))
        query, oracle = gen._update_from_row(s0, row)
        diff: dict = {}
        if oracle.profile.allergies != s0.profile.allergies:
            diff["allergies"] = list(oracle.profile.allergies)
        moved = {
            key: list(bounds)
            for key, bounds in oracle.profile.windows.items()
            if bounds != s0.profile.windows.get(key)
        }
        if moved:
            diff["windows"] = moved
        items.append({
            "id": f"{tag}-upd-{stem}",
            "family": "update",
            "persona": "cut" if row.s0_plan_preset else "everyday",
            "situations": [],
            "query": query,
            "s0": {"profile": _profile_json(s0.profile), "ledger": []},
            "oracle": {"profile": diff, "ledger": "s0"},
        })
    return items


def recommend_items(catalog: dict, wanted, tag: str) -> list[dict]:
    gen = Generator()
    items = []
    for row in _rows(RECOMMEND_ROWS, wanted):
        stem = row.seed_id.removeprefix("rec-")
        s0 = _state(catalog, f"{tag}-rec-{stem}", ())
        query, _oracle = gen._recommend_from_row(s0, row)
        items.append({
            "id": f"{tag}-rec-{stem}",
            "family": "recommend",
            "persona": row.persona,
            "situations": [],
            "query": query,
            "s0": {"profile": _profile_json(s0.profile), "ledger": []},
            "oracle": {
                "profile": "s0",
                "last_plan": [],
                "plan_must_be_safe": True,
                "plan_must_fit_windows": True,
                "ledger": "s0",
            },
        })
    return items


def constrain_items(catalog: dict, conditions, conflicts, tag: str) -> list[dict]:
    gen = Generator()
    items = []
    for row in _rows(CONSTRAIN_ROWS, conditions):
        stem = row.seed_id.removeprefix("co-")
        s0 = _state(catalog, f"{tag}-cond-{stem}", ())
        query, _oracle = gen._condition_from_row(s0, row)
        items.append({
            "id": f"{tag}-cond-{stem}",
            "family": "constrain",
            "persona": "everyday",
            "situations": ["condition_suitability"],
            "query": query,
            "s0": {"profile": _profile_json(s0.profile), "ledger": []},
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
        stem = row.seed_id.removeprefix("cf-")
        s0 = _state(catalog, f"{tag}-conf-{stem}", ())
        query, _oracle = gen._conflict_from_row(s0, row)
        items.append({
            "id": f"{tag}-conf-{stem}",
            "family": "constrain",
            "persona": "everyday",
            "situations": ["conflict_windows"],
            "query": query,
            "s0": {
                "profile": _profile_json(s0.profile),
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
    gen = Generator()
    items = []
    for row in _rows(EVALUATE_ROWS, wanted):
        stem = row.seed_id.removeprefix("ev-")
        # Gold evaluate items carry a baseline allergy, but never one that the
        # named meal itself trips: the agent passes by submitting that exact
        # plan, so a collision would make the item unpassable rather than hard.
        carried = set()
        for food_id, _phrase in row.items:
            carried.update(catalog[food_id].get("allergen_tags") or [])
        allergies = tuple(tag_ for tag_ in ("peanut",) if tag_ not in carried)
        s0 = _state(catalog, f"{tag}-eval-{stem}", allergies)
        query, oracle = gen._evaluate_from_row(s0, row)
        grams = {item["food_id"]: item["grams"] for item in oracle.last_plan}
        plan = [
            {"food_id": food_id, "grams": grams[gen._food_id(s0, food_id)]}
            for food_id, _phrase in row.items
        ]
        items.append({
            "id": f"{tag}-eval-{stem}",
            "family": "evaluate",
            "persona": "everyday",
            "situations": [],
            "query": query,
            "s0": {"profile": _profile_json(s0.profile), "ledger": []},
            "oracle": {
                "profile": "s0",
                "last_plan": plan,
                "plan_must_fit_windows": True,
                "ledger": "s0",
            },
        })
    return items


def build(version: str) -> None:
    spec = INCREMENTS[version]
    tag = "v" + version[1:].replace(".", "")      # v0.2 -> v02
    catalog = load_catalog()
    parent_path = SPLITS / f"{spec['parent']}.json"
    parent = json.loads(parent_path.read_text(encoding="utf-8"))

    wanted_eval = spec.get("evaluate", ())

    new = (
        log_items(catalog, spec.get("log", ()), tag)
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
    target = SPLITS / f"{version}-gold.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {target.relative_to(ROOT)}: {len(parent['items'])} KEEP + "
        f"{len(new)} new = {len(payload['items'])}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in INCREMENTS:
        raise SystemExit(f"usage: materialize_split.py {{{'|'.join(INCREMENTS)}}}")
    build(sys.argv[1])
