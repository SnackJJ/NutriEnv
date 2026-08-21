"""Single-task mill entry: sample a roster world, expand Log as {query, foods}."""

from __future__ import annotations

import copy
import json
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from nutrienv.bench.realize import Oracle, Task, realize_evaluate
from nutrienv.world.daily_windows import (
    derive_profile_windows,
    estimated_energy_requirement,
    plan_windows_for_meal,
)
from nutrienv.world.portions import GRAM_UNITS, OUNCE_UNITS, UNIT_SYNONYMS, resolve_portion
from nutrienv.world.types import MAX_ITEM_GRAMS, LedgerRow, WorldState, ledger_totals, normalize_tags

from .knives import KNIVES, apply_knife
from .resolver import spoken_grams_from_query
from .roster import RosterPerson, profile_for, sample_roster_person
from .sampler import sample_pools
from .semantic_vote import GRAM_TOLERANCE
from .templates import recommend_query, update_query
from .types import (
    DEFAULT_GENERATE_POOL_SIZE,
    FoodPool,
    PoolFood,
    Rejected,
)

__all__ = [
    "AMOUNT_PATHS",
    "KNIVES",
    "GenerateOneResult",
    "LogExpander",
    "build_log_system_prompt",
    "build_log_user_prompt",
    "build_stage_a_prompt",
    "build_unfit_rewrite_prompt",
    "generate_one",
    "make_log_expander",
    "make_unfit_rewriter",
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
_SCENES: tuple[str, ...] = ("empty", "leftover")
_RECOMMEND_SHELLS_BY_OCCASION: dict[str, str] = {
    "breakfast": "rec-breakfast",
    "lunch": "rec-lunch",
    "dinner": "rec-dinner",
    "snack": "rec-snack",
}
# Recommend additionally accepts the thin snack occasion (no energy share).
_RECOMMEND_OCCASIONS: frozenset[str] = frozenset(_OCCASIONS) | {"snack"}
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
    expander: Callable[..., object] | None = None,
    family: str = "log",
    seed: int = 0,
    person: RosterPerson | None = None,
    amount_path: str | None = None,
    occasion: str = "lunch",
    pool_size: int = DEFAULT_GENERATE_POOL_SIZE,
    knife: str | None = None,
    rewriter: Callable[..., object] | None = None,
    scene: str = "empty",
    prior_ledger: Sequence[LedgerRow] | None = None,
    last_meal: bool = False,
    shell: str | None = None,
    slots: Mapping[str, str] | None = None,
) -> GenerateOneResult:
    """One mill item: roster person → world windows → pool → expander → speech bind.

    Recommend items are template-filled (``shell``/``slots``) with no expander.
    """
    if family not in {"log", "evaluate", "recommend", "update"}:
        raise ValueError(f"generate_one does not implement {family!r}")
    if amount_path is not None and amount_path not in AMOUNT_PATHS:
        raise ValueError(f"unknown amount_path {amount_path!r}")
    if occasion not in _OCCASIONS and not (
        family == "recommend" and occasion in _RECOMMEND_OCCASIONS
    ):
        raise ValueError(f"unknown occasion {occasion!r}")
    if knife is not None and knife not in KNIVES:
        raise ValueError(f"unknown knife {knife!r}")
    if scene not in _SCENES:
        raise ValueError(f"unknown scene {scene!r}")

    rng = random.Random(seed)
    chosen = person if person is not None else sample_roster_person(seed)
    profile = profile_for(chosen)

    if family == "recommend":
        return _recommend_from_template(
            catalog,
            chosen=chosen,
            profile=profile,
            seed=seed,
            occasion=occasion,
            scene=scene,
            prior_ledger=prior_ledger,
            shell=shell,
            slots=dict(slots or {}),
        )

    if family == "update":
        if knife is not None or scene != "empty" or prior_ledger:
            raise ValueError("knives, scenes, and prior ledgers apply only to evaluate")
        return _update_from_template(
            catalog,
            chosen=chosen,
            profile=profile,
            seed=seed,
            shell=shell,
            slots=dict(slots or {}),
        )

    if family == "log" and (knife is not None or scene != "empty"):
        raise ValueError("knives and leftover scenes apply only to evaluate")
    path = amount_path if amount_path is not None else rng.choice(AMOUNT_PATHS)
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
    if expander is None:
        raise ValueError(f"family {family!r} requires an injected expander")
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
    ledger: list[LedgerRow] = []
    if scene == "leftover":
        if not prior_ledger:
            return GenerateOneResult(
                accepted=None, rejected=Rejected(query, "no_ledger", family)
            )
        ledger = list(prior_ledger)
    s0 = WorldState(profile=profile, ledger=ledger, catalog=catalog)
    if family == "evaluate":
        return _evaluate_from_bound(
            query,
            bound,
            s0,
            seed=seed,
            occasion=occasion,
            persona=chosen.persona,
            knife=knife,
            rewriter=rewriter,
            pool=pool,
            amount_path=path,
            last_meal=last_meal,
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


def _recommend_from_template(
    catalog: Mapping,
    *,
    chosen: RosterPerson,
    profile: object,
    seed: int,
    occasion: str,
    scene: str,
    prior_ledger: Sequence[LedgerRow] | None,
    shell: str | None,
    slots: dict[str, str],
) -> GenerateOneResult:
    """Template-filled Recommend: query from the agreed shells, work in S0."""
    default_shell = _RECOMMEND_SHELLS_BY_OCCASION[occasion]
    shell_id = shell if shell is not None else default_shell
    if (
        shell_id in _RECOMMEND_SHELLS_BY_OCCASION.values()
        and shell_id != default_shell
    ):
        # Shell text names an occasion; it must be the sampled one so the
        # query and the judged windows agree.
        return GenerateOneResult(
            accepted=None,
            rejected=Rejected("", "template_occasion", "recommend"),
        )
    fill = dict(slots)
    if shell_id == "rec-named-dish":
        dish = _allergen_dish(catalog, chosen, fill.get("dish"))
        if dish is None:
            return GenerateOneResult(
                accepted=None, rejected=Rejected("", "no_allergen_dish", "recommend")
            )
        fill["dish"] = dish
    elif shell_id == "rec-post-gym" and chosen.persona != "gym":
        return GenerateOneResult(
            accepted=None, rejected=Rejected("", "not_gym_persona", "recommend")
        )
    elif shell_id in {"rec-occasion"}:
        fill.setdefault("occasion", occasion)
    query = recommend_query(shell_id, fill)
    if query is None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected("", "template", "recommend")
        )
    ledger: list[LedgerRow] = []
    if scene == "leftover":
        # Leftover copies earlier Log tails verbatim; a dropped parent Log
        # means there is nothing to copy and the draft is dropped with it.
        if not prior_ledger:
            return GenerateOneResult(
                accepted=None,
                rejected=Rejected(query, "no_ledger", "recommend"),
            )
        ledger = list(prior_ledger)
    s0 = WorldState(profile=profile, ledger=ledger, catalog=catalog)
    eaten = ledger_totals(ledger, catalog)
    plan_windows = plan_windows_for_meal(profile.windows, eaten, occasion)
    if plan_windows is None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, "empty_windows", "recommend")
        )
    oracle = Oracle(
        profile=copy.deepcopy(profile),
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=plan_windows,
        ledger=tuple(ledger),
    )
    task = Task(
        f"one-rec-{seed:04d}",
        "recommend",
        query,
        s0,
        oracle,
        (),
        chosen.persona,
    )
    return GenerateOneResult(accepted=task, rejected=None)


