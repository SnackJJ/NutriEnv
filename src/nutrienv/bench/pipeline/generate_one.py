"""Single-task mill entry: sample a roster world, expand Log as {query, foods}."""

from __future__ import annotations

import copy
import json
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from nutrienv.bench.realize import Oracle, Task, realize_evaluate
from nutrienv.world.portions import GRAM_UNITS, OUNCE_UNITS, UNIT_SYNONYMS, resolve_portion
from nutrienv.world.types import MAX_ITEM_GRAMS, LedgerRow, WorldState

from .resolver import spoken_grams_from_query
from .roster import RosterPerson, profile_for, sample_roster_person
from .sampler import sample_pools
from .semantic_vote import GRAM_TOLERANCE
from .types import (
    DEFAULT_GENERATE_POOL_SIZE,
    FoodPool,
    PoolFood,
    Rejected,
)

__all__ = [
    "AMOUNT_PATHS",
    "GenerateOneResult",
    "LogExpander",
    "build_log_system_prompt",
    "build_log_user_prompt",
    "generate_one",
    "make_log_expander",
    "parse_query_foods_payload",
]

AMOUNT_EXPLICIT_GRAMS = "explicit_grams"
AMOUNT_NAMED_MEASURE = "named_measure"
AMOUNT_UNSPECIFIED = "unspecified"
AMOUNT_PATHS: tuple[str, ...] = (
    AMOUNT_EXPLICIT_GRAMS,
    AMOUNT_NAMED_MEASURE,
    AMOUNT_UNSPECIFIED,
)

_OCCASIONS: tuple[str, ...] = ("breakfast", "lunch", "dinner")
_NAMED_PORTION_KEYS = frozenset(
    {"cup", "tbsp", "tsp", "slice", "piece", "can", "fl_oz"}
)
_WORD = re.compile(r"[a-z0-9.]+")
_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d)")
_QUANTITY_AND = re.compile(
    r"(?i)\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"\d+(?:\.\d+)?)\s+and\s+(?:a\s+)?(?:half|quarter|third|halves|quarters|thirds)\b"
)
_HYPHEN_QUANTITY_AND = re.compile(
    r"(?i)\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"\d+(?:\.\d+)?)-and-(?:a-)?(half|quarter|third|halves|quarters|thirds)\b"
)
_FOOD_SPLIT = re.compile(r",|\band\b|\bwith\b|\bplus\b|&", re.I)
_PROTECT_SLOT = re.compile(r"\x00(\d+)\x00")
_MENTION_STOP = frozenset(
    {
        "and",
        "the",
        "for",
        "with",
        "plus",
        "please",
        "log",
        "lunch",
        "dinner",
        "breakfast",
        "today",
        "another",
        "cup",
        "cups",
        "bowl",
        "bowls",
        "piece",
        "pieces",
        "slice",
        "slices",
    }
)


@dataclass(frozen=True)
class GenerateOneResult:
    accepted: Task | None
    rejected: Rejected | None


def generate_one(
    *,
    catalog: Mapping,
    expander: Callable[..., object],
    family: str = "log",
    seed: int = 0,
    person: RosterPerson | None = None,
    amount_path: str | None = None,
    occasion: str = "lunch",
    pool_size: int = DEFAULT_GENERATE_POOL_SIZE,
) -> GenerateOneResult:
    """One mill item: roster person → world windows → pool → expander → speech bind."""
    if family not in {"log", "evaluate"}:
        raise ValueError(f"generate_one does not implement {family!r}")
    if amount_path is not None and amount_path not in AMOUNT_PATHS:
        raise ValueError(f"unknown amount_path {amount_path!r}")
    if occasion not in _OCCASIONS:
        raise ValueError(f"unknown occasion {occasion!r}")

    rng = random.Random(seed)
    chosen = person if person is not None else sample_roster_person(seed)
    path = amount_path if amount_path is not None else rng.choice(AMOUNT_PATHS)
    profile = profile_for(chosen)
    pools = sample_pools(
        catalog,
        seed=seed,
        family=family,
        n_pools=1,
        pool_size=pool_size,
    )
    if not pools:
        return GenerateOneResult(
            accepted=None, rejected=Rejected("", "empty_pool", family)
        )
    pool = _without_small_gram_foods(pools[0])
    if not pool.foods:
        return GenerateOneResult(
            accepted=None, rejected=Rejected("", "empty_pool", family)
        )
    raw = expander(
        pool, persona=chosen.persona, family=family, amount_path=path
    )
    payload = parse_query_foods_payload(raw)
    if payload is None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected("", "schema", family)
        )
    query = str(payload["query"])
    foods = list(payload["foods"])
    bound, reason = _bind_log_foods(
        query, foods, pool, catalog, occasion, amount_path=path
    )
    if reason is not None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, reason, family)
        )
    s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
    if family == "evaluate":
        return _evaluate_from_bound(
            query, bound, s0, seed=seed, occasion=occasion, persona=chosen.persona
        )
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


