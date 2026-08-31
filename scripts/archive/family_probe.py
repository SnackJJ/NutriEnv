#!/usr/bin/env python3
"""Offline verification: run one item per ADR 0017 family through generate_one.

No network. The probe proves every family's code path runs and produces either
a Task or a typed rejection -- the mill contract, not a fixed pass ratio.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nutrienv.bench.pipeline.generate_one import generate_one  # noqa: E402
from nutrienv.world.catalog_store import load_catalog  # noqa: E402


def _tracer(pool, *, persona, family, amount_path=None):
    path = amount_path or "named_measure"
    for food in pool.foods:
        phrase = None
        if path == "explicit_grams":
            for alt in food.alternatives:
                if alt.quantity == 1.0 and alt.key != "qns":
                    phrase = f"{alt.grams:g} g"
                    break
        elif path == "unspecified":
            for alt in food.alternatives:
                if alt.key == "qns" and alt.quantity == 1.0:
                    phrase = "a bowl"
                    break
        else:
            for alt in food.alternatives:
                if alt.quantity == 1.0 and alt.key != "qns":
                    phrase = alt.phrase
                    break
        if phrase is None:
            continue
        spoken = food.aliases[0] if food.aliases else food.name.split(",", 1)[0].strip()
        query = f"Please log {phrase} of {spoken} for lunch."
        if family == "evaluate":
            query = f"Evaluate this as my plan for lunch: {phrase} of {spoken}."
        elif family == "composite":
            query = (
                f"I had {phrase} of {spoken} for lunch. "
                "What should I eat for dinner?"
            )
        return {"query": query, "foods": [food.food_id]}
    return {"query": "", "foods": []}


def _run_family(catalog, family, seed, amount_path="named_measure"):
    kwargs = dict(
        catalog=catalog,
        family=family,
        seed=seed,
        amount_path=amount_path,
        occasion="lunch",
        pool_size=12,
    )
    if family in {"log", "evaluate", "composite"}:
        kwargs["expander"] = _tracer
    if family == "composite":
        kwargs["steps"] = ("log", "recommend")
    if family in {"recommend", "update"}:
        kwargs["shell"] = None
    return generate_one(**kwargs)


def _run_update(catalog, shell, slots, seed):
    return generate_one(
        catalog=catalog,
        family="update",
        seed=seed,
        shell=shell,
        slots=dict(slots or {}),
    )


def main() -> int:
    catalog = load_catalog(Path("data/fdc/catalog-v2.sqlite"))
    for family in ("log", "evaluate", "recommend", "composite"):
        accepted = 0
        total = 0
        for seed in range(12):
            result = _run_family(catalog, family, seed)
            total += 1
            if result.accepted is not None:
                accepted += 1
        print(f"{family}: {accepted}/{total} accepted")
    update_shells = [
        ("upd-add-allergy-short", {"allergen": "milk"}),
        ("upd-weight", {"n": "71"}),
    ]
    for shell, slots in update_shells:
        accepted = 0
        total = 0
        for seed in range(6):
            result = _run_update(catalog, shell, slots, seed)
            total += 1
            if result.accepted is not None:
                accepted += 1
        print(f"update[{shell}]: {accepted}/{total} accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