def _update_from_template(
    catalog: Mapping,
    *,
    chosen: RosterPerson,
    profile: object,
    seed: int,
    shell: str | None,
    slots: dict[str, str],
) -> GenerateOneResult:
    """Template-filled Update: the query states the profile change."""
    if shell is None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected("", "template", "update")
        )
    query = update_query(shell, slots)
    if query is None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected("", "template", "update")
        )

    def reject(reason: str) -> GenerateOneResult:
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, reason, "update")
        )

    band: str | None = None
    expected = profile
    if shell in {"upd-add-allergy", "upd-add-allergy-short"}:
        spoken = slots.get("food") if shell == "upd-add-allergy" else slots.get("allergen")
        tags = _resolve_allergen_tags(catalog, spoken or "")
        if not tags:
            return reject("no_allergen_food")
        merged = normalize_tags(list(profile.allergies) + list(tags))
        if merged == tuple(profile.allergies):
            return reject("no_op_update")
        expected = replace(profile, allergies=merged)
    elif shell == "upd-rm-allergy":
        tags = _resolve_allergen_tags(catalog, slots.get("allergen") or "")
        if not tags:
            return reject("no_allergen_food")
        if not set(tags) & set(profile.allergies):
            return reject("not_allergic")
        remaining = tuple(
            item for item in profile.allergies if item not in tags
        )
        expected = replace(profile, allergies=remaining)
    elif shell == "upd-weight":
        n = _slot_number(slots)
        if n is None or n <= 0:
            return reject("bad_slot")
        candidate = replace(profile, weight_kg=n)
        derived = derive_profile_windows(candidate)
        if derived is None:
            return reject("bad_slot")
        expected = replace(candidate, windows=derived)
    elif shell == "upd-kcal-explicit":
        n = _slot_number(slots)
        if n is None or n == 0.0:
            return reject("bad_slot")
        lo, hi = profile.windows["kcal"]
        windows = {**profile.windows, "kcal": (lo + n, hi + n)}
        expected = replace(profile, windows=windows)
    elif shell == "upd-phase-cut":
        if profile.phase == "cut":
            return reject("already_cut")
        band = "cut"
        expected = replace(profile, phase="cut")
    elif shell == "upd-phase-muscle":
        if profile.phase == "muscle":
            return reject("already_muscle")
        band = "muscle"
        expected = replace(profile, phase="muscle")
    elif shell == "upd-fatigue":
        # Easing a deficit needs a deficit: S0 kcal-hi must sit below EER.
        eer = estimated_energy_requirement(
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity=profile.activity,
        )
        if profile.phase != "cut" or profile.windows["kcal"][1] >= eer:
            return reject("no_deficit")
        band = "fatigue"
        expected = profile
    elif shell == "upd-phase-maintain":
        if profile.phase != "cut":
            return reject("not_cutting")
        candidate = replace(profile, phase="maintain")
        derived = derive_profile_windows(candidate)
        if derived is None:
            return reject("bad_slot")
        expected = replace(candidate, windows=derived)
    else:
        return reject("template")

    oracle = Oracle(
        profile=copy.deepcopy(expected),
        ledger=(),
        update_band=band,
    )
    s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
    task = Task(
        f"one-upd-{seed:04d}",
        "update",
        query,
        s0,
        oracle,
        (),
        chosen.persona,
    )
    return GenerateOneResult(accepted=task, rejected=None)


