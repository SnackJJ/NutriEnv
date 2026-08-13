"""Seeded task generation for the v1 benchmark.

The generator owns S0 and derives every oracle from that state and the query it
emits.  It deliberately uses only the local fixture catalog: generation never
depends on a clock, network service, or process-global random state.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, replace

from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.types import LedgerRow, Profile, WorldState, normalize_tags

from .situations import SITUATIONS, Situation

__all__ = ["Oracle", "Task", "Generator"]


FAMILIES = ("lookup", "log", "recommend", "evaluate", "update", "constrain")
_NUTRIENTS = ("kcal", "protein_g", "carb_g", "fat_g", "fiber_g", "sodium_mg")
_SAFE_PLAN = (
    ("chicken_breast", 200.0),
    ("white_rice", 300.0),
    ("broccoli", 150.0),
    ("olive_oil", 20.0),
)

# Deterministic household/unit conversions used only in emitted local tasks.
# Values name a fixture food and its gram equivalent.
PORTIONS = {
    "half a cup of milk": ("milk_whole", 122.0),
    "one cup of milk": ("milk_whole", 244.0),
}
UNIT_GRAMS = {"ounce": 28.35}

_SITUATION_FAMILY = {
    "fuzzy_portion": "log",
    "multi_item_log": "log",
    "condition_suitability": "constrain",
    "unit_convert": "log",
    "near_synonym": "lookup",
    "conflict_windows": "constrain",
    "ledger_gap": "log",
}


@dataclass(frozen=True)
class Oracle:
    """The query-scoped portion of the expected end state.

    ``last_plan=[]`` is the marker for a free recommendation: the submitted
    plan may contain any catalog items, provided it is non-empty, allergen-safe,
    and inside every oracle profile window.  A non-empty value is the exact
    plan named by an evaluate task.  ``None`` means plans are not judged.
    """

    profile: Profile | None = None
    last_plan: list | None = None
    ledger_tail: list | None = None
    # Compatibility with the initial integration seam. New code should use
    # ``ledger_tail`` and the last_plan sentinel documented above.
    ledger: tuple[LedgerRow, ...] | None = None
    plan_must_be_safe: bool = False
    plan_must_fit_windows: bool = False
    allow_empty_plan: bool = False


@dataclass(frozen=True)
class Task:
    id: str
    family: str
    query: str
    s0: WorldState
    oracle: Oracle
    situations: tuple[str, ...] = ()


class Generator:
    """Generate deterministic tasks from an isolated ``random.Random``."""

    def sample(
        self,
        seed: int,
        family: str | None = None,
        difficulty: dict | None = None,
        situation: str | Situation | None = None,
    ) -> Task:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an int")
        rng = random.Random(seed)
        situation_name = self._situation_name(situation)
        if situation_name is not None:
            expected_family = _SITUATION_FAMILY[situation_name]
            if family is not None and family != expected_family:
                raise ValueError(
                    f"situation {situation_name!r} requires family {expected_family!r}"
                )
            family = expected_family
        elif family is None:
            family = rng.choice(FAMILIES)
        if family not in FAMILIES:
            raise ValueError(f"unknown family {family!r}; expected one of {FAMILIES}")
        knobs = self._difficulty(difficulty)
        s0 = self._make_s0(seed, knobs)
        builder = getattr(
            self,
            f"_build_situation_{situation_name}" if situation_name else f"_build_{family}",
        )
        query, oracle = builder(rng, s0, knobs)
        label = f"{family}-{situation_name}" if situation_name else family
        task_id = f"v1-{label}-{seed & ((1 << 64) - 1):016x}"
        tags = (situation_name,) if situation_name else ()
        return Task(task_id, family, query, s0, oracle, tags)

    def generate(
        self,
        seed: int,
        family: str | None = None,
        difficulty: dict | None = None,
        situation: str | Situation | None = None,
    ) -> Task:
        """Compatibility alias for :meth:`sample`."""
        return self.sample(
            seed, family=family, difficulty=difficulty, situation=situation
        )

    def generate_split(
        self, seed: int, n: int, situation: str | Situation | None = None
    ) -> list[Task]:
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError("n must be a non-negative int")
        # Cycling guarantees family coverage in ordinary splits; the seeded
        # shuffle prevents a fixed family order from becoming a shortcut.
        situation_name = self._situation_name(situation)
        if situation_name is not None:
            return [
                self.sample(seed + index, situation=situation_name)
                for index in range(n)
            ]
        rng = random.Random(seed)
        order = list(FAMILIES)
        rng.shuffle(order)
        return [
            self.sample(seed + index, family=order[index % len(order)])
            for index in range(n)
        ]

    @staticmethod
    def _situation_name(value: str | Situation | None) -> str | None:
        if value is None:
            return None
        name = value.value if isinstance(value, Situation) else value
        if not isinstance(name, str) or name not in SITUATIONS:
            raise ValueError(f"unknown situation {value!r}; expected one of {SITUATIONS}")
        return name

    @staticmethod
    def _difficulty(value: dict | None) -> dict[str, int]:
        if value is None:
            value = {}
        if not isinstance(value, dict):
            raise TypeError("difficulty must be a dict")
        unknown = set(value) - {"n_constraints", "ledger_gaps", "name_ambiguity"}
        if unknown:
            raise ValueError(f"unknown difficulty knobs: {sorted(unknown)}")
        defaults = {"n_constraints": 2, "ledger_gaps": 1, "name_ambiguity": 0}
        for key, raw in value.items():
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                raise ValueError(f"{key} must be a non-negative int")
            defaults[key] = raw
        return defaults

    @staticmethod
    def _make_s0(seed: int, knobs: dict[str, int]) -> WorldState:
        base = demo_state()
        catalog = load_catalog()
        # Ambiguous aliases make resolution harder without hiding any action or
        # catalog entry.  The query still supplies enough detail to resolve it.
        distractors = ["oats", "whole_wheat_bread", "tofu", "greek_yogurt"]
        for food_id in distractors[: min(knobs["name_ambiguity"], len(distractors))]:
            catalog[food_id]["aliases"].append("rice")
        profile = replace(base.profile, user_id=f"bench-{seed}")
        prior = [
            LedgerRow("banana", 100.0 + i * 5.0, f"day-{i + 1}-breakfast")
            for i in range(knobs["ledger_gaps"])
        ]
        return WorldState(profile=profile, ledger=prior, catalog=catalog, last_plan=[])

    @staticmethod
    def _plan_items() -> list[dict]:
        return [{"food_id": food_id, "grams": grams} for food_id, grams in _SAFE_PLAN]

    @staticmethod
    def _profile_for_plan(s0: WorldState, n_constraints: int) -> Profile:
        totals = {key: 0.0 for key in _NUTRIENTS}
        for food_id, grams in _SAFE_PLAN:
            for key, amount in s0.catalog[food_id]["nutrients"].items():
                totals[key] += float(amount) * grams / 100.0
        count = min(n_constraints, len(_NUTRIENTS))
        windows = {}
        for key in _NUTRIENTS[:count]:
            margin = max(1.0, abs(totals[key]) * 0.05)
            windows[key] = (totals[key] - margin, totals[key] + margin)
        allergies = normalize_tags(["peanut", "shellfish"][: min(n_constraints, 2)])
        return replace(s0.profile, allergies=allergies, windows=windows)

    def _build_lookup(self, rng: random.Random, s0: WorldState, knobs: dict) -> tuple[str, Oracle]:
        food_id = rng.choice(sorted(s0.catalog))
        food = s0.catalog[food_id]
        query = (
            f"Look up {food['name']} (catalog id {food_id}) and report its kcal "
            "and protein_g per 100 g. Do not change my profile or ledger."
        )
        return query, Oracle()

    def _build_log(self, rng: random.Random, s0: WorldState, knobs: dict) -> tuple[str, Oracle]:
        count = max(1, knobs["ledger_gaps"])
        choices = ("white_rice", "oats", "greek_yogurt", "banana")
        rows = [
            LedgerRow(
                choices[(rng.randrange(len(choices)) + i) % len(choices)],
                float(50 + 25 * i),
                f"today-meal-{i + 1}",
            )
            for i in range(count)
        ]
        details = "; ".join(
            f"{row.grams:g} g of {row.food_id} at {row.eaten_at}" for row in rows
        )
        return f"Log these missing ledger entries: {details}.", Oracle(ledger_tail=rows)

    def _build_recommend(self, rng: random.Random, s0: WorldState, knobs: dict) -> tuple[str, Oracle]:
        profile = self._profile_for_plan(s0, knobs["n_constraints"])
        s0.profile = profile
        windows = ", ".join(f"{k} {lo:.1f}-{hi:.1f}" for k, (lo, hi) in profile.windows.items())
        query = (
            "Submit a non-empty food plan that avoids all profile allergies and "
            f"falls within every profile nutrient window ({windows or 'no numeric windows'})."
        )
        return query, Oracle(profile=copy.deepcopy(profile), last_plan=[])

    def _build_evaluate(self, rng: random.Random, s0: WorldState, knobs: dict) -> tuple[str, Oracle]:
        profile = self._profile_for_plan(s0, knobs["n_constraints"])
        s0.profile = profile
        items = self._plan_items()
        text = ", ".join(f"{x['grams']:g} g {x['food_id']}" for x in items)
        query = f"Evaluate this candidate by submitting it as the plan: {text}."
        return query, Oracle(profile=copy.deepcopy(profile), last_plan=items)

    def _build_update(self, rng: random.Random, s0: WorldState, knobs: dict) -> tuple[str, Oracle]:
        lo, hi = s0.profile.windows.get("kcal", (1800.0, 2200.0))
        kcal = (float(lo) + 200.0, float(hi) + 200.0)
        allergies = normalize_tags([*s0.profile.allergies, " SHRIMP ", "shrimp"])
        windows = dict(s0.profile.windows)
        windows["kcal"] = kcal
        expected = replace(
            s0.profile,
            allergies=allergies,
            windows=windows,
        )
        query = (
            "I've been tired. Update my profile now: add shrimp to my allergies and "
            f"raise my kcal window to {kcal[0]:g}-{kcal[1]:g}. Leave every other "
            "field unchanged."
        )
        return query, Oracle(profile=expected)

    def _build_constrain(self, rng: random.Random, s0: WorldState, knobs: dict) -> tuple[str, Oracle]:
        allergen = rng.choice(("peanut", "milk", "shellfish", "soy"))
        query = (
            f"Which catalog foods carry the {allergen} allergen tag? Answer the constraint "
            "question without changing my state."
        )
        return query, Oracle()

    def _build_situation_fuzzy_portion(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        phrase = "half a cup of milk"
        food_id, grams = PORTIONS[phrase]
        row = LedgerRow(food_id, grams, "today-breakfast")
        query = f"Log {phrase} at today-breakfast; use the standard portion conversion."
        return query, Oracle(ledger_tail=[row])

    def _build_situation_multi_item_log(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        rows = [
            LedgerRow("oats", 60.0, "today-breakfast"),
            LedgerRow("banana", 110.0, "today-breakfast"),
            LedgerRow("greek_yogurt", 150.0, "today-breakfast"),
        ]
        query = (
            "Log all three breakfast items: 60 g rolled oats, 110 g banana, and "
            "150 g plain Greek yogurt, each at today-breakfast."
        )
        return query, Oracle(ledger_tail=rows)

    def _build_situation_condition_suitability(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        # Shrimp carries shellfish in the fixture, so the collision is wholly
        # represented by S0 rather than hidden in prose.
        profile = replace(s0.profile, allergies=normalize_tags(["shellfish"]))
        s0.profile = profile
        query = (
            "I have a shellfish allergy. Is cooked shrimp suitable for me? Do not "
            "submit a plan containing an allergen; leaving the plan empty is valid."
        )
        return query, Oracle(
            profile=copy.deepcopy(profile),
            last_plan=None,
            plan_must_be_safe=True,
            allow_empty_plan=True,
        )

    def _build_situation_unit_convert(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        ounces = 2.0
        grams = ounces * UNIT_GRAMS["ounce"]
        row = LedgerRow("oats", grams, "today-snack")
        query = f"Log {ounces:g} ounces of rolled oats at today-snack, converted to grams."
        return query, Oracle(ledger_tail=[row])

    def _build_situation_near_synonym(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        query = (
            "Look up prawns in the local catalog and report kcal and protein_g per "
            "100 g. Resolve the near-synonym without changing my state."
        )
        return query, Oracle()

    def _build_situation_conflict_windows(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        # Protein cannot reach 100 g under 100 kcal with any non-negative mix
        # of the fixture foods. The expected safe response is no submitted plan.
        profile = replace(
            s0.profile,
            windows={"kcal": (0.0, 100.0), "protein_g": (100.0, 200.0)},
        )
        s0.profile = profile
        query = (
            "Can a catalog plan satisfy both at most 100 kcal and at least 100 g "
            "protein? These windows conflict; leave the plan empty rather than "
            "submit a violating plan."
        )
        return query, Oracle(
            profile=copy.deepcopy(profile),
            last_plan=None,
            plan_must_fit_windows=True,
            allow_empty_plan=True,
        )

    def _build_situation_ledger_gap(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        s0.ledger = [
            LedgerRow("banana", 100.0, "today-breakfast"),
            LedgerRow("white_rice", 200.0, "today-dinner"),
        ]
        missing = LedgerRow("chicken_breast", 150.0, "today-lunch")
        query = (
            "My ledger skips lunch between breakfast and dinner. Add the missing "
            "150 g chicken breast entry at today-lunch only."
        )
        return query, Oracle(ledger_tail=[missing])
