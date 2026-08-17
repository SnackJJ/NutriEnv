"""Expander seam: injectable LLM (or a deterministic synthetic fake)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .types import MAX_PER_POOL, Candidate, FoodPool, PoolFood

__all__ = ["coerce_candidates", "synthetic_expander"]


def coerce_candidates(
    raw: object,
    *,
    family: str,
    persona: str,
    pool_id: str,
    limit: int = MAX_PER_POOL,
) -> list[Candidate]:
    """Normalize expander output to at most ``limit`` Candidates. Fail-closed."""
    payloads = _as_payloads(raw)
    out: list[Candidate] = []
    for payload in payloads[:limit]:
        candidate = _one_candidate(payload, family=family, persona=persona, pool_id=pool_id)
        if candidate is not None:
            out.append(candidate)
    return out


def synthetic_expander(
    pool: FoodPool, *, persona: str, family: str
) -> dict[str, object]:
    """Deterministic fake: compose 1–2 pool foods with a table phrase.

    Used by the tracer-bullet freeze. No network, no clock, no RNG.
    """
    chosen: list[tuple[PoolFood, str]] = []
    for food in pool.foods:
        phrase = _preferred_phrase(food)
        if phrase is None:
            continue
        chosen.append((food, phrase))
        if len(chosen) >= 2:
            break
    if not chosen:
        return {"items": [], "query": ""}
    items = [
        {"food": food.food_id, "expression": phrase} for food, phrase in chosen
    ]
    parts = [f"{phrase} of {_spoken_name(food)}" for food, phrase in chosen]
    if len(parts) == 1:
        meal = parts[0]
    else:
        meal = ", and ".join(parts)
    if family == "evaluate":
        query = f"Evaluate this as my plan: {meal}."
    else:
        query = f"Please log {meal} for lunch."
    return {"items": items, "query": query}


def _as_payloads(raw: object) -> list[Mapping]:
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        if "items" in raw and "query" in raw:
            return [raw]
        nested = raw.get("candidates")
        if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
            return [item for item in nested if isinstance(item, Mapping)]
        return []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return [item for item in raw if isinstance(item, Mapping)]
    return []


def _one_candidate(
    payload: Mapping, *, family: str, persona: str, pool_id: str
) -> Candidate | None:
    query = payload.get("query")
    items_raw = payload.get("items")
    if not isinstance(query, str) or not query.strip():
        return None
    if not isinstance(items_raw, Sequence) or isinstance(items_raw, (str, bytes)):
        return None
    items: list[tuple[str, str]] = []
    for item in items_raw:
        if not isinstance(item, Mapping):
            return None
        food = item.get("food")
        expression = item.get("expression")
        if not isinstance(food, str) or not food.strip():
            return None
        if not isinstance(expression, str) or not expression.strip():
            return None
        items.append((food.strip(), expression.strip()))
    if not items:
        return None
    return Candidate(
        items=tuple(items),
        query=query.strip(),
        family=family,
        persona=persona,
        pool_id=pool_id,
    )


def _preferred_phrase(food: PoolFood) -> str | None:
    for alt in food.alternatives:
        if alt.quantity == 1.0:
            return alt.phrase
    if food.alternatives:
        return food.alternatives[0].phrase
    return None


def _spoken_name(food: PoolFood) -> str:
    for alias in food.aliases:
        cleaned = alias.strip()
        if len(cleaned) >= 3 and "_" not in cleaned:
            return cleaned
    head = food.name.split(",", 1)[0].strip()
    if head:
        return head
    return food.food_id.replace("_", " ")