def _slot_number(slots: dict[str, str]) -> float | None:
    try:
        value = float(slots["n"])
    except (KeyError, TypeError, ValueError):
        return None
    return value


def _resolve_allergen_tags(catalog: Mapping, spoken: str) -> tuple[str, ...]:
    """Spoken name → catalog allergen tags (Oracle stores tags, never speech)."""
    token = spoken.strip().lower()
    if not token:
        return ()
    for food_id in sorted(catalog):
        entry = catalog[food_id]
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        names = {food_id.replace("_", " ").lower(), name.lower()}
        if "," in name:
            names.add(name.split(",", 1)[0].lower())
        names.update(str(alias).lower() for alias in entry.get("aliases") or [])
        if token in names:
            tags = tuple(sorted(set(entry.get("allergen_tags") or [])))
            if tags:
                return tags
    for food_id in sorted(catalog):
        entry = catalog[food_id]
        if not isinstance(entry, dict):
            continue
        if token in {str(tag).lower() for tag in entry.get("allergen_tags") or []}:
            return (token,)
    return ()


def _allergen_dish(
    catalog: Mapping, chosen: RosterPerson, requested: str | None
) -> str | None:
    """A catalog food carrying one of the person's allergen tags.

    The spoken name fills {dish}; the query never says allergic.
    """
    banned = set(chosen.allergies)
    if not banned:
        return None
    if requested is not None:
        entry = catalog.get(requested)
        tags = set((entry or {}).get("allergen_tags") or [])
        if entry is None or not tags & banned:
            return None
        return _spoken_name(requested, entry)
    for food_id in sorted(catalog):
        entry = catalog[food_id]
        if not isinstance(entry, dict):
            continue
        if set(entry.get("allergen_tags") or []) & banned:
            return _spoken_name(food_id, entry)
    return None


