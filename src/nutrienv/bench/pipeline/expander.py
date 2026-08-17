"""Expander seam: injectable LLM (or a deterministic synthetic fake)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence

from nutrienv.io.chat import complete_chat

from .models import (
    DEFAULT_EXPANDER_MODEL,
    assign_model,
    enabled_route,
    parse_model_route,
)
from .types import MAX_PER_POOL, Candidate, FoodPool, PoolFood

__all__ = [
    "HANDBOOK_VOCABULARY",
    "LlmExpander",
    "build_system_prompt",
    "build_user_prompt",
    "coerce_candidates",
    "make_llm_expander",
    "parse_expander_payload",
    "synthetic_expander",
]

# Spoken measures listed in harness/react.py _SYSTEM_V1_TAIL. Discipline 4:
# expander output may only use this vocabulary.
HANDBOOK_VOCABULARY: tuple[str, ...] = (
    "cup",
    "tbsp",
    "tsp",
    "slice",
    "piece",
    "can",
    "fl_oz",
    "serving",
    "portion",
    "bowl",
    "plate",
    "order",
    "thick",
    "thin",
    "regular",
    "a serving of",
    "grams",
    "ounces",
)

Completer = Callable[[str, Sequence[Mapping[str, str]]], str]


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


_PERSONA_FLAVOR = {
    "everyday": (
        "Everyday eater: an ordinary household meal with mixed, believable "
        "portions. Use household measures only."
    ),
    "gym": (
        "Gym / light training: a plausible training meal. You may mix "
        "household measures and explicit grams in the same meal "
        '(e.g. "a cup of milk + two eggs", or "150 g of chicken").'
    ),
    "cut": (
        "Cutting: slightly smaller but still plausible portions. "
        "Household measures only."
    ),
}

_FAMILY_INSTRUCTION = {
    "log": (
        "Family is log: the user already ate this meal and wants it recorded. "
        "Write one request to log it."
    ),
    "evaluate": (
        "Family is evaluate: the user proposes this exact meal as their plan "
        "and wants it assessed. Write one request to evaluate it."
    ),
}

_SCHEMA_BLOCK = """\
Return exactly one JSON object and nothing else (no markdown, no prose):
{"items":[{"food":"<spoken name>","expression":"<portion phrase>"}],"query":"<one sentence>"}

