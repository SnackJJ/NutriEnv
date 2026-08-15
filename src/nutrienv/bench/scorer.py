"""Binary hand-in scorer for generated benchmark tasks."""

from __future__ import annotations

import math

from nutrienv.world.types import LedgerRow, Profile, WorldState, normalize_tags

from .generator import Oracle

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

        if (
            oracle.last_plan is not None
            or oracle.plan_must_be_safe
            or oracle.plan_must_fit_windows
        ):
            plan_error = self._score_plan(end_state, oracle)
            if plan_error is not None:
                return self._fail(plan_error)

        # Profile equality also protects recommend/evaluate constraints from an
        # agent that tries to make its own plan pass by weakening the profile.
        if oracle.profile is not None and end_state.profile != oracle.profile:
            return self._fail("update_miss")

        if oracle.ledger_tail is not None:
            expected = oracle.ledger_tail
            if not isinstance(expected, list) or not all(
                isinstance(row, LedgerRow) for row in expected
            ):
                return self._fail("log_miss")
            if not expected or len(end_state.ledger) < len(expected):
                return self._fail("log_miss")
            if end_state.ledger[-len(expected) :] != expected:
                return self._fail("log_miss")

        if oracle.ledger is not None and tuple(end_state.ledger) != oracle.ledger:
            return self._fail("log_miss")

        return _ScoreResult(passed=True, tag="pass")

    @staticmethod
    def _fail(tag: str) -> dict:
        return _ScoreResult(passed=False, tag=tag)

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
        if oracle.last_plan and items != oracle.last_plan:
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