def _spoken_name(food_id: str, entry: Mapping) -> str:
    aliases = entry.get("aliases") or []
    if aliases:
        return str(aliases[0])
    name = str(entry.get("name") or "")
    return name.split(",", 1)[0] if "," in name else name or food_id


def _evaluate_from_bound(
    query: str,
    bound: Sequence,
    s0: WorldState,
    *,
    seed: int,
    occasion: str,
    persona: str,
    knife: str | None,
    rewriter: Callable[..., object] | None,
    pool: FoodPool,
    amount_path: str,
    last_meal: bool,
) -> GenerateOneResult:
    items = [{"food_id": row.food_id, "grams": float(row.grams)} for row in bound]
    draft = _realize_eval(
        f"one-eval-{seed:04d}",
        query,
        items,
        s0,
        occasion,
        ("evaluate_fit",),
        persona,
        last_meal=last_meal,
    )
    if isinstance(draft, GenerateOneResult):
        return draft
    labels = draft.oracle.bound_labels
    if "leftover_under" in labels:
        if not last_meal:
            return GenerateOneResult(
                accepted=None, rejected=Rejected(query, "leftover_under", "evaluate")
            )
        return GenerateOneResult(
            accepted=_retag(
                draft, ("evaluate_unfit", "leftover_under", "draft_only"), persona
            ),
            rejected=None,
        )
    if "leftover_over" in labels and knife in (None, "over_slot"):
        return GenerateOneResult(
            accepted=_retag(draft, ("evaluate_unfit", "leftover_over"), persona),
            rejected=None,
        )
    if draft.oracle.last_verdict != "accept":
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, "not_fit", "evaluate")
        )
    if knife is None:
        return GenerateOneResult(accepted=draft, rejected=None)
    eaten = ledger_totals(list(s0.ledger), s0.catalog)
    windows = plan_windows_for_meal(
        s0.profile.windows, eaten, occasion, last_meal=last_meal
    )
    if windows is None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, "empty_windows", "evaluate")
        )
    knifed = apply_knife(
        knife,
        items,
        profile=s0.profile,
        catalog=s0.catalog,
        pool=pool,
        windows=windows,
    )
    if knifed is None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, "knife", "evaluate")
        )
    spoken = _rewrite_unfit(
        knifed,
        rewriter,
        intent=_knife_intent(knife),
        occasion=occasion,
        amount_path=amount_path,
    )
    if spoken is None:
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, "rewrite", "evaluate")
        )
    unfit = _realize_eval(
        f"one-eval-{seed:04d}",
        spoken,
        knifed,
        s0,
        occasion,
        ("evaluate_unfit", knife),
        persona,
        last_meal=last_meal,
    )
    if isinstance(unfit, GenerateOneResult):
        return unfit
    if unfit.oracle.last_verdict != "reject":
        return GenerateOneResult(
            accepted=None, rejected=Rejected(spoken, "knife", "evaluate")
        )
    return GenerateOneResult(accepted=unfit, rejected=None)


def _retag(task: Task, situations: tuple[str, ...], persona: str) -> Task:
    return Task(
        task.id, task.family, task.query, task.s0, task.oracle, situations, persona
    )


def _realize_eval(
    task_id: str,
    query: str,
    items: Sequence[Mapping[str, object]],
    s0: WorldState,
    occasion: str,
    situations: tuple[str, ...],
    persona: str,
    *,
    last_meal: bool,
) -> Task | GenerateOneResult:
    meal = [
        {"food_id": str(item["food_id"]), "grams": float(item["grams"])}
        for item in items
    ]
    try:
        task = realize_evaluate(
            task_id=task_id,
            query=query,
            items=meal,
            s0=s0,
            occasion=occasion,
            last_meal=last_meal,
        )
    except ValueError:
        return GenerateOneResult(
            accepted=None, rejected=Rejected(query, "empty_windows", "evaluate")
        )
    return Task(
        task.id,
        task.family,
        task.query,
        task.s0,
        task.oracle,
        situations,
        persona,
    )


def _knife_intent(knife: str) -> str:
    return {
        "allergy": "include the allergen",
        "over_slot": "bigger",
        "under_slot": "smaller",
        "swap": "swap",
    }.get(knife, knife)