def _evaluate_from_bound(
    query: str,
    bound: Sequence,
    s0: WorldState,
    *,
    seed: int,
    occasion: str,
    persona: str,
) -> GenerateOneResult:
    items = [{"food_id": row.food_id, "grams": float(row.grams)} for row in bound]
    try:
        task = realize_evaluate(
            task_id=f"one-eval-{seed:04d}",
            query=query,
            items=items,
            s0=s0,
            occasion=occasion,
        )
    except ValueError:
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, "empty_windows", "evaluate")
        )
    task = Task(
        task.id,
        task.family,
        task.query,
        task.s0,
        task.oracle,
        ("evaluate_fit",),
        persona,
    )
    if task.oracle.last_verdict != "accept":
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, "not_fit", "evaluate")
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
    if set(payload) != {"query", "foods"}:
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
    if amount_path == AMOUNT_EXPLICIT_GRAMS:
        lines.append(
            'Amount path is explicit grams: you may write household grams such as "150 g".'
        )
    elif amount_path == AMOUNT_NAMED_MEASURE:
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


def build_log_user_prompt(pool: FoodPool) -> str:
    """Pool table for the Log expander. foods in JSON must be these ids."""
    lines = [
        f"Food pool {pool.pool_id} (pick 1-3 foods; JSON foods must be pool ids):",
    ]
    for food in pool.foods:
        spoken = food.aliases[0] if food.aliases else food.name.split(",", 1)[0]
        lines.append(f"- id={food.food_id} spoken={spoken} — {food.name}")
    lines.append("")
    lines.append("The user already ate this meal. Write a log request.")
    lines.append("Compose one meal. Output the JSON object only.")
    return "\n".join(lines)


class LogExpander:
    """Mill expander: {query, foods} JSON, amount path in the system prompt."""

    def __init__(
        self,
        *,
        complete: Callable[[str, Sequence[Mapping[str, str]]], str],
        parse_retries: int = 1,
    ) -> None:
        self._complete = complete
        self._parse_retries = max(0, int(parse_retries))

    def __call__(
        self,
        pool: FoodPool,
        *,
        persona: str,
        family: str,
        amount_path: str,
    ) -> dict[str, object]:
        messages = (
            {
                "role": "system",
                "content": build_log_system_prompt(
                    amount_path=amount_path, persona=persona
                ),
            },
            {"role": "user", "content": build_log_user_prompt(pool)},
        )
        last: dict[str, object] = {"query": "", "foods": []}
        for _attempt in range(1 + self._parse_retries):
            parsed = parse_query_foods_payload(self._complete("log-expander", messages))
            if parsed is not None:
                return parsed
        return last


def make_log_expander(
    *,
    complete: Callable[[str, Sequence[Mapping[str, str]]], str],
    parse_retries: int = 1,
) -> LogExpander:
    """Build the Log mill expander. complete is injected; no live API required."""
    return LogExpander(complete=complete, parse_retries=parse_retries)


