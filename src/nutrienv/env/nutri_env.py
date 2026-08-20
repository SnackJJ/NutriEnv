"""The steppable world: load S0, step Actions, expose observations.

Env is the same machine on every Task (ADR 0003). It holds no Task knowledge,
invents no recommendations, and never scores. Semantic quality — nutrient
windows, allergen intersection, extra or missing field writes — is Bench's job
at hand-in, so no Action is ever rejected for being a bad idea.
"""

from __future__ import annotations

import copy

from ..actions.dispatch import DEFAULT_EATEN_AT, dispatch
from ..actions.schemas import ActionError
from ..world.types import WorldState, ledger_totals, ledger_view, profile_view

__all__ = ["NutriEnv"]


class NutriEnv:
    """One episode's world.

    ``default_eaten_at`` is the ``eaten_at`` stamped on a ``log_meal`` that
    omits one. It is a fixed string rather than a clock so an episode replays
    identically and an Oracle can name the expected ledger row.
    """

    def __init__(self, *, default_eaten_at: str = DEFAULT_EATEN_AT) -> None:
        self._state: WorldState | None = None
        self._default_eaten_at = default_eaten_at

    def reset(self, s0: WorldState) -> dict:
        """Load a start world and return the opening observation.

        The Generator's ``s0`` is copied, not adopted, so the caller keeps a
        pristine S0 to build its Oracle against.

        ``catalog_size`` is published. Individual ids are found with
        ``search_foods``; a USDA-scale catalog is not dumped into the opening
        observation.
        """
        if not isinstance(s0, WorldState):
            raise TypeError(f"reset expects a WorldState, got {type(s0).__name__}")
        self._state = copy.deepcopy(s0)
        return {
            "op": "reset",
            "profile": profile_view(self._state.profile),
            "ledger": ledger_view(self._state.ledger, self._state.catalog),
            "ledger_totals": ledger_totals(self._state.ledger, self._state.catalog),
            "last_plan": copy.deepcopy(self._state.last_plan),
            "last_verdict": self._state.last_verdict,
            "last_reasons": list(self._state.last_reasons),
            "catalog_size": len(self._state.catalog),
        }

    def step(self, action: dict) -> dict:
        """Apply one Action.

        Returns ``{ok, observation, error?, done}``. An Illegal Action returns
        ``ok=False`` with the world unchanged; the episode continues.
        """
        state = self._require_state()
        try:
            observation = dispatch(
                state, action, default_eaten_at=self._default_eaten_at
            )
        except ActionError as exc:
            return {
                "ok": False,
                "observation": None,
                "error": exc.as_dict(),
                "done": False,
            }
        return {"ok": True, "observation": observation, "done": False}

    def state(self) -> WorldState:
        """The live end state, for the scorer. Read it; do not mutate it."""
        return self._require_state()

    def _require_state(self) -> WorldState:
        if self._state is None:
            raise RuntimeError("reset(s0) must be called before step/state")
        return self._state