def _rewrite_unfit(
    items: Sequence[Mapping[str, object]],
    rewriter: Callable[..., object] | None,
    *,
    intent: str,
    occasion: str,
    amount_path: str,
) -> str | None:
    if rewriter is None:
        return None
    raw = rewriter(
        items, intent=intent, occasion=occasion, amount_path=amount_path
    )
    payload = parse_query_foods_payload(raw)
    if payload is None:
        return None
    expected = [str(item["food_id"]) for item in items]
    if list(payload["foods"]) != expected:
        return None
    return str(payload["query"])


def build_unfit_rewrite_prompt(
    items: Sequence[Mapping[str, object]],
    *,
    intent: str,
    occasion: str,
    catalog: Mapping | None = None,
) -> str:
    """Second-pass speech only: code-chosen foods and amounts, no window numbers."""
    foods = catalog or {}
    lines = [
        "Rewrite one user query that names this exact plate as a meal to evaluate.",
        f"Intent: {intent}. Occasion: {occasion}.",
        "Speak the code-chosen foods and amounts. JSON foods must match this id list.",
        "Do not mention remaining budget, nutrient targets, or allergy codes.",
        "Return exactly {\"query\":\"...\",\"foods\":[\"<id>\", ...]} and nothing else.",
        "Plate:",
    ]
    ids: list[str] = []
    for item in items:
        food_id = str(item["food_id"])
        grams = float(item["grams"])
        ids.append(food_id)
        spoken = _spoken_names(food_id, foods)
        name = spoken[1] if len(spoken) > 1 else spoken[0]
        lines.append(f"- id={food_id} spoken={name} amount={grams:g} g")
    lines.append("foods: " + ", ".join(ids))
    return "\n".join(lines)


def build_stage_a_prompt(
    items: Sequence[Mapping[str, object]], catalog: Mapping | None = None
) -> str:
    """Stage A voter: food+grams only. Eatable plate, not wisdom."""
    foods = catalog or {}
    lines = [
        "Here is a plate listed as food and grams.",
        "Could one person eat this at one meal? Large plates are allowed.",
        "Vote whether the plate is eatable, not whether it is wise or healthy.",
        "Do not judge whether the gram amounts are the table-correct portion fact.",
        "Do not see a user query. Do not see nutrient windows.",
        "Plate:",
    ]
    for item in items:
        food_id = str(item["food_id"])
        grams = float(item["grams"])
        spoken = _spoken_names(food_id, foods)
        name = spoken[1] if len(spoken) > 1 else spoken[0]
        lines.append(f"- {name}: {grams:g} g")
    return "\n".join(lines)


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


class UnfitRewriter:
    """Second Evaluate speech pass. Prompt has foods and amounts, not windows."""

    def __init__(
        self,
        *,
        complete: Callable[[str, Sequence[Mapping[str, str]]], str],
        catalog: Mapping,
        parse_retries: int = 1,
    ) -> None:
        self._complete = complete
        self._catalog = catalog
        self._parse_retries = max(0, int(parse_retries))

    def __call__(
        self,
        items: Sequence[Mapping[str, object]],
        *,
        intent: str,
        occasion: str,
        amount_path: str | None = None,
    ) -> dict[str, object]:
        messages = (
            {
                "role": "system",
                "content": build_unfit_rewrite_prompt(
                    items, intent=intent, occasion=occasion, catalog=self._catalog
                ),
            },
            {
                "role": "user",
                "content": "Write the evaluate query for this plate. JSON only.",
            },
        )
        last: dict[str, object] = {"query": "", "foods": []}
        for _attempt in range(1 + self._parse_retries):
            parsed = parse_query_foods_payload(
                self._complete("evaluate-rewrite", messages)
            )
            if parsed is not None:
                return parsed
        return last


def make_unfit_rewriter(
    *,
    complete: Callable[[str, Sequence[Mapping[str, str]]], str],
    catalog: Mapping,
    parse_retries: int = 1,
) -> UnfitRewriter:
    """Build the unfit speech rewriter. complete is injected; no live API required."""
    return UnfitRewriter(
        complete=complete, catalog=catalog, parse_retries=parse_retries
    )


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
