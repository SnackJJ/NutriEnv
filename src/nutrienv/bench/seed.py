"""Deterministic seeding for the Generator."""

from __future__ import annotations

import random

__all__ = ["make_rng"]


def make_rng(seed: int) -> random.Random:
    """Return an isolated PRNG. Same seed always yields the same stream."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    return random.Random(seed)
