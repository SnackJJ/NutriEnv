"""Harness protocol: observations in, one Env action out.

The Runner is the only place Env, Harness, and Model meet (ADR 0005).
A harness may reshape text; it must not score, change gates, or touch Oracle.
The Runner enforces that restriction: ``reset`` receives a :class:`HarnessView`
with no oracle and no S0 unless ``run_split(..., leak_oracle=True)``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Harness", "HarnessView"]


@dataclass(frozen=True)
class HarnessView:
    """What a harness may see in ``reset``: identity and the query, nothing else."""

    id: str
    family: str
    persona: str
    situations: tuple[str, ...]
    query: str


class Harness:
    """Presentation loop. Subclasses emit a single legal Env action dict."""

    def act(self, observation: dict, query: str, history: list) -> dict:
        """Return the next Env action for this observation."""
        raise NotImplementedError

    def set_step_budget(self, max_steps: int) -> None:
        """Receive the episode's step budget. The Runner owns the bound, so it hands it over.

        A harness that renders the budget into a prompt must render the number the loop will
        actually use; a constructor default cannot express that, because the bound depends on
        the Task's family. Override to store it (`ReActHarness`), to forward it
        (`BuddyHarness`), or as an explicit no-op if this harness builds no prompt
        (`ScriptHarness`). The default raises so a new harness cannot silently keep a budget
        the exam is not running with.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement set_step_budget: store the budget, or opt "
            "out explicitly if it builds no prompt"
        )

    def clone(self) -> "Harness":
        """Episode-local copy. Override if this instance holds chat state."""
        return self
