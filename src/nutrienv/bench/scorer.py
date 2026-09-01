"""Binary hand-in scorer for generated benchmark tasks."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace

from nutrienv.world.daily_windows import (
    BAND_WINDOW_KEYS,
    estimated_energy_requirement,
    implicit_windows_pass,
)
from nutrienv.world.types import LedgerRow, Profile, WorldState, normalize_tags

from .portion_table import matches_portion_table
from .realize import Oracle, scored_oracles

__all__ = ["Scorer"]


class _ScoreResult(dict):
    """A mapping with read-only legacy attributes for early integration tests."""

    @property
    def passed(self) -> bool:
        return self["passed"]

    @property
    def tag(self) -> str | None:
        return None if self["tag"] == "pass" else self["tag"]

    @property
    def tags(self) -> tuple[str, ...]:
        return () if self["tag"] == "pass" else (self["tag"],)


class Scorer:
    """Score only the finished world; Env remains free of semantic policy."""

    def score(self, end_state: WorldState, oracle: Oracle) -> dict:
        if not isinstance(end_state, WorldState):
            raise TypeError("end_state must be a WorldState")
        if not isinstance(oracle, Oracle):
            raise TypeError("oracle must be an Oracle")

        if oracle.sub_oracles:
            return self._score_composite(end_state, oracle)
        return self._score_one(end_state, oracle)

    def _score_composite(self, end_state: WorldState, oracle: Oracle) -> dict:
        sub_tags: list[str] = []
        first_fail: str | None = None
        for sub in scored_oracles(oracle):
            result = self._score_one(end_state, sub)
            tag = result["tag"]
            sub_tags.append(tag)
            if tag != "pass" and first_fail is None:
                first_fail = tag
        if first_fail is None:
            return _ScoreResult(passed=True, tag="pass", sub_tags=tuple(sub_tags))
        return _ScoreResult(passed=False, tag=first_fail, sub_tags=tuple(sub_tags))

    def _score_one(self, end_state: WorldState, oracle: Oracle) -> dict:
        if oracle.last_verdict is not None:
            verdict_error = self._score_verdict(end_state, oracle)
            if verdict_error is not None:
                return self._fail(verdict_error)
        if oracle.last_verdict != "reject" and (
            oracle.last_plan is not None
            or oracle.plan_must_be_safe
            or oracle.plan_must_fit_windows
        ):
            plan_error = self._score_plan(end_state, oracle)
            if plan_error is not None:
                return self._fail(plan_error)

        # Profile equality also protects recommend/evaluate constraints from an
        # agent that tries to make its own plan pass by weakening the profile.
        if oracle.profile is not None:
            if oracle.update_band:
                if not self._implicit_update_ok(end_state.profile, oracle):
                    return self._fail("update_miss")
            elif end_state.profile != oracle.profile:
                return self._fail("update_miss")

        if oracle.ledger_tail is not None:
            expected = oracle.ledger_tail
            if not isinstance(expected, list) or not all(
                isinstance(row, LedgerRow) for row in expected
            ):
                return self._fail("log_miss")
            if not expected or len(end_state.ledger) < len(expected):
                return self._fail("log_miss")
            if not self._match_ledger_multiset(
                end_state.ledger[-len(expected) :], expected, end_state.catalog
            ):
                return self._fail("log_miss")

        if oracle.ledger is not None:
            if not self._match_ledger_multiset(
                end_state.ledger, oracle.ledger, end_state.catalog
            ):
                return self._fail("log_miss")

        return _ScoreResult(passed=True, tag="pass")

    @staticmethod
    def _ledger_row_matches(
        got: LedgerRow, exp: LedgerRow, catalog: Mapping[str, dict] | None
    ) -> bool:
        if got.food_id != exp.food_id:
            return False
        # Meal slot compatibility: exact match or default 'now'
        if got.eaten_at != exp.eaten_at and got.eaten_at != "now" and exp.eaten_at != "now":
            return False
        if math.isclose(got.grams, exp.grams, rel_tol=1e-5):
            return True
        # ADR 0023 discrete portion tolerance
        if 0.85 * exp.grams - 1e-5 <= got.grams <= 1.15 * exp.grams + 1e-5:
            if catalog and matches_portion_table(exp.food_id, got.grams, catalog):
                return True
        return False

    @classmethod
    def _match_ledger_multiset(
        cls,
        got_rows: list[LedgerRow] | tuple[LedgerRow, ...],
        expected_rows: list[LedgerRow] | tuple[LedgerRow, ...],
        catalog: Mapping[str, dict] | None,
    ) -> bool:
        if len(got_rows) != len(expected_rows):
            return False
        if Counter(got_rows) == Counter(expected_rows):
            return True
        n = len(expected_rows)
        used = [False] * n

        def dfs(i: int) -> bool:
            if i == len(got_rows):
                return True
            for j in range(n):
                if not used[j] and cls._ledger_row_matches(got_rows[i], expected_rows[j], catalog):
                    used[j] = True
                    if dfs(i + 1):
                        return True
                    used[j] = False
            return False

        return dfs(0)

    @staticmethod
    def _fail(tag: str) -> dict:
        return _ScoreResult(passed=False, tag=tag)

    @staticmethod
    def _implicit_update_ok(end: Profile, oracle: Oracle) -> bool:
        expected = oracle.profile
        if expected is None:
            return False
        # phase is a means, not the verdict: the handbook offers both a phase
        # patch and a direct window move, and ADR 0015 scores where the windows
        # landed. A wrong phase still fails below, because Env derives its
        # windows and they miss the band.
        if replace(end, windows=expected.windows, phase=expected.phase) != expected:
            return False
        band_keys = BAND_WINDOW_KEYS.get(oracle.update_band or "", frozenset())
        for key, bounds in expected.windows.items():
            if key in band_keys:
                continue
            if end.windows.get(key) != bounds:
                return False
        for key in end.windows:
            if key not in band_keys and key not in expected.windows:
                return False
        if (
            expected.sex is None
            or expected.age_y is None
            or expected.height_cm is None
            or expected.weight_kg is None
            or expected.activity is None
        ):
            return False
        eer = estimated_energy_requirement(
            sex=expected.sex,
            age_y=expected.age_y,
            height_cm=expected.height_cm,
            weight_kg=expected.weight_kg,
            activity=expected.activity,
        )
        # A band oracle carries S0's windows unchanged (split.py enforces it),
        # so expected.windows is the S0 baseline fatigue must rise above.
        return implicit_windows_pass(
            oracle.update_band or "",
            end.windows,
            eer=eer,
            weight_kg=expected.weight_kg,
            s0_windows=expected.windows,
        )

    @classmethod
    def _plan_item_matches(
        cls, got: dict, exp: dict, catalog: Mapping[str, dict] | None
    ) -> bool:
        if got.get("food_id") != exp.get("food_id"):
            return False
        got_g = got.get("grams", 0.0)
        exp_g = exp.get("grams", 0.0)
        if not (isinstance(got_g, (int, float)) and isinstance(exp_g, (int, float))):
            return False
        if math.isclose(got_g, exp_g, rel_tol=1e-5):
            return True
        if catalog and matches_portion_table(exp["food_id"], got_g, catalog):
            return True
        return False

    @classmethod
    def _match_plan_items(
        cls, got_items: list[dict], exp_items: list[dict], catalog: Mapping[str, dict] | None
    ) -> bool:
        if len(got_items) != len(exp_items):
            return False
        n = len(exp_items)
        used = [False] * n

        def dfs(i: int) -> bool:
            if i == len(got_items):
                return True
            for j in range(n):
                if not used[j] and cls._plan_item_matches(got_items[i], exp_items[j], catalog):
                    used[j] = True
                    if dfs(i + 1):
                        return True
                    used[j] = False
            return False

        return dfs(0)

    def _score_verdict(self, state: WorldState, oracle: Oracle) -> str | None:
        if oracle.last_verdict == "accept":
            if state.last_verdict != "accept":
                return "wrong_goal"
            if not isinstance(state.last_plan, list) or not isinstance(oracle.last_plan, list):
                return "wrong_goal"
            if not self._match_plan_items(state.last_plan, oracle.last_plan, state.catalog):
                return "wrong_goal"
            return None
        if oracle.last_verdict == "reject":
            if state.last_verdict != "reject":
                return "wrong_goal"
            if state.last_plan != []:
                return "wrong_goal"
            gold_reasons = set(oracle.last_reasons)
            got_reasons = set(state.last_reasons)
            if "allergy" in gold_reasons:
                if "allergy" not in got_reasons:
                    return "wrong_goal"
                return None
            if not gold_reasons.issubset(got_reasons) and got_reasons != gold_reasons:
                return "wrong_goal"
            return None
        return "wrong_goal"

    def _score_plan(self, state: WorldState, oracle: Oracle) -> str | None:
        items = state.last_plan
        if not isinstance(items, list) or not items:
            if oracle.allow_empty_plan and items == []:
                return None
            return "wrong_goal"

        allergens: set[str] = set()
        totals: dict[str, float] = {}
        for item in items:
            if not isinstance(item, dict) or set(item) != {"food_id", "grams"}:
                return "wrong_goal"
            food_id, grams = item["food_id"], item["grams"]
            if food_id not in state.catalog or not self._positive_finite(grams):
                return "wrong_goal"
            food = state.catalog[food_id]
            try:
                allergens.update(normalize_tags(food.get("allergen_tags", [])))
            except ValueError:
                return "wrong_goal"
            nutrients = food.get("nutrients")
            if not isinstance(nutrients, dict):
                return "wrong_goal"
            for key, amount in nutrients.items():
                if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount):
                    return "wrong_goal"
                totals[key] = totals.get(key, 0.0) + float(amount) * float(grams) / 100.0

        profile = oracle.profile if oracle.profile is not None else state.profile
        try:
            prohibited = set(normalize_tags(list(profile.allergies)))
        except ValueError:
            return "wrong_goal"
        if allergens & prohibited:
            return "allergy"

        if oracle.plan_must_fit_windows or oracle.plan_windows is not None:
            windows = (
                oracle.plan_windows if oracle.plan_windows is not None else profile.windows
            )
            for nutrient, window in windows.items():
                try:
                    lo, hi = window
                except (TypeError, ValueError):
                    return "wrong_goal"
                amount = totals.get(nutrient, 0.0)
                if amount < lo or amount > hi:
                    return "window"

        # Empty is the free-recommendation sentinel. Evaluate tasks carry a
        # non-empty exact candidate so submitting a different plan is a miss.
        if oracle.last_plan and not self._match_plan_items(items, oracle.last_plan, state.catalog):
            return "wrong_goal"
        return None

    @staticmethod
    def _positive_finite(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
        )
