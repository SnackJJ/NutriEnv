"""Replay each Oracle through Env and report which items cannot be Passed.

This is the dynamic gate after freeze. ``validate_draft`` stays the static
draft-time gate. Callers pass a loaded split (not a path) and choose whether
to assert, print, or drop ids.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from nutrienv.env import NutriEnv

from .realize import Oracle, Task, scored_oracles
from .scorer import Scorer

__all__ = ["AchievabilityReport", "check_achievable"]


@dataclass(frozen=True)
class AchievabilityReport:
    unreachable: tuple[str, ...]


def check_achievable(tasks: Sequence[Task]) -> AchievabilityReport:
    """Replay each Task's Oracle via legal Env actions. Never asserts."""
    scorer = Scorer()
    unreachable: list[str] = []
    for task in tasks:
        if not _reachable(task, scorer):
            unreachable.append(task.id)
    return AchievabilityReport(unreachable=tuple(unreachable))


def _reachable(task: Task, scorer: Scorer) -> bool:
    env = NutriEnv()
    env.reset(task.s0)
    for oracle in scored_oracles(task.oracle):
        if not _replay_oracle(env, oracle):
            return False
    return scorer.score(env.state(), task.oracle)["passed"] is True


def _replay_oracle(env: NutriEnv, oracle: Oracle) -> bool:
    if oracle.ledger_tail:
        for row in oracle.ledger_tail:
            if row in env.state().ledger:
                continue
            stepped = env.step(
                {
                    "op": "log_meal",
                    "food_id": row.food_id,
                    "grams": row.grams,
                    "eaten_at": row.eaten_at,
                }
            )
            if not stepped.get("ok"):
                return False
    return True
