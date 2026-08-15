"""Materialize data/splits/v0.2-gold.json from the realization tables.

The exam is never hand-authored. Every new item is derived from a row in
``bench/realizations.py`` plus the live catalog, and the query/oracle pair is
built by the same ``Generator._*_from_row`` helpers the factory uses, so the
frozen file cannot drift from the factory that produced it.

v0.1's 64 items are copied byte-for-byte; only the tail is new.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from nutrienv.bench.generator import Generator
from nutrienv.bench.realizations import (
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    LEFTOVER_ROWS,
    UPDATE_ROWS,
)
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.types import Profile, WorldState

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "data" / "splits" / "v0.1-gold.json"
TARGET = ROOT / "data" / "splits" / "v0.2-gold.json"
CATALOG = ROOT / "data" / "fdc" / "catalog.sqlite"

GOLD_WINDOWS = {"kcal": (1800.0, 2200.0), "protein_g": (90.0, 140.0)}

# Which rows this increment admits. Chosen for coverage, not for count:
# the five update allergens and the five condition tags are all tags gold
# does not already carry, and the three conflict rows are the widely spaced
# ones rather than three neighbours off the same arithmetic ramp.
ADMIT_LEFTOVER = (
    "lo-tuna-lunch", "lo-avocado-rice", "lo-dinner-logged", "lo-skip-breakfast",
    "lo-almond-snack", "lo-peanut-allergy", "lo-milk-allergy", "lo-cut-tight",
    "lo-potato-lunch", "lo-pb-breakfast", "lo-beef-pasta", "lo-late-snack-only",
    "lo-three-carb-debt", "lo-gym-protein-in", "lo-shrimp-lunch",
    "lo-cut-breakfast-only",
)
ADMIT_UPDATE = (
    "up-milk", "up-soy-tofu", "up-fish-salmon", "up-tree-nut-almonds",
    "up-kcal-plus-300", "up-protein-plus-30", "up-milk-kcal-200", "up-cut-400",
)
ADMIT_CONDITION = ("co-milk", "co-tofu", "co-eggs", "co-salmon", "co-almonds")
ADMIT_CONFLICT = ("cf-50-70", "cf-70-90", "cf-90-110")
ADMIT_EVALUATE = (
    "ev-tuna-rice", "ev-yogurt-banana", "ev-chicken-potato", "ev-tofu-rice",
)


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


def leftover_items(catalog: dict) -> list[dict]:
    gen = Generator()
    items = []
    for row in _rows(LEFTOVER_ROWS, ADMIT_LEFTOVER):
        stem = row.seed_id.removeprefix("lo-")
        # Leftover S0 carries no baseline allergy: the row is the whole story.
        s0 = _state(catalog, f"v02-lo-{stem}", ())
        query, oracle = gen._leftover_from_row(s0, row)
        items.append({
            "id": f"v02-rec-lo-{stem}",
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


def update_items(catalog: dict) -> list[dict]:
    gen = Generator()
    items = []
    for row in _rows(UPDATE_ROWS, ADMIT_UPDATE):
        stem = row.seed_id.removeprefix("up-")
        s0 = _state(catalog, f"v02-upd-{stem}", ("peanut",))
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
            "id": f"v02-upd-{stem}",
            "family": "update",
            "persona": "cut" if row.s0_plan_preset else "everyday",
            "situations": [],
            "query": query,
            "s0": {"profile": _profile_json(s0.profile), "ledger": []},
            "oracle": {"profile": diff, "ledger": "s0"},
        })
    return items


def constrain_items(catalog: dict) -> list[dict]:
    gen = Generator()
    items = []
    for row in _rows(CONSTRAIN_ROWS, ADMIT_CONDITION):
        stem = row.seed_id.removeprefix("co-")
        s0 = _state(catalog, f"v02-cond-{stem}", ())
        query, _oracle = gen._condition_from_row(s0, row)
        items.append({
            "id": f"v02-cond-{stem}",
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
    for row in _rows(CONSTRAIN_ROWS, ADMIT_CONFLICT):
        stem = row.seed_id.removeprefix("cf-")
        s0 = _state(catalog, f"v02-conf-{stem}", ())
        query, _oracle = gen._conflict_from_row(s0, row)
        items.append({
            "id": f"v02-conf-{stem}",
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


def evaluate_items(catalog: dict) -> list[dict]:
    gen = Generator()
    items = []
    for row in _rows(EVALUATE_ROWS, ADMIT_EVALUATE):
        stem = row.seed_id.removeprefix("ev-")
        s0 = _state(catalog, f"v02-eval-{stem}", ("peanut",))
        query, oracle = gen._evaluate_from_row(s0, row)
        grams = {item["food_id"]: item["grams"] for item in oracle.last_plan}
        plan = [
            {"food_id": food_id, "grams": grams[gen._food_id(s0, food_id)]}
            for food_id, _phrase in row.items
        ]
        items.append({
            "id": f"v02-eval-{stem}",
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


def main() -> None:
    catalog = load_catalog()
    parent = json.loads(PARENT.read_text(encoding="utf-8"))
    new = (
        leftover_items(catalog)
        + update_items(catalog)
        + constrain_items(catalog)
        + evaluate_items(catalog)
    )
    payload = {
        "version": "v0.2-gold",
        "catalog": "data/fdc/catalog.sqlite",
        "catalog_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        "parent": "v0.1-gold",
        "notes": (
            "v0.1-gold 64 KEEP plus the second increment: 16 leftover recommends, "
            "8 profile updates, 5 condition + 3 conflict constrains, and 4 evaluate "
            "transcriptions, all materialized from realizations.py against the live "
            "catalog. Reviewed by validate_draft plus an LLM reviewer; not reviewed "
            "item-by-item by a human. Destination exam is 240 (ADR 0009). Do not "
            "treat this file as the 240."
        ),
        "items": parent["items"] + new,
    }
    TARGET.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}: {len(parent['items'])} KEEP + {len(new)} new = {len(payload['items'])}")


if __name__ == "__main__":
    main()
