"""Every ADR 0017 family runs through generate_one and yields Task or Rejected.

This is the offline family-coverage lock that scripts/family_probe.py doubles
as a CLI probe on catalog-v2. Small fixture catalog keeps it fast.
"""

from __future__ import annotations

import pytest

from nutrienv.bench.pipeline.generate_one import generate_one
from nutrienv.bench.pipeline.roster import ROSTER


def _food(name, portions, aliases=(), allergen_tags=(), nutrients=None):
    return {
        "name": name,
        "portions": dict(portions),
        "aliases": list(aliases),
        "allergen_tags": list(allergen_tags),
        "nutrients": dict(
            nutrients
            or {
                "kcal": 100.0,
                "protein_g": 5.0,
                "carb_g": 10.0,
                "fat_g": 3.0,
                "fiber_g": 2.0,
                "sodium_mg": 40.0,
            }
        ),
    }


def _catalog() -> dict:
    return {
        "oats": _food("Oats, rolled", {"cup": 81.0, "qns": 81.0}, ("oats", "oatmeal")),
        "milk_whole": _food(
            "Milk, whole", {"cup": 244.0, "qns": 244.0}, ("milk",), ("milk",)
        ),
        "shrimp": _food(
            "Shrimp, cooked", {"piece": 25.0, "qns": 100.0}, ("shrimp",), ("shellfish",)
        ),
    }


def _tracer(pool, *, persona, family, amount_path=None):
    for food in pool.foods:
        phrase = None
        for alt in food.alternatives:
            if alt.quantity == 1.0 and alt.key != "qns":
                phrase = alt.phrase
                break
        if phrase is None:
            continue
        spoken = food.aliases[0] if food.aliases else food.name.split(",", 1)[0].strip()
        if family == "composite":
            query = f"I had {phrase} of {spoken} for lunch. What should I eat for dinner?"
        elif family == "evaluate":
            query = f"Evaluate this as my plan for lunch: {phrase} of {spoken}."
        else:
            query = f"Please log {phrase} of {spoken} for lunch."
        return {"query": query, "foods": [food.food_id]}
    return {"query": "", "foods": []}


def _base(family, seed=0, **overrides):
    kwargs = dict(
        catalog=_catalog(),
        family=family,
        seed=seed,
        person=ROSTER[0],
        amount_path="named_measure",
        occasion="lunch",
        pool_size=8,
    )
    kwargs.update(overrides)
    return generate_one(**kwargs)


def test_log_family_runs() -> None:
    result = _base("log", expander=_tracer)
    assert (result.accepted is None) != (result.rejected is None)
    if result.rejected is not None:
        assert result.rejected.reason


def test_evaluate_family_runs() -> None:
    result = _base("evaluate", expander=_tracer, tier="single")
    assert (result.accepted is None) != (result.rejected is None)
    if result.rejected is not None:
        assert result.rejected.reason


def test_recommend_family_runs() -> None:
    result = _base("recommend")
    assert (result.accepted is None) != (result.rejected is None)


def test_update_family_runs() -> None:
    result = _base(
        "update",
        shell="upd-add-allergy-short",
        slots={"allergen": "milk"},
    )
    assert (result.accepted is None) != (result.rejected is None)


def test_composite_family_runs() -> None:
    result = _base(
        "composite",
        expander=_tracer,
        steps=("log", "recommend"),
    )
    assert (result.accepted is None) != (result.rejected is None)