def _bind_log_foods(
    query: str,
    foods: Sequence[str],
    pool: FoodPool,
    catalog: Mapping,
    occasion: str,
    *,
    amount_path: str,
) -> tuple[list[LedgerRow] | None, str | None]:
    pool_ids = {food.food_id for food in pool.foods}
    eaten_at = f"today-{occasion}"
    query = _normalize_quantity_english(query)
    if len(foods) != len(set(foods)):
        return None, "duplicate"
    for food_id in foods:
        if food_id not in pool_ids or food_id not in catalog:
            return None, "not_in_pool"
    if _ambiguous_mention(query, pool, catalog):
        return None, "ambiguous"
    mentioned = _mentioned_pool_ids(query, pool, catalog)
    if mentioned - set(foods):
        return None, "omitted_food"
    if _repeated_speech(query, foods, catalog):
        return None, "repeat"
    rows: list[LedgerRow] = []
    for food_id in foods:
        clause = _local_clause(query, food_id, catalog)
        if clause is None:
            return None, "unresolvable"
        spoken = _speech_amount_path(clause)
        if spoken != amount_path:
            return None, "unresolvable" if spoken is None else "amount_path"
        if amount_path == AMOUNT_UNSPECIFIED:
            grams = _qns_grams(food_id, clause, catalog)
        else:
            grams = spoken_grams_from_query(clause, food_id, catalog)
            if grams is None:
                grams = resolve_portion(food_id, clause, catalog)
        if grams is None:
            return None, "unresolvable"
        if float(grams) <= GRAM_TOLERANCE:
            return None, "small_grams"
        if float(grams) > MAX_ITEM_GRAMS:
            return None, "over_cap"
        rows.append(LedgerRow(food_id, float(grams), eaten_at))
    if not rows:
        return None, "unresolvable"
    return rows, None


def _normalize_quantity_english(query: str) -> str:
    """Keep 1,500 and one-and-a-half as one quantity before clause splitting."""
    query = _THOUSANDS_COMMA.sub("", query)

    def _spaced(match: re.Match[str]) -> str:
        number, frac = match.group(1), match.group(2)
        if frac in {"half", "quarter", "third"}:
            return f"{number} and a {frac}"
        return f"{number} and {frac}"

    return _HYPHEN_QUANTITY_AND.sub(_spaced, query)


def _food_clauses(query: str) -> list[str]:
    """Split a meal into per-food spans, keeping quantity English intact."""
    held: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        held.append(match.group(0))
        return f"\x00{len(held) - 1}\x00"

    protected = _QUANTITY_AND.sub(_hold, query)
    parts = _FOOD_SPLIT.split(protected)
    clauses: list[str] = []
    for part in parts:
        restored = _PROTECT_SLOT.sub(lambda match: held[int(match.group(1))], part)
        text = restored.strip()
        if text:
            clauses.append(text)
    return clauses


def _repeated_speech(
    query: str, food_ids: Sequence[str], catalog: Mapping
) -> bool:
    """True when the query reports the same food in more than one clause."""
    clauses = _food_clauses(query)
    for food_id in food_ids:
        hits = sum(
            1 for clause in clauses if _clause_mentions(clause, food_id, catalog)
        )
        if hits > 1:
            return True
    return False


def _clause_mentions(clause: str, food_id: str, catalog: Mapping) -> bool:
    lowered = clause.lower()
    for name in _spoken_names(food_id, catalog):
        needle = name.strip().lower()
        if len(needle) < 3 or needle in _MENTION_STOP:
            continue
        if re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", lowered):
            return True
    return False


def _local_clause(query: str, food_id: str, catalog: Mapping) -> str | None:
    """Speech span for one food: a neighbor's unit cannot leak across coordinators."""
    best: tuple[int, str] | None = None
    for clause in _food_clauses(query):
        lowered = clause.lower()
        for name in _spoken_names(food_id, catalog):
            needle = name.strip().lower()
            if len(needle) < 3:
                continue
            if re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", lowered):
                if best is None or len(needle) > best[0]:
                    best = (len(needle), clause)
    return None if best is None else best[1]


