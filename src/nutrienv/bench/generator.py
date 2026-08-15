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

from .realizations import (
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    FUZZY_ROWS,
    LEDGER_GAP_ROWS,
    LEFTOVER_ROWS,
    MULTI_ITEM_LOG_ROWS,
    NEAR_SYNONYM_ROWS,
    RECOMMEND_ROWS,
    UNIT_CONVERT_ROWS,
    UPDATE_ROWS,
    evaluate_windows,
)
from .situations import SITUATIONS, Situation

__all__ = ["Oracle", "Task", "Generator"]


FAMILIES = ("lookup", "log", "recommend", "evaluate", "update", "constrain")
PERSONAS = ("everyday", "cut", "gym", "leftover", "flex", "htn")
# Windows and presets for these live on recommend rows (leftover has its own
# table). Elsewhere the name is a label with no semantics behind it.
_RECOMMEND_ONLY_PERSONAS = frozenset({"cut", "gym", "leftover", "flex", "htn"})
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
        if situation_name is not None:
            expected_family = _SITUATION_FAMILY[situation_name]
            if family is not None and family != expected_family:
                raise ValueError(
                    f"situation {situation_name!r} requires family {expected_family!r}"
                )
            family = expected_family
        if persona in _RECOMMEND_ONLY_PERSONAS:
            if family is not None and family != "recommend":
                raise ValueError(f"persona {persona!r} requires family 'recommend'")
            family = "recommend"
        elif family is None:
            family = rng.choice(FAMILIES)
        if family not in FAMILIES:
            raise ValueError(f"unknown family {family!r}; expected one of {FAMILIES}")
        if situation_name is None and family == "constrain":
            picked = CONSTRAIN_ROWS[rng.randrange(len(CONSTRAIN_ROWS))]
            situation_name = (
                "condition_suitability" if picked.kind == "condition" else "conflict_windows"
            )
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
        if persona in _RECOMMEND_ONLY_PERSONAS:
            if situation_name is not None:
                raise ValueError(f"persona {persona!r} cannot pair with a situation")
            return [
                self.sample(seed + index, family="recommend", persona=persona)
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
        rows = [row for row in RECOMMEND_ROWS if row.persona == persona]
        if not rows:
            raise ValueError(f"no recommend rows for persona {persona!r}")
        return self._recommend_from_row(s0, rows[rng.randrange(len(rows))])

    def _recommend_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        extras: dict = {}
        if row.plan_preset is not None:
            extras["plan_preset"] = dict(row.plan_preset)
        s0.profile = replace(
            s0.profile,
            windows=dict(row.windows),
            allergies=normalize_tags(row.allergies),
            **extras,
        )
        s0.ledger = []
        s0.last_plan = []
        return row.query, Oracle(
            profile=copy.deepcopy(s0.profile),
            last_plan=[],
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
            ledger=tuple(s0.ledger),
        )

    def _build_leftover_recommend(
        self, rng: random.Random, s0: WorldState
    ) -> tuple[str, Oracle]:
        row = LEFTOVER_ROWS[rng.randrange(len(LEFTOVER_ROWS))]
        return self._leftover_from_row(s0, row)

    def _leftover_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        extras: dict = {}
        if row.plan_preset is not None:
            extras["plan_preset"] = dict(row.plan_preset)
        s0.profile = replace(
            s0.profile,
            windows=dict(row.windows),
            allergies=row.allergies or s0.profile.allergies,
            **extras,
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
        row = EVALUATE_ROWS[rng.randrange(len(EVALUATE_ROWS))]
        return self._evaluate_from_row(s0, row)

    def _evaluate_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        items = []
        for food_id, phrase in row.items:
            grams = self._require_portion(food_id, phrase, s0.catalog)
            items.append({"food_id": self._food_id(s0, food_id), "grams": grams})
        windows = evaluate_windows(
            items,
            s0.catalog,
            kcal_margin=row.margin_kcal,
            protein_margin=row.margin_protein,
        )
        colliding = set()
        for item in items:
            entry = s0.catalog.get(item["food_id"]) or {}
            colliding.update(entry.get("allergen_tags") or [])
        allergies = tuple(tag for tag in s0.profile.allergies if tag not in colliding)
        s0.profile = replace(s0.profile, windows=windows, allergies=allergies)
        return row.query, Oracle(
            profile=copy.deepcopy(s0.profile),
            last_plan=items,
            plan_must_fit_windows=True,
            ledger=tuple(s0.ledger),
        )

    def _build_update(self, rng: random.Random, s0: WorldState, knobs: dict) -> tuple[str, Oracle]:
        row = UPDATE_ROWS[rng.randrange(len(UPDATE_ROWS))]
        return self._update_from_row(s0, row)

    def _update_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        profile = s0.profile
        if row.s0_allergies is not None:
            profile = replace(profile, allergies=normalize_tags(row.s0_allergies))
        if row.s0_plan_preset is not None:
            profile = replace(profile, plan_preset=dict(row.s0_plan_preset))
        s0.profile = profile
        allergies = list(s0.profile.allergies)
        for tag in row.add_allergens:
            if tag not in allergies:
                allergies.append(tag)
        remove = set(row.remove_allergens)
        if remove:
            allergies = [tag for tag in allergies if tag not in remove]
        windows = dict(s0.profile.windows)
        for key, delta in (row.window_shifts or {}).items():
            lo, hi = windows.get(key, (0.0, 0.0))
            dlo, dhi = _shift_deltas(delta)
            windows[key] = (float(lo) + dlo, float(hi) + dhi)
        extras: dict = {}
        if row.set_plan_preset is not None:
            extras["plan_preset"] = dict(row.set_plan_preset)
        expected = replace(
            s0.profile,
            allergies=normalize_tags(allergies),
            windows=windows,
            **extras,
        )
        return row.query, Oracle(profile=expected, ledger=tuple(s0.ledger))

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
        row = MULTI_ITEM_LOG_ROWS[rng.randrange(len(MULTI_ITEM_LOG_ROWS))]
        return self._multi_item_from_row(s0, row)

    def _multi_item_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        s0.ledger = self._log_distractors(s0, row.slot)
        tail = [
            LedgerRow(
                food_id,
                self._require_portion(food_id, phrase, s0.catalog),
                row.slot,
            )
            for food_id, phrase in row.items
        ]
        return row.query, self._log_oracle(s0, tail)

    def _build_situation_condition_suitability(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        rows = [row for row in CONSTRAIN_ROWS if row.kind == "condition"]
        return self._condition_from_row(s0, rows[rng.randrange(len(rows))])

    def _condition_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        profile = replace(
            s0.profile,
            allergies=normalize_tags(row.allergies),
            windows=dict(row.windows),
        )
        s0.profile = profile
        return row.query, Oracle(
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
        row = UNIT_CONVERT_ROWS[rng.randrange(len(UNIT_CONVERT_ROWS))]
        return self._unit_convert_from_row(s0, row)

    def _unit_convert_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        grams = self._require_portion(row.food_id, row.phrase, s0.catalog)
        s0.ledger = self._log_distractors(s0, row.slot)
        return row.utterance, self._log_oracle(s0, [LedgerRow(row.food_id, grams, row.slot)])

    def _build_situation_near_synonym(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        row = NEAR_SYNONYM_ROWS[rng.randrange(len(NEAR_SYNONYM_ROWS))]
        return self._near_synonym_from_row(s0, row)

    def _near_synonym_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        grams = self._require_portion(row.food_id, row.phrase, s0.catalog)
        s0.ledger = self._log_distractors(s0, row.slot)
        return row.utterance, self._log_oracle(s0, [LedgerRow(row.food_id, grams, row.slot)])

    def _build_situation_conflict_windows(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        rows = [row for row in CONSTRAIN_ROWS if row.kind == "conflict"]
        return self._conflict_from_row(s0, rows[rng.randrange(len(rows))])

    def _conflict_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        profile = replace(
            s0.profile,
            windows=dict(row.windows),
            allergies=normalize_tags(row.allergies),
        )
        s0.profile = profile
        s0.last_plan = [
            {"food_id": self._food_id(s0, food_id), "grams": grams}
            for food_id, grams in row.last_plan
        ]
        return row.query, Oracle(
            profile=copy.deepcopy(profile),
            last_plan=None,
            plan_must_fit_windows=True,
            allow_empty_plan=True,
            ledger=tuple(s0.ledger),
        )

    def _build_situation_ledger_gap(
        self, rng: random.Random, s0: WorldState, knobs: dict
    ) -> tuple[str, Oracle]:
        row = LEDGER_GAP_ROWS[rng.randrange(len(LEDGER_GAP_ROWS))]
        return self._ledger_gap_from_row(s0, row)

    def _ledger_gap_from_row(self, s0: WorldState, row) -> tuple[str, Oracle]:
        s0.ledger = [
            LedgerRow(self._food_id(s0, food_id), grams, eaten_at)
            for food_id, grams, eaten_at in row.surround
            if food_id in s0.catalog
        ]
        food_id, phrase, slot = row.missing
        missing = LedgerRow(
            food_id,
            self._require_portion(food_id, phrase, s0.catalog),
            slot,
        )
        return row.query, self._log_oracle(s0, [missing])

    def _log_distractors(self, s0: WorldState, slot: str) -> list[LedgerRow]:
        return [
            LedgerRow(self._food_id(s0, "apple"), 182.0, "yesterday-snack"),
            LedgerRow(self._food_id(s0, "orange"), 131.0, slot),
        ]


def _shift_deltas(delta: float | tuple[float, float]) -> tuple[float, float]:
    if isinstance(delta, (tuple, list)):
        return (float(delta[0]), float(delta[1]))
    value = float(delta)
    return (value, value)
