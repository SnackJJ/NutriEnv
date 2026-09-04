"""Build v2.6-gold from frozen v2.5: unique-recovery wording plus two log swaps.

Patches (ADR 0027): unique-recovery wording on 8301/8303/5005, fat-status
dining speech on 9402/9403/9503, prospective tense on Evaluate accepts
1003/1005/1006/1007, and drop adr20-log-8205 / adr20-log-5004 in favor of
adr26-log-1309 / adr26-log-1310. Family quotas stay update 5 / log 14 /
evaluate 39 / recommend 23 / composite 47.

Run: ``uv run python scripts/build_v2_6_gold.py``.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

from nutrienv.bench.pipeline.freezer import task_to_item
from nutrienv.bench.pipeline.roster import ROSTER, profile_for
from nutrienv.bench.realize import Oracle, Task
from nutrienv.bench.split import load_split
from nutrienv.bench.validator import validate_draft
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, WorldState

_ROOT = Path(__file__).resolve().parents[2]
_V25 = _ROOT / "data" / "splits" / "v2.5-gold.json"
_V26 = _ROOT / "data" / "splits" / "v2.6-gold.json"
_NUTRIENV_GOLD = _ROOT / "data" / "splits" / "nutrienv-gold.json"

_FAMILY_QUOTAS = {
    "update": 5,
    "log": 14,
    "evaluate": 39,
    "recommend": 23,
    "composite": 47,
}

_DROP_IDS = frozenset({"adr20-log-8205", "adr20-log-5004"})

_QUERY_PATCHES = {
    "adr24-comp-8301": (
        "I had a serving of tripe for lunch. Also, please update my activity "
        "level to light."
    ),
    "adr24-comp-8303": (
        "I had a serving of cooked fresh carrots for lunch. Update my "
        "activity level to light."
    ),
    "adr20-log-5005": (
        "I had a standard plate of fish with noodles and mixed vegetables "
        "covered in cheese sauce — no broccoli or extra greens, just the "
        "fish and noodles."
    ),
    "adr25-eval-1003": (
        "Can you evaluate this planned lunch: a burrito bowl and a grilled "
        "chicken fillet wrap sandwich?"
    ),
    "adr25-eval-1005": (
        "Can you evaluate this planned lunch: a burrito bowl, a grilled "
        "chicken fillet wrap sandwich, and an apple?"
    ),
    "adr25-eval-1006": (
        "Can you evaluate this planned lunch: a burrito bowl, pasta with "
        "tomato-based sauce, and a banana?"
    ),
    "adr25-eval-1007": (
        "Can you evaluate this planned plate for lunch: a burrito bowl, "
        "grilled salmon fish, and an apple?"
    ),
    "adr24-comp-9402": (
        "For lunch, I had a cup of cooked split peas prepared with added fat. "
        "Please update my weight to 68.5 kg. For an afternoon snack, is a "
        "slice of sweet potato pie compliant with my targets?"
    ),
    "adr24-comp-9403": (
        "For lunch, I had a cup of brown rice with vegetables and gravy made "
        "with no added fat. Please update my weight to 72.0 kg. For an "
        "afternoon snack, is a slice of sweet potato pie compliant with my "
        "targets?"
    ),
    "adr24-comp-9503": (
        "I started regular gym training, so please update my activity level "
        "to moderate. Log lunch as a cup of brown rice with vegetables and "
        "gravy made with no added fat. Is a slice of sweet potato pie okay "
        "for an afternoon snack?"
    ),
}


def _person(user_id: str):
    for person in ROSTER:
        if person.user_id == user_id:
            return person
    raise KeyError(user_id)


def _require_grams(catalog, food_id: str, phrase: str, expected: float) -> float:
    grams = resolve_portion(food_id, phrase, catalog)
    if grams != expected:
        raise SystemExit(
            f"{food_id} {phrase!r} resolved to {grams}, expected {expected}"
        )
    return grams


def _log_item(
    task_id: str,
    user_id: str,
    query: str,
    tail: list[LedgerRow],
    catalog,
) -> dict:
    person = _person(user_id)
    profile = profile_for(person)
    s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
    oracle = Oracle(
        profile=copy.deepcopy(profile),
        ledger_tail=list(tail),
        ledger=tuple(tail),
    )
    task = Task(task_id, "log", query, s0, oracle, (), person.persona)
    issues = [it for it in validate_draft(task) if "update oracle" not in it]
    if issues:
        raise SystemExit(f"{task_id} validate_draft: {issues}")
    item = task_to_item(task)
    item["id"] = task_id
    return item


def _replacement_logs(catalog) -> list[dict]:
    egg_g = _require_grams(catalog, "2707154", "2 pieces", 100.0)
    apple_g = _require_grams(catalog, "2709215", "an apple", 165.0)
    milk_g = _require_grams(catalog, "2705385", "a glass", 244.0)
    banana_g = _require_grams(catalog, "2709224", "a banana", 126.0)
    return [
        _log_item(
            "adr26-log-1309",
            "roster-ben",
            "I had two hard-boiled eggs and an apple for breakfast.",
            [
                LedgerRow("2707154", egg_g, "today-breakfast"),
                LedgerRow("2709215", apple_g, "today-breakfast"),
            ],
            catalog,
        ),
        _log_item(
            "adr26-log-1310",
            "roster-kim",
            "I had a glass of whole milk and a banana for breakfast.",
            [
                LedgerRow("2705385", milk_g, "today-breakfast"),
                LedgerRow("2709224", banana_g, "today-breakfast"),
            ],
            catalog,
        ),
    ]


def _apply_patches(items: list[dict]) -> None:
    by_id = {item["id"]: item for item in items}
    missing = set(_QUERY_PATCHES) - set(by_id)
    if missing:
        raise KeyError(f"v2.5-gold missing ids: {sorted(missing)}")
    for task_id, query in _QUERY_PATCHES.items():
        by_id[task_id]["query"] = query


def main() -> None:
    catalog = load_catalog(_ROOT / "data" / "fdc" / "catalog-v2.sqlite")
    payload = json.loads(_V25.read_text(encoding="utf-8"))
    items = copy.deepcopy(payload["items"])

    found_drop = {item["id"] for item in items if item["id"] in _DROP_IDS}
    if found_drop != _DROP_IDS:
        raise SystemExit(f"v2.5-gold drop-set mismatch: {sorted(found_drop)}")
    items = [item for item in items if item["id"] not in _DROP_IDS]
    _apply_patches(items)
    replacements = _replacement_logs(catalog)
    seen = {item["id"] for item in items}
    for item in replacements:
        if item["id"] in seen:
            raise SystemExit(f"duplicate id {item['id']}")
        items.append(item)
        seen.add(item["id"])

    families = Counter(item["family"] for item in items)
    if dict(families) != _FAMILY_QUOTAS or len(items) != 128:
        raise SystemExit(
            f"family quotas drifted: {dict(families)} n={len(items)}"
        )

    payload["version"] = "v2.6-gold"
    payload["parent"] = "v2.5-gold"
    payload["items"] = items
    _V26.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    published = copy.deepcopy(payload)
    published["version"] = "nutrienv-v1.0-gold"
    _NUTRIENV_GOLD.write_text(
        json.dumps(published, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    loaded = load_split(_V26, catalog=catalog)
    print(f"Successfully compiled {_V26}: {len(loaded)} tasks")
    print(f"Public NutriEnv v1.0 Gold: {_NUTRIENV_GOLD} ({len(loaded)})")
    print("by family:", dict(sorted(families.items())))


if __name__ == "__main__":
    main()
