"""Harness protocol: observations in, one Env action out.

The Runner is the only place Env, Harness, and Model meet (ADR 0005).
A harness may reshape text; it must not score, change gates, or touch Oracle.
"""

from __future__ import annotations

__all__ = ["Harness"]


class Harness:
    """Presentation loop. Subclasses emit a single legal Env action dict."""

    def act(self, observation: dict, query: str, history: list) -> dict:
        """Return the next Env action for this observation."""
        raise NotImplementedError

    def clone(self) -> "Harness":
        """Episode-local copy. Override if this instance holds chat state."""
        return self
