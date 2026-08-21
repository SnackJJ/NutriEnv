"""Single-task mill entry: sample a roster world, expand Log as {query, foods}."""

from __future__ import annotations

import copy
import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from nutrienv.bench.realize import Oracle, Task
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, WorldState

from .resolver import spoken_grams_from_query
from .roster import RosterPerson, profile_for, sample_roster_person
from .sampler import sample_pools
from .types import (
    DEFAULT_GENERATE_POOL_SIZE,
    Expander,
    FoodPool,
    Rejected,
)

__all__ = [
    "AMOUNT_PATHS",
    "GenerateOneResult",
    "build_log_system_prompt",
    "generate_one",
    "parse_query_foods_payload",
]

AMOUNT_PATHS: tuple[str, ...] = ("explicit_grams", "named_measure", "unspecified")

_OCCASIONS: tuple[str, ...] = ("breakfast", "lunch", "dinner")


@dataclass(frozen=True)
class GenerateOneResult:
    accepted: Task | None
    rejected: Rejected | None


def generate_one(
    *,
    catalog: Mapping,
    expander: Expander,
    family: str = "log",
    seed: int = 0,
    person: RosterPerson | None = None,
    amount_path: str | None = None,
    occasion: str = "lunch",
    pool_size: int = DEFAULT_GENERATE_POOL_SIZE,
) -> GenerateOneResult:
    """One Log item: roster person → world windows → pool → expander → speech bind."""
    if family != "log":
        raise ValueError("generate_one implements log in this ticket")
    if amount_path is not None and amount_path not in AMOUNT_PATHS:
        raise ValueError(f"unknown amount_path {amount_path!r}")
    if occasion not in _OCCASIONS:
        raise ValueError(f"unknown occasion {occasion!r}")

    rng = random.Random(seed)
    chosen = person if person is not None else sample_roster_person(seed)
    path = amount_path if amount_path is not None else rng.choice(list(AMOUNT_PATHS))
    profile = profile_for(chosen)
    pools = sample_pools(
        catalog,
        seed=seed,
        family="log",
        n_pools=1,
        pool_size=pool_size,
    )
    if not pools:
        return GenerateOneResult(
            accepted=None, rejected=Rejected("", "empty_pool", "log")
        )
    pool = pools[0]
    raw = expander(pool, persona=chosen.persona, family="log")
    payload = parse_query_foods_payload(raw)
    if payload is None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected("", "schema", "log")
        )
    query = str(payload["query"])
    foods = list(payload["foods"])
    bound, reason = _bind_log_foods(query, foods, pool, catalog, occasion)
    if reason is not None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, reason, "log")
        )
    s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
    oracle = Oracle(
        profile=copy.deepcopy(profile),
        ledger_tail=bound,
        ledger=tuple(bound),
    )
    task = Task(
        f"one-log-{seed:04d}",
        "log",
        query,
        s0,
        oracle,
        ("multi_item_log",),
        chosen.persona,
    )
    return GenerateOneResult(accepted=task, rejected=None)


def parse_query_foods_payload(payload: object) -> dict[str, object] | None:
    """Accept {query, foods: [pool id, …]}. Grams and items/expression are not a schema."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, Mapping):
        return None
    if "grams" in payload:
        return None
    query = payload.get("query")
    foods_raw = payload.get("foods")
    if not isinstance(query, str) or not query.strip():
        return None
    if not isinstance(foods_raw, Sequence) or isinstance(foods_raw, (str, bytes)):
        return None
    foods: list[str] = []
    for item in foods_raw:
        if isinstance(item, Mapping):
            return None
        if not isinstance(item, str) or not item.strip():
            return None
        foods.append(item.strip())
    if not foods:
        return None
    return {"query": query.strip(), "foods": foods}


def build_log_system_prompt(*, amount_path: str, persona: str = "everyday") -> str:
    """Amount-path instructions for the Log expander. Unspecified does not teach serving-of."""
    if amount_path not in AMOUNT_PATHS:
        raise ValueError(f"unknown amount_path {amount_path!r}")
    lines = [
        "Compose one plausible meal from the food pool and write one user query.",
        "Return exactly one JSON object and nothing else:",
        '{"query":"<one sentence>","foods":["<pool food_id>", ...]}',
        "foods are pool ids. Do not put grams in the JSON.",
        "The query names each chosen food in natural speech.",
        "Do not leak window numbers or food_id slugs in the query.",
    ]
    if amount_path == "explicit_grams":
        lines.append(
            'Amount path is explicit grams: you may write household grams such as "150 g".'
        )
    elif amount_path == "named_measure":
        lines.append(
            "Amount path is named measures: cup, tbsp, tsp, slice, piece, can, fl_oz."
        )
        lines.append("Solid cup is allowed. Do not hide cup.")
    else:
        lines.append(
            "Amount path is unspecified quantity: bind will use FNDDS QNS "
            "(bowl / plate / order), never cup."
        )
        lines.append("Do not use serving-of wording.")
    lines.append(f"Persona flavor: {persona}.")
    return "\n".join(lines)


def _bind_log_foods(
    query: str,
    foods: Sequence[str],
    pool: FoodPool,
    catalog: Mapping,
    occasion: str,
) -> tuple[list[LedgerRow] | None, str | None]:
    pool_ids = {food.food_id for food in pool.foods}
    eaten_at = f"today-{occasion}"
    rows: list[LedgerRow] = []
    for food_id in foods:
        if food_id not in pool_ids or food_id not in catalog:
            return None, "not_in_pool"
        grams = spoken_grams_from_query(query, food_id, catalog)
        if grams is None:
            grams = resolve_portion(food_id, query, catalog)
        if grams is None:
            return None, "unresolvable"
        rows.append(LedgerRow(food_id, float(grams), eaten_at))
    if not rows:
        return None, "unresolvable"
    return rows, None
