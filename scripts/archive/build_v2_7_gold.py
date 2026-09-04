"""Build v2.7-gold from v2.6-gold: re-derived quantifiers and anti-cheating hygiene.

Patches:
1. adr20-comp-5050: Re-derive with ground beef patty @ 85.0g (patty key in catalog)
   and recomputed dinner plan_windows via plan_windows_for_meal.
2. adr20-comp-5034: Re-derive with breadfruit piece @ 35.0g (piece key in catalog)
   and recomputed dinner plan_windows via plan_windows_for_meal.
3. adr26-eval-1304: Correct evaluated_plan white rice from 118.0g (qns) to 158.0g (cup)
   matching the literal query "a cup of white rice, cooked".

Run: ``python scripts/build_v2_7_gold.py``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from nutrienv.bench.achievable import check_achievable
from nutrienv.bench.realize import bind_evaluate_reasons
from nutrienv.bench.split import load_split
from nutrienv.bench.validator import validate_draft
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.daily_windows import plan_windows_for_meal
from nutrienv.world.types import LedgerRow, ledger_totals

_ROOT = Path(__file__).resolve().parents[2]
_V26 = _ROOT / "data" / "splits" / "v2.6-gold.json"
_V27 = _ROOT / "data" / "splits" / "v2.7-gold.json"
_NUTRIENV_GOLD = _ROOT / "data" / "splits" / "nutrienv-gold.json"


def main() -> None:
    catalog_path = _ROOT / "data" / "fdc" / "catalog-v2.sqlite"
    catalog = load_catalog(catalog_path)
    catalog_sha = hashlib.sha256(catalog_path.read_bytes()).hexdigest()

    data_v26 = json.loads(_V26.read_text(encoding="utf-8"))
    items = copy.deepcopy(data_v26["items"])
    items_by_id = {it["id"]: it for it in items}

    # 1. Patch adr20-comp-5050
    it_5050 = items_by_id["adr20-comp-5050"]
    it_5050["oracle"]["sub_oracles"][0]["ledger_tail"][0]["grams"] = 85.0
    it_5050["oracle"]["sub_oracles"][1]["ledger"][0]["grams"] = 85.0
    p_5050 = it_5050["s0"]["profile"]["windows"]
    rows_5050 = [
        LedgerRow(
            food_id=r["food_id"],
            grams=r["grams"],
            eaten_at=r["eaten_at"],
        )
        for r in it_5050["oracle"]["sub_oracles"][0]["ledger_tail"]
    ]
    eaten_5050 = ledger_totals(rows_5050, catalog)
    new_w_5050 = plan_windows_for_meal(p_5050, eaten_5050, "dinner", last_meal=False)
    assert new_w_5050 is not None, "5050 dinner windows must be achievable"
    it_5050["oracle"]["sub_oracles"][1]["plan_windows"] = {
        k: list(v) for k, v in new_w_5050.items()
    }

    # 2. Patch adr20-comp-5034
    it_5034 = items_by_id["adr20-comp-5034"]
    # breadfruit is the second item (index 1)
    it_5034["oracle"]["sub_oracles"][0]["ledger_tail"][1]["grams"] = 35.0
    it_5034["oracle"]["sub_oracles"][1]["ledger"][1]["grams"] = 35.0
    p_5034 = it_5034["s0"]["profile"]["windows"]
    rows_5034 = [
        LedgerRow(
            food_id=r["food_id"],
            grams=r["grams"],
            eaten_at=r["eaten_at"],
        )
        for r in it_5034["oracle"]["sub_oracles"][0]["ledger_tail"]
    ]
    eaten_5034 = ledger_totals(rows_5034, catalog)
    new_w_5034 = plan_windows_for_meal(p_5034, eaten_5034, "dinner", last_meal=False)
    assert new_w_5034 is not None, "5034 dinner windows must be achievable"
    it_5034["oracle"]["sub_oracles"][1]["plan_windows"] = {
        k: list(v) for k, v in new_w_5034.items()
    }

    # 3. Patch adr26-eval-1304
    it_1304 = items_by_id["adr26-eval-1304"]
    for item in it_1304["oracle"]["evaluated_plan"]:
        if item["food_id"] == "2708408":
            item["grams"] = 158.0
    windows_1304 = {
        k: tuple(v) for k, v in it_1304["oracle"]["plan_windows"].items()
    }
    reasons_1304 = bind_evaluate_reasons(
        it_1304["oracle"]["evaluated_plan"],
        windows_1304,
        catalog,
        tuple(it_1304["s0"]["profile"].get("allergies", [])),
    )
    it_1304["oracle"]["last_reasons"] = list(reasons_1304)

    # Reassemble final v2.7 payload
    v27_payload = {
        "version": "v2.7-gold",
        "parent": "v2.6-gold",
        "catalog": "data/fdc/catalog-v2.sqlite",
        "catalog_sha256": catalog_sha,
        "items": items,
    }

    _V27.write_text(json.dumps(v27_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(items)} items to {_V27}")

    # Mirror to nutrienv-gold.json for external release
    public_payload = copy.deepcopy(v27_payload)
    public_payload["version"] = "nutrienv-v1.0-gold"
    _NUTRIENV_GOLD.write_text(json.dumps(public_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Mirrored clean split to {_NUTRIENV_GOLD}")

    # Quotas and structure validation
    from collections import Counter
    families = Counter(item["family"] for item in items)
    family_quotas = {"update": 5, "log": 14, "evaluate": 39, "recommend": 23, "composite": 47}
    assert dict(families) == family_quotas, f"Quotas drifted: {families}"
    assert len(items) == 128, f"Expected 128 items, got {len(items)}"

    tasks = load_split(_V27, catalog=catalog)
    print(f"Loaded {len(tasks)} tasks via load_split.")

    unreachable = check_achievable(tasks).unreachable
    assert not unreachable, f"Unreachable tasks: {unreachable}"
    print(f"Achievability passed: 0 unreachable tasks.")
    print("by family:", dict(sorted(families.items())))


if __name__ == "__main__":
    main()
