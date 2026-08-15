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

    def clone(self) -> "Harness":
        """Episode-local copy. Override if this instance holds chat state."""
        return self
