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
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, Profile, WorldState, ledger_totals, normalize_tags

from .realizations import FUZZY_ROWS, LEFTOVER_ROWS
from .situations import SITUATIONS, Situation

__all__ = ["Oracle", "Task", "Generator"]


FAMILIES = ("lookup", "log", "recommend", "evaluate", "update", "constrain")
PERSONAS = ("everyday", "cut", "gym", "leftover", "flex", "htn")
_NUTRIENTS = ("kcal", "protein_g", "carb_g", "fat_g", "fiber_g", "sodium_mg")
_SAFE_PLAN = (
    ("chicken_breast", 200.0),
    ("white_rice", 300.0),
    ("broccoli", 150.0),
    ("olive_oil", 20.0),
)


_SITUATION_FAMILY = {
    "fuzzy_portion": "log",
    "multi_item_log": "log",
    "condition_suitability": "constrain",
    "unit_convert": "log",
    "near_synonym": "log",
    "conflict_windows": "constrain",
    "ledger_gap": "log",
}


@dataclass(frozen=True)
class Oracle:
    """The query-scoped portion of the expected end state.

    ``last_plan=[]`` is the marker for a free recommendation: the submitted
    plan may contain any catalog items, provided it is non-empty, allergen-safe,
    and inside every judged window.  A non-empty value is the exact plan named
    by an evaluate task.  ``None`` means plans are not judged.

    ``plan_windows``, when set, is what the submitted plan is checked against.
    Use it when the agent reads daily windows on the profile but the meal must
    fit the remainder after the ledger.  Profile equality still uses ``profile``.
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
    plan_windows: dict[str, tuple[float, float]] | None = None


@dataclass(frozen=True)
class Task:
    id: str
    family: str
    query: str
    s0: WorldState
    oracle: Oracle
    situations: tuple[str, ...] = ()
    persona: str = "everyday"


class Generator:
    """Generate deterministic tasks from an isolated ``random.Random``."""

    def sample(
        self,
        seed: int,
        family: str | None = None,
        difficulty: dict | None = None,
        situation: str | Situation | None = None,
        *,
        persona: str = "everyday",
    ) -> Task:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an int")
        rng = random.Random(seed)
        situation_name = self._situation_name(situation)
        if persona not in PERSONAS:
            raise ValueError(f"unknown persona {persona!r}; expected one of {PERSONAS}")
        if persona not in {"everyday", "leftover"}:
            raise ValueError(f"persona {persona!r} is not implemented in the factory yet")
        if situation_name is not None:
            expected_family = _SITUATION_FAMILY[situation_name]
            if family is not None and family != expected_family:
                raise ValueError(
                    f"situation {situation_name!r} requires family {expected_family!r}"
                )
            family = expected_family
        if persona == "leftover":
            if family is not None and family != "recommend":
                raise ValueError("persona 'leftover' requires family 'recommend'")
            family = "recommend"
        elif family is None:
            family = rng.choice(FAMILIES)
        if family not in FAMILIES:
            raise ValueError(f"unknown family {family!r}; expected one of {FAMILIES}")
        knobs = self._difficulty(difficulty)
        s0 = self._make_s0(seed, knobs)
        if situation_name is None and family == "recommend":
            query, oracle = self._build_recommend(rng, s0, knobs, persona=persona)
        else:
            builder = getattr(
                self,
                f"_build_situation_{situation_name}" if situation_name else f"_build_{family}",
            )
            query, oracle = builder(rng, s0, knobs)
        label = f"{family}-{situation_name}" if situation_name else family
        if persona != "everyday":
            label = f"{label}-{persona}"
        task_id = f"v1-{label}-{seed & ((1 << 64) - 1):016x}"
        tags = (situation_name,) if situation_name else ()
        return Task(task_id, family, query, s0, oracle, tags, persona)

    def generate(
        self,
        seed: int,
        family: str | None = None,
        difficulty: dict | None = None,
        situation: str | Situation | None = None,
        *,
        persona: str = "everyday",
    ) -> Task:
        """Compatibility alias for :meth:`sample`."""
        return self.sample(
            seed,
            family=family,
            difficulty=difficulty,
            situation=situation,
            persona=persona,
        )

    def generate_split(
        self,
        seed: int,
        n: int,
        situation: str | Situation | None = None,
        *,
        persona: str = "everyday",
    ) -> list[Task]:
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError("n must be a non-negative int")
        # Cycling guarantees family coverage in ordinary splits; the seeded
        # shuffle prevents a fixed family order from becoming a shortcut.
        situation_name = self._situation_name(situation)
        if persona == "leftover":
            if situation_name is not None:
                raise ValueError("persona 'leftover' cannot pair with a situation")
            return [
                self.sample(seed + index, family="recommend", persona="leftover")
                for index in range(n)
            ]
        if situation_name is not None:
            return [
                self.sample(seed + index, situation=situation_name, persona=persona)
                for index in range(n)
            ]
        rng = random.Random(seed)
        order = list(FAMILIES)
        rng.shuffle(order)
        return [
            self.sample(
                seed + index, family=order[index % len(order)], persona=persona
            )
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

    @classmethod
    def _plan_items(cls, s0: WorldState) -> list[dict]:
        return [
            {"food_id": cls._food_id(s0, food_id), "grams": grams}
            for food_id, grams in _SAFE_PLAN
        ]

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

    @staticmethod
    def _food_id(s0: WorldState, food_id: str) -> str:
        resolver = getattr(s0.catalog, "canonical_id", None)
        if callable(resolver) and food_id in s0.catalog:
            return resolver(food_id)
        return food_id

    @classmethod
    def _log_oracle(cls, s0: WorldState, tail: list[LedgerRow]) -> Oracle:
        canon = [
            LedgerRow(cls._food_id(s0, row.food_id), row.grams, row.eaten_at)
            for row in tail
        ]
        return Oracle(
            profile=copy.deepcopy(s0.profile),
            ledger_tail=canon,
            ledger=(*s0.ledger, *canon),
        )

    @staticmethod
    def _seed_eaten_at(s0: WorldState, *slots: str) -> None:
        rows = list(s0.ledger)
        present = {row.eaten_at for row in rows}
        if "yesterday-snack" not in present:
            rows.insert(0, LedgerRow("banana", 100.0, "yesterday-snack"))
            present.add("yesterday-snack")
        for slot in slots:
            if slot not in present:
                rows.append(LedgerRow("oats", 60.0, slot))
                present.add(slot)
        s0.ledger = rows

    @staticmethod
    def _remainder_windows(s0: WorldState) -> dict[str, tuple[float, float]]:
        eaten = ledger_totals(s0.ledger, s0.catalog)
        remain: dict[str, tuple[float, float]] = {}
        for key, (lo, hi) in s0.profile.windows.items():
            used = eaten.get(key, 0.0)
            remain[key] = (round(max(0.0, lo - used), 2), round(max(0.0, hi - used), 2))
        return remain

    @staticmethod
    def _require_portion(food_id: str, phrase: str, catalog: dict) -> float:
        grams = resolve_portion(food_id, phrase, catalog)
        if grams is None:
            raise RuntimeError(f"catalog cannot resolve {phrase!r} for {food_id}")
        return grams

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
        slots = tuple(f"today-meal-{i + 1}" for i in range(count))
        self._seed_eaten_at(s0, *slots)
        rows = [
            LedgerRow(
                choices[(rng.randrange(len(choices)) + i) % len(choices)],
                float(50 + 25 * i),
                slots[i],
            )
            for i in range(count)
        ]
        details = "; ".join(
            f"{row.grams:g} g of {row.food_id} at {row.eaten_at}" for row in rows
        )
        return f"Log these missing ledger entries: {details}.", self._log_oracle(s0, rows)

    def _build_recommend(
        self,
        rng: random.Random,
        s0: WorldState,
        knobs: dict,
        persona: str = "everyday",
    ) -> tuple[str, Oracle]:
        if persona == "leftover":
            return self._build_leftover_recommend(rng, s0)
        profile = self._profile_for_plan(s0, knobs["n_constraints"])
        s0.profile = profile
        query = (
            "Submit a non-empty food plan that avoids all profile allergies and "
            "falls within every profile nutrient window."
        )
        return query, Oracle(
            profile=copy.deepcopy(profile),
            last_plan=[],
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
            ledger=tuple(s0.ledger),
        )

    def _build_leftover_recommend(
        self, rng: random.Random, s0: WorldState
    ) -> tuple[str, Oracle]:
        row = LEFTOVER_ROWS[rng.randrange(len(LEFTOVER_ROWS))]
        s0.profile = replace(
            s0.profile,
            windows=dict(row.windows),
            allergies=row.allergies or s0.profile.allergies,
        )
        s0.ledger = [
            LedgerRow(self._food_id(s0, food_id), grams, eaten_at)
            for food_id, grams, eaten_at in row.ledger
            if food_id in s0.catalog
        ]
        return row.query, Oracle(
            profile=copy.deepcopy(s0.profile),
            last_plan=[],
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
            plan_windows=self._remainder_windows(s0),
            ledger=tuple(s0.ledger),
        )

    def _build_evaluate(self, rng: random.Random, s0: WorldState, knobs: dict) -> tuple[str, Oracle]:
        profile = self._profile_for_plan(s0, knobs["n_constraints"])
        s0.profile = profile
        items = self._plan_items(s0)
        text = ", ".join(f"{x['grams']:g} g {x['food_id']}" for x in items)
        query = f"Evaluate this candidate by submitting it as the plan: {text}."
        return query, Oracle(
            profile=copy.deepcopy(profile),
            last_plan=items,
            plan_must_fit_windows=True,
            ledger=tuple(s0.ledger),
        )

    def _build_update(self, rng: random.Random, s0: WorldState, knobs: dict) -> tuple[str, Oracle]:
        lo, hi = s0.profile.windows.get("kcal", (1800.0, 2200.0))
        kcal = (float(lo) + 200.0, float(hi) + 200.0)
        allergies = normalize_tags([*s0.profile.allergies, " SHELLFISH ", "shellfish"])
        windows = dict(s0.profile.windows)
        windows["kcal"] = kcal
        expected = replace(
            s0.profile,
            allergies=allergies,
            windows=windows,
        )
        query = (
            "I've been tired. Update my profile now: add shellfish to my allergies "
            f"(I reacted to shrimp) and raise my kcal window to {kcal[0]:g}-{kcal[1]:g}. "
            "Leave every other field unchanged."
        )
        return query, Oracle(profile=expected, ledger=tuple(s0.ledger))

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
        spec = FUZZY_ROWS[rng.randrange(len(FUZZY_ROWS))]
        grams = self._require_portion(spec.food_id, spec.phrase, s0.catalog)
        self._seed_eaten_at(s0, spec.slot)
        row = LedgerRow(spec.food_id, grams, spec.slot)
        return spec.utterance, self._log_oracle(s0, [row])

    def _build_situation_multi_item_log(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        self._seed_eaten_at(s0, "today-breakfast")
        rows = [
            LedgerRow("oats", 60.0, "today-breakfast"),
            LedgerRow("banana", 110.0, "today-breakfast"),
            LedgerRow("greek_yogurt", 150.0, "today-breakfast"),
        ]
        query = (
            "Log all three breakfast items: 60 g rolled oats, 110 g banana, and "
            "150 g plain Greek yogurt, each at today-breakfast."
        )
        return query, self._log_oracle(s0, rows)

    def _build_situation_condition_suitability(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        # Shrimp carries shellfish in the fixture, so the collision is wholly
        # represented by S0 rather than hidden in prose.
        profile = replace(
            s0.profile,
            allergies=normalize_tags(["shellfish"]),
            windows={"kcal": (400.0, 800.0), "protein_g": (20.0, 50.0)},
        )
        s0.profile = profile
        query = (
            "I was thinking of having shrimp tonight. Is that okay for me, or "
            "what should I have instead?"
        )
        return query, Oracle(
            profile=copy.deepcopy(profile),
            last_plan=[],
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
            allow_empty_plan=False,
            ledger=tuple(s0.ledger),
        )

    def _build_situation_unit_convert(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        grams = self._require_portion("oats", "2 ounces", s0.catalog)
        self._seed_eaten_at(s0, "today-snack")
        row = LedgerRow("oats", grams, "today-snack")
        query = "Snack was about 2 ounces of oats. Log it for me."
        return query, self._log_oracle(s0, [row])

    def _build_situation_near_synonym(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        self._seed_eaten_at(s0, "today-dinner")
        row = LedgerRow("shrimp", 150.0, "today-dinner")
        query = "Log the prawns I had for dinner — about 150 grams."
        return query, self._log_oracle(s0, [row])

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
        s0.last_plan = [{"food_id": "chicken_breast", "grams": 200.0}]
        query = (
            "Can you make a day of eating that hits my protein target without "
            "going over calories?"
        )
        return query, Oracle(
            profile=copy.deepcopy(profile),
            last_plan=None,
            plan_must_fit_windows=True,
            allow_empty_plan=True,
            ledger=tuple(s0.ledger),
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
        return query, self._log_oracle(s0, [missing])
