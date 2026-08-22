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
from .types import COMPOSITE_FAMILY, COMPOSITE_STEPS, MAX_PER_POOL, Candidate, FoodPool, PoolFood

__all__ = [
    "HANDBOOK_VOCABULARY",
    "LlmExpander",
    "build_system_prompt",
    "build_user_prompt",
    "coerce_candidates",
    "food_in_pool",
    "make_llm_expander",
    "match_pool_food",
    "parse_expander_payload",
    "synthetic_expander",
    "validate_expander_payload",
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

_WINDOW_LEAK = re.compile(r"\b(?:kcal|protein_g|carb_g|fat_g)\s+\d")
_SLUG = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")


def food_in_pool(token: str, pool: FoodPool) -> bool:
    """True when ``token`` names a pool food (id, short name, or alias)."""
    raw = token.strip().lower()
    if not raw:
        return False
    return any(raw in _pool_keys(food) for food in pool.foods)


def match_pool_food(token: str, pool: FoodPool) -> str | None:
    """Return the unique pool ``food_id`` that ``token`` names, or None.

    Uses the same keys as expander validation (id, full name, comma-head
    short name, aliases). Ambiguous heads (two coffees both named
    ``Coffee, …``) stay unmatched so the resolver cannot pick the wrong row.
    """
    raw = token.strip().lower()
    if not raw:
        return None
    hits = [food.food_id for food in pool.foods if raw in _pool_keys(food)]
    if len(hits) == 1:
        return hits[0]
    return None


def _pool_keys(food: PoolFood) -> set[str]:
    keys = {food.food_id.lower(), _spoken_name(food).lower()}
    name = food.name.strip()
    if name:
        keys.add(name.lower())
        keys.add(name.split(",", 1)[0].strip().lower())
    keys.update(alias.strip().lower() for alias in food.aliases if alias.strip())
    return keys


def validate_expander_payload(payload: object, pool: FoodPool) -> list[str]:
    """Return issue strings. Empty means schema, pool refs, and leaks are ok."""
    parsed = _as_parsed_payload(payload)
    if parsed is None:
        return ["schema"]
    issues: list[str] = []
    for item in parsed["items"]:
        food = item["food"]
        if not food_in_pool(food, pool):
            issues.append(f"food {food!r} is not in pool")
    if _query_leaks(str(parsed["query"]), pool):
        issues.append("query leak")
    return issues


def _as_parsed_payload(payload: object) -> dict[str, object] | None:
    if isinstance(payload, str):
        return parse_expander_payload(payload)
    if isinstance(payload, Mapping):
        return parse_expander_payload(json.dumps(payload))
    return None


def _query_leaks(query: str, pool: FoodPool) -> bool:
    lowered = query.lower()
    if "catalog id" in lowered or "food_id" in lowered:
        return True
    if _WINDOW_LEAK.search(query):
        return True
    pool_ids = {food.food_id.lower() for food in pool.foods}
    return any(token in pool_ids for token in _SLUG.findall(lowered))


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
    pool: FoodPool,
    *,
    persona: str,
    family: str,
    items: int | None = None,
    amount_path: str | None = None,
    exclude_allergens: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Deterministic fake: compose 1–2 pool foods with a table phrase.

    Used by the tracer-bullet freeze. No network, no clock, no RNG.

    Recipe hints (issue 15 transport): ``items`` composes exactly N
    speakable pool foods -- fewer available yields the empty payload
    (fail-closed), never a smaller plate. ``amount_path="explicit_grams"``
    speaks the food's one-portion gram amount ("150 g") instead of the table
    phrase. ``exclude_allergens`` skips pool foods whose catalog allergen
    tags intersect the set (the fit→knife construction needs an allergen-free
    plate so the knife can add the carrier). Defaults keep today's behavior.
    """
    banned = {str(tag).strip().lower() for tag in (exclude_allergens or ())} - {""}
    chosen: list[tuple[PoolFood, str]] = []

    def _phrase_for(food: PoolFood) -> str | None:
        if amount_path == "explicit_grams":
            # Fail-closed like items: a food without a one-portion table
            # value is skipped rather than falling back to a mixed phrase.
            one = next(
                (
                    alt.grams
                    for alt in food.alternatives
                    if alt.quantity == 1.0 and alt.grams > 0
                ),
                None,
            )
            return None if one is None else f"{one:g} g"
        return _preferred_phrase(food)

    def _excluded(food: PoolFood) -> bool:
        return bool(
            banned & {str(tag).lower() for tag in food.allergen_tags}
        )

    if family == COMPOSITE_FAMILY:
        # ADR 0014 six-nutrient windows leave a finite daily budget, and a
        # heavy tracer plate can spend it all — the draft is then (correctly)
        # dropped as unpassable. Keep the composite tracer plate to the
        # lightest single pool food so the sample stays writable. Recipe
        # hints do not apply: the composite shape owns its plate.
        lightest = min(
            (food for food in pool.foods if _preferred_phrase(food) is not None),
            key=lambda food: min(
                alt.grams for alt in food.alternatives if alt.quantity == 1.0
            ),
            default=None,
        )
        chosen = (
            [(lightest, _preferred_phrase(lightest))] if lightest is not None else []
        )
    else:
        limit = items if items else 2
        for food in pool.foods:
            if _excluded(food):
                continue
            phrase = _phrase_for(food)
            if phrase is None:
                continue
            chosen.append((food, phrase))
            if len(chosen) >= limit:
                break
        if len(chosen) < (items or 0):
            # Fail-closed: fewer speakable non-excluded foods than requested
            # is an empty candidate (schema-dropped), never a smaller plate.
            return {"items": [], "query": ""}
    if not chosen:
        return {"items": [], "query": ""}
    # Named payload_items so the ``items`` recipe hint parameter is not
    # shadowed.
    payload_items = [
        {"food": food.food_id, "expression": phrase} for food, phrase in chosen
    ]
    parts = [f"{phrase} of {_spoken_name(food)}" for food, phrase in chosen]
    if len(parts) == 1:
        meal = parts[0]
    else:
        meal = ", and ".join(parts)
    if family == "evaluate":
        # The spoken occasion feeds the knife branch's window derivation.
        query = f"Evaluate this as my plan for dinner: {meal}."
        return {"items": payload_items, "query": query}
    if family == COMPOSITE_FAMILY:
        query = (
            f"Please log {meal} for lunch, then recommend a dinner that fits "
            "what's left."
        )
        return {
            "items": payload_items,
            "query": query,
            "steps": list(COMPOSITE_STEPS),
        }
    if family == "recommend":
        # The named foods stay spoken context: the recommend oracle judges a
        # free plan, so the query never states window numbers.
        query = f"What should I eat along with {meal} for dinner?"
        return {"items": payload_items, "query": query}
    if family == "update":
        # The named food evidences the profile change; its catalog allergen
        # tags become the oracle's added allergies (resolver-side). Pick a
        # pool food that actually carries a tag; a pool without one yields
        # no candidate (the pool is then schema-dropped, fail-closed). The
        # query speaks the tag words themselves -- the oracle stores tags,
        # never speech, and the validator demands tag-level evidence.
        carrier = next(
            (
                food
                for food in pool.foods
                if food.allergen_tags and _preferred_phrase(food) is not None
            ),
            None,
        )
        if carrier is None:
            return {"items": [], "query": ""}
        tags = " and ".join(sorted(tag.replace("_", " ") for tag in carrier.allergen_tags))
        query = (
            f"Please remember, I am now allergic to {tags}, "
            f"so no more {_spoken_name(carrier)}."
        )
        return {
            "items": [
                {"food": carrier.food_id, "expression": _preferred_phrase(carrier)}
            ],
            "query": query,
        }
    query = f"Please log {meal} for lunch."
    return {"items": payload_items, "query": query}


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
    steps = _steps_from_payload(payload, family=family)
    if family == COMPOSITE_FAMILY and steps is None:
        return None
    return Candidate(
        items=tuple(items),
        query=query.strip(),
        family=family,
        persona=persona,
        pool_id=pool_id,
        steps=steps or (),
    )


def _steps_from_payload(payload: Mapping, *, family: str) -> tuple[str, ...] | None:
    raw = payload.get("steps")
    if raw is None:
        if family == COMPOSITE_FAMILY:
            return COMPOSITE_STEPS
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return None
    steps: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            return None
        steps.append(item.strip())
    if family == COMPOSITE_FAMILY and len(steps) < 2:
        return None
    return tuple(steps)


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
    "composite": (
        "Family is composite: the user already ate this meal AND wants a "
        "recommendation for what to eat next (typically dinner) that fits "
        "the remaining daily windows. Write ONE natural-language request "
        "that does both steps (log, then recommend). Do not leak window numbers."
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

_COMPOSITE_SCHEMA_BLOCK = """\
Return exactly one JSON object and nothing else (no markdown, no prose):
{"items":[{"food":"<spoken name>","expression":"<portion phrase>"}],"query":"<multi-step request>","steps":["log","recommend"]}

Rules:
- Pick 1-3 foods that form a plausible meal the user already ate.
- "food" is a spoken name from the pool (an alias or short name). Never a food_id slug.
- "expression" is natural user speech using only the allowed vocabulary.
- "query" is what a real person would type: first log the named meal, then ask for a next meal (dinner) that fits what is left of the day. It must mention each chosen food.
- "steps" must be exactly ["log","recommend"].
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
    schema = _COMPOSITE_SCHEMA_BLOCK if family == COMPOSITE_FAMILY else _SCHEMA_BLOCK
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
            schema,
        ]
    )


def build_user_prompt(pool: FoodPool, *, family: str = "log") -> str:
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
    if family == "evaluate":
        lines.append(
            "The user wants this exact meal assessed as a plan. "
            "Write an evaluate request; do not include kcal numbers."
        )
    else:
        lines.append("The user already ate this meal. Write a log request.")
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
    parsed: dict[str, object] = {"items": items, "query": query.strip()}
    if "steps" in data:
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes)):
            return None
        steps: list[str] = []
        for step in raw_steps:
            if not isinstance(step, str) or not step.strip():
                return None
            steps.append(step.strip())
        if len(steps) < 2:
            return None
        parsed["steps"] = steps
    return parsed


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
            {"role": "user", "content": build_user_prompt(pool, family=family)},
        )
        last: dict[str, object] = {"items": [], "query": ""}
        for _attempt in range(1 + self._parse_retries):
            text = self._complete(model_id, messages)
            parsed = parse_expander_payload(text)
            if parsed is None:
                continue
            if validate_expander_payload(parsed, pool):
                continue
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
