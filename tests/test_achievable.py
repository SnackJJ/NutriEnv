"""Oracle reachability is a Bench capability over any loaded split.

Seams: ``check_achievable(tasks)`` (loaded Tasks in, report out — no path,
no assert); ``AchievabilityReport.unreachable``; later coverage and the
``scripts/check_achievable.py --split`` CLI. Pass is still end state == Oracle.
"""

from __future__ import annotations

from nutrienv.bench import check_achievable
from nutrienv.bench.realize import Oracle, Task
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.types import LedgerRow


def _log_task(*, task_id: str = "log-001", food_id: str = "oats") -> Task:
    s0 = demo_state()
    tail = [LedgerRow(food_id, 60.0, "today-breakfast")]
    return Task(
        task_id,
        "log",
        "I had oats for breakfast.",
        s0,
        Oracle(
            profile=s0.profile,
            ledger_tail=tail,
            ledger=(*s0.ledger, *tail),
        ),
    )


def test_reachable_log_oracle_is_not_listed() -> None:
    report = check_achievable([_log_task()])
    assert report.unreachable == ()


def test_unminted_log_food_is_listed_not_raised() -> None:
    report = check_achievable([_log_task(task_id="log-bad", food_id="not_a_food")])
    assert report.unreachable == ("log-bad",)