def _ambiguous_mention(query: str, pool: FoodPool, catalog: Mapping) -> bool:
    """True when two pool ids claim overlapping spoken spans (rice / white rice)."""
    spans = _mention_spans(query, [food.food_id for food in pool.foods], catalog)
    for index, (start, end, food_id) in enumerate(spans):
        for other_start, other_end, other_id in spans[index + 1 :]:
            if food_id != other_id and start < other_end and other_start < end:
                return True
    return False


def _mention_spans(
    query: str, food_ids: Sequence[str], catalog: Mapping
) -> list[tuple[int, int, str]]:
    lowered = query.lower()
    spans: list[tuple[int, int, str]] = []
    for food_id in food_ids:
        for name in _spoken_names(food_id, catalog):
            needle = name.strip().lower()
            if len(needle) < 3 or needle in _MENTION_STOP:
                continue
            for match in re.finditer(
                rf"(?<![\w]){re.escape(needle)}(?![\w])", lowered
            ):
                spans.append((match.start(), match.end(), food_id))
    return spans


def _mentioned_pool_ids(query: str, pool: FoodPool, catalog: Mapping) -> set[str]:
    """Pool ids whose name or alias appears anywhere in the query."""
    mentioned: set[str] = set()
    lowered = query.lower()
    for food in pool.foods:
        for name in _spoken_names(food.food_id, catalog):
            needle = name.strip().lower()
            if len(needle) < 3 or needle in _MENTION_STOP:
                continue
            if re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", lowered):
                mentioned.add(food.food_id)
                break
    return mentioned


def _spoken_names(food_id: str, catalog: Mapping) -> list[str]:
    entry = catalog.get(food_id) or {}
    names = [food_id.replace("_", " ")]
    name = str(entry.get("name") or "")
    if name.strip():
        names.append(name)
        if "," in name:
            names.append(name.split(",", 1)[0])
    names.extend(str(alias) for alias in (entry.get("aliases") or []))
    return names


def _qns_grams(food_id: str, clause: str, catalog: Mapping) -> float | None:
    """Unspecified bowl/plate/order binds FNDDS QNS only, never cup fallback."""
    entry = catalog.get(food_id) or {}
    portions = entry.get("portions") or {}
    qns = portions.get("qns")
    if isinstance(qns, bool) or not isinstance(qns, (int, float)) or qns <= 0:
        return None
    probe = {
        food_id: {
            "name": entry.get("name") or food_id,
            "aliases": list(entry.get("aliases") or []),
            "portions": {"qns": float(qns)},
        }
    }
    grams = spoken_grams_from_query(clause, food_id, probe)
    if grams is None:
        grams = resolve_portion(food_id, clause, probe)
    return grams


def _speech_amount_path(text: str) -> str | None:
    """Which amount path the spoken units belong to, or None if mixed/absent."""
    classes: set[str] = set()
    for token in _WORD.findall(text.lower()):
        if token in GRAM_UNITS:
            classes.add(AMOUNT_EXPLICIT_GRAMS)
            continue
        if token in OUNCE_UNITS:
            classes.add(AMOUNT_NAMED_MEASURE)
            continue
        key = UNIT_SYNONYMS.get(token)
        if key in _NAMED_PORTION_KEYS:
            classes.add(AMOUNT_NAMED_MEASURE)
        elif key == "serving":
            classes.add(AMOUNT_UNSPECIFIED)
    if len(classes) != 1:
        return None
    return next(iter(classes))


def _without_small_gram_foods(pool: FoodPool) -> FoodPool:
    """Drop foods whose 1.0 portions all sit inside the ±10 g phrasing band."""
    foods = tuple(food for food in pool.foods if _has_portion_outside_band(food))
    return FoodPool(pool_id=pool.pool_id, family=pool.family, foods=foods)


def _has_portion_outside_band(food: PoolFood) -> bool:
    return any(
        alt.quantity == 1.0 and alt.grams > GRAM_TOLERANCE for alt in food.alternatives
    )
