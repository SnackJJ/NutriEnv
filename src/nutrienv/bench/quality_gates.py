"""Split-agnostic quality floors for any frozen exam split.

Five checks migrated from the archived v0.x increment tests (ticket 14).
They take a loaded split -- the ``Sequence[Task]`` that ``load_split``
returns -- never a split path or item id, and report instead of asserting,
so a caller chooses to gate, print, or drop ids. Coverage-type floors are
declared by the exam's own contract; the gates only verify the frozen
split backs it.
"""

from __future__ import annotations

from collections.abc import Sequence

from .realize import Task

__all__ = ["window_leaks"]


def _leaks_windows(task: Task) -> bool:
    """A recommend query that names its own numbers is answerable without
    reading the profile, which is the whole point of the family."""
    for bounds in task.s0.profile.windows.values():
        for value in bounds:
            if (
                value
                and float(value).is_integer()
                and abs(value) >= 10
                and str(int(value)) in task.query
            ):
                return True
    return False


def window_leaks(tasks: Sequence[Task]) -> tuple[str, ...]:
    """Ids of recommend tasks whose query states one of their window numbers."""
    return tuple(task.id for task in tasks if task.family == "recommend" and _leaks_windows(task))