Rules:
- Pick 1-3 foods that form a plausible meal for this persona.
- "food" is a spoken name from the pool (an alias or short name). Never a food_id slug.
- "expression" is natural user speech using only the allowed vocabulary.
- "query" is ONE sentence a real person would type. It must mention each chosen food.
- Do not leak window numbers or answers."""

_VOCAB_BLOCK = """\
Allowed portion vocabulary (handbook coverage; do not invent other units):
- cup, tbsp (tablespoon), tsp (teaspoon), slice, piece (also "each"), can, fl_oz (fluid ounce)
- serving / portion / bowl / plate / order (one default serving)
- thick / thin / regular (a different default serving of the same food; never "a thick slice")
- "a serving of"
- ounces ("2 oz", "two ounces")
- grams ("150 g", "150 grams") — gym persona only; everyday/cut must not use grams"""

_FORBID_BLOCK = """\
Forbidden:
- food_id slugs (milk_whole, chicken_breast, or any underscore id)
- window numbers (kcal, protein_g, carb_g, fat_g and any numeric targets)
- numeric answers (do not copy gram-table values into the query as the spoken amount, except gym gram phrases)
- catalog ids, portion-table slugs, or leaking the answer"""


def build_system_prompt(*, persona: str, family: str) -> str:
    """Persona + family + handbook vocabulary + fixed JSON schema."""
    flavor = _PERSONA_FLAVOR.get(
        persona,
        f"Persona {persona}: compose a plausible everyday meal.",
    )
    family_line = _FAMILY_INSTRUCTION.get(
        family,
        f"Family is {family}: write one natural-language user request.",
    )
    grams_rule = (
        "You may mix household measures and explicit grams."
        if persona == "gym"
        else "Do not use grams or numeric gram amounts; stay on household measures."
    )
    return "\n".join(
        [
            "You compose one plausible meal from a provided food pool and write "
            "a single natural-language user query.",
            "",
            f"Persona: {flavor}",
            f"{family_line}",
            grams_rule,
            "",
            _VOCAB_BLOCK,
            "",
            _FORBID_BLOCK,
            "",
            _SCHEMA_BLOCK,
        ]
    )


def build_user_prompt(pool: FoodPool) -> str:
    """Compact pool table: spoken name + portion key → grams per unit."""
    lines = [
        f"Food pool {pool.pool_id} (pick 1-3 foods):",
    ]
    for food in pool.foods:
        spoken = _spoken_name(food)
        also = [alias for alias in food.aliases if alias.strip().lower() != spoken.lower()]
        header = f"- {spoken} — {food.name}"
        if also:
            header += f" (also called: {', '.join(also)})"
        lines.append(header)
        per_unit: dict[str, float] = {}
        for alt in food.alternatives:
            if alt.quantity <= 0:
                continue
            per_unit.setdefault(alt.key, round(alt.grams / alt.quantity, 2))
        if per_unit:
            bits = [f"{key}={grams:g}g" for key, grams in per_unit.items()]
            lines.append("  portions (key → grams per 1 unit): " + ", ".join(bits))
    lines.append("")
    lines.append("Compose one meal. Output the JSON object only.")
    return "\n".join(lines)


def parse_expander_payload(text: object) -> dict[str, object] | None:
    """Return a schema-valid payload, or None if structurally damaged."""
    if not isinstance(text, str) or not text.strip():
        return None
    data = _extract_json_object(text)
    if not isinstance(data, Mapping):
        return None
    query = data.get("query")
    items_raw = data.get("items")
    if not isinstance(query, str) or not query.strip():
        return None
    if not isinstance(items_raw, Sequence) or isinstance(items_raw, (str, bytes)):
        return None
    items: list[dict[str, str]] = []
    for item in items_raw:
        if not isinstance(item, Mapping):
            return None
        food = item.get("food")
        expression = item.get("expression")
        if not isinstance(food, str) or not food.strip():
            return None
        if not isinstance(expression, str) or not expression.strip():
            return None
        items.append({"food": food.strip(), "expression": expression.strip()})
    if not items:
        return None
    return {"items": items, "query": query.strip()}


def _extract_json_object(text: str) -> object | None:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.S | re.I)
    candidates = [fenced.group(1), stripped] if fenced else [stripped]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        first = len(candidate) - len(candidate.lstrip())
        if first < len(candidate) and candidate[first] in "{[":
            try:
                data, _ = decoder.raw_decode(candidate, first)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                return data
        for start in (match.start() for match in re.finditer(r"\{", candidate)):
            try:
                data, _ = decoder.raw_decode(candidate, start)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return None


def _live_complete(model_id: str, messages: Sequence[Mapping[str, str]]) -> str:
    return complete_chat(model_id, messages)


class LlmExpander:
    """Real expander: one meal + query per pool, routed across models."""

    def __init__(
        self,
        *,
        route: Sequence[str],
        seed: int = 0,
        complete: Completer | None = None,
        parse_retries: int = 1,
    ) -> None:
        if not route:
            raise RuntimeError("no enabled expander models in the route table")
        self._route = tuple(route)
        self._seed = int(seed)
        self._complete = complete if complete is not None else _live_complete
        self._parse_retries = max(0, int(parse_retries))
        self._index = 0

    def __call__(
        self, pool: FoodPool, *, persona: str, family: str
    ) -> dict[str, object]:
        model_id = assign_model(self._index, self._route, seed=self._seed)
        self._index += 1
        messages = (
            {"role": "system", "content": build_system_prompt(persona=persona, family=family)},
            {"role": "user", "content": build_user_prompt(pool)},
        )
        last: dict[str, object] = {"items": [], "query": ""}
        for _attempt in range(1 + self._parse_retries):
            text = self._complete(model_id, messages)
            parsed = parse_expander_payload(text)
            if parsed is not None:
                return parsed
        return last


def make_llm_expander(
    *,
    model_route: object = None,
    seed: int = 0,
    complete: Completer | None = None,
    parse_retries: int = 1,
    disabled: Sequence[str] | None = None,
) -> LlmExpander:
    """Build a routed expander. Empty ``model_route`` → one default model."""
    parsed = parse_model_route(model_route)
    if not parsed:
        parsed = (DEFAULT_EXPANDER_MODEL,)
    route = enabled_route(parsed, disabled or ())
    if not route:
        raise RuntimeError("no enabled expander models in the route table")
    return LlmExpander(
        route=route,
        seed=seed,
        complete=complete,
        parse_retries=parse_retries,
    )
