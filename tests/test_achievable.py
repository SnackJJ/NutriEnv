"""Oracle reachability is a Bench capability over any loaded split.

Seams: ``check_achievable(tasks)`` (loaded Tasks in, report out — no path,
no assert); ``AchievabilityReport.unreachable``; later coverage and the
``scripts/check_achievable.py --split`` CLI. Pass is still end state == Oracle.
"""

from __future__ import annotations

from dataclasses import replace

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


def test_exact_last_plan_evaluate_is_reachable() -> None:
    s0 = demo_state()
    plan = [{"food_id": "chicken_breast", "grams": 150.0}]
    task = Task(
        "eval-001",
        "evaluate",
        "Evaluate 150 g chicken.",
        s0,
        Oracle(profile=s0.profile, last_plan=plan, ledger=tuple(s0.ledger)),
    )
    assert check_achievable([task]).unreachable == ()


def test_any_fitting_plan_recommend_is_reachable() -> None:
    s0 = demo_state()
    s0.profile = replace(
        s0.profile,
        windows={"kcal": (200.0, 500.0), "protein_g": (20.0, 50.0)},
    )
    task = Task(
        "rec-001",
        "recommend",
        "What's for dinner?",
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            ledger=tuple(s0.ledger),
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
        ),
    )
    assert check_achievable([task]).unreachable == ()


def test_allow_empty_plan_is_reachable_when_no_fitting_plan_exists() -> None:
    s0 = demo_state()
    s0.profile = replace(
        s0.profile,
        windows={"kcal": (1.0, 2.0), "protein_g": (1000.0, 2000.0)},
    )
    task = Task(
        "conf-001",
        "constrain",
        "Those numbers cannot work together.",
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            ledger=tuple(s0.ledger),
            allow_empty_plan=True,
        ),
    )
    assert check_achievable([task]).unreachable == ()


def test_unsatisfiable_recommend_is_unreachable() -> None:
    s0 = demo_state()
    s0.profile = replace(
        s0.profile,
        windows={"kcal": (1.0, 2.0), "protein_g": (1000.0, 2000.0)},
    )
    task = Task(
        "rec-impossible",
        "recommend",
        "What's for dinner?",
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            ledger=tuple(s0.ledger),
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
        ),
    )
    assert check_achievable([task]).unreachable == ("rec-impossible",)


def test_fitting_plan_uses_oracle_plan_windows() -> None:
    s0 = demo_state()
    s0.profile = replace(
        s0.profile,
        windows={"kcal": (1.0, 2.0), "protein_g": (1000.0, 2000.0)},
    )
    task = Task(
        "rec-leftover",
        "recommend",
        "What's for dinner?",
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            ledger=tuple(s0.ledger),
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
            plan_windows={"kcal": (200.0, 500.0), "protein_g": (20.0, 50.0)},
        ),
    )
    assert check_achievable([task]).unreachable == ()
