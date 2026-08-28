"""Evaluate code-chosen plate authoring: search_fit_plate + generate_one items."""

from __future__ import annotations

from pathlib import Path

import pytest

from nutrienv.bench.pipeline.generate_one import generate_one, search_fit_plate
from nutrienv.bench.pipeline.roster import profile_for, sample_roster_person
from nutrienv.bench.pipeline.sampler import sample_pools
from nutrienv.world.catalog_store import load_catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "fdc" / "catalog-v2.sqlite"

pytestmark = pytest.mark.skipif(
    not CATALOG.is_file(), reason="catalog-v2 is not present"
)


def _catalog():
    return load_catalog(CATALOG)


def _rewriter(catalog):
    def rewriter(items, *, intent, occasion, amount_path=None):
        spoken = []
        for item in items:
            fid = str(item["food_id"])
            entry = catalog.get(fid) or {}
            name = (entry.get("aliases") or [str(entry.get("name") or fid).split(",", 1)[0]])[0]
            spoken.append(str(name))
        query = f"Evaluate this as my plan for {occasion}: " + ", ".join(spoken) + "."
        return {"query": query, "foods": [str(item["food_id"]) for item in items]}

    return rewriter


def test_search_fit_plate_returns_a_fit_plate_for_each_seed() -> None:
    catalog = _catalog()
    for seed in range(6):
        person = sample_roster_person(seed)
        profile = profile_for(person)
        pools = sample_pools(
            catalog, seed=seed, family="evaluate", n_pools=1, pool_size=12,
            spoken_only=True,
        )
        plate = search_fit_plate(
            pools[0], profile=profile, catalog=catalog, occasion="lunch"
        )
        assert plate is not None
        assert all(item["grams"] > 0 for item in plate)


def test_generate_one_items_fit_evaluate_accepts() -> None:
    catalog = _catalog()
    seed = 0
    person = sample_roster_person(seed)
    profile = profile_for(person)
    pools = sample_pools(
        catalog, seed=seed, family="evaluate", n_pools=1, pool_size=12,
        spoken_only=True,
    )
    plate = search_fit_plate(
        pools[0], profile=profile, catalog=catalog, occasion="lunch"
    )
    result = generate_one(
        catalog=catalog,
        family="evaluate",
        seed=seed,
        person=person,
        occasion="lunch",
        pool_size=12,
        items=plate,
        rewriter=_rewriter(catalog),
        tier="single",
    )
    assert result.accepted is not None, result.rejected
    assert result.accepted.oracle.last_verdict == "accept"
    assert result.accepted.oracle.last_plan == plate


def test_generate_one_items_over_slot_mints_unfit_evaluate() -> None:
    catalog = _catalog()
    seed = 0
    person = sample_roster_person(seed)
    pools = sample_pools(
        catalog, seed=seed, family="evaluate", n_pools=1, pool_size=12,
        spoken_only=True,
    )
    plate = search_fit_plate(
        pools[0], profile=profile_for(person), catalog=catalog, occasion="lunch"
    )
    result = generate_one(
        catalog=catalog,
        family="evaluate",
        seed=seed,
        person=person,
        occasion="lunch",
        pool_size=12,
        items=plate,
        rewriter=_rewriter(catalog),
        knife="over_slot",
        tier="single",
    )
    assert result.accepted is not None, result.rejected
    assert result.accepted.oracle.last_verdict == "reject"
    assert result.accepted.oracle.last_plan == []
    assert result.accepted.oracle.last_reasons


def test_generate_one_items_are_evaluate_only() -> None:
    catalog = _catalog()
    with pytest.raises(ValueError, match="evaluate-only"):
        generate_one(
            catalog=catalog,
            family="log",
            seed=0,
            items=[{"food_id": "2708539", "grams": 120.0}],
        )


def test_generate_one_items_rejects_unknown_food() -> None:
    catalog = _catalog()
    result = generate_one(
        catalog=catalog,
        family="evaluate",
        seed=0,
        items=[{"food_id": "not-a-food", "grams": 100.0}],
        rewriter=_rewriter(catalog),
        tier="single",
    )
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "bad_items"
