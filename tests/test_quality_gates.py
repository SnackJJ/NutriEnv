"""Ticket 14: split-agnostic exam quality gates pinned on synthetic splits."""

from nutrienv.bench.realize import Oracle, Task
from nutrienv.bench.quality_gates import window_leaks
from nutrienv.world.catalog_fixture import demo_catalog
from nutrienv.world.types import LedgerRow, Profile, WorldState


def _task(
    task_id="t1",
    family="recommend",
    query="What is for dinner?",
    allergies=(),
    windows=None,
    ledger=(),
    situations=(),
    persona="everyday",
    oracle=None,
):
    profile = Profile(
        user_id=f"{task_id}-user",
        allergies=allergies,
        windows=windows or {"kcal": (400.0, 700.0)},
    )
    s0 = WorldState(profile=profile, ledger=list(ledger), catalog=demo_catalog())
    return Task(task_id, family, query, s0, oracle or Oracle(), situations, persona)


def test_recommend_query_naming_its_own_window_number_is_a_leak():
    tasks = [
        _task("rec-clean", query="What is for dinner tonight?"),
        _task(
            "rec-leak",
            query="I have 600 kcal left for dinner, what should I eat?",
            windows={"kcal": (400.0, 600.0)},
        ),
    ]
    assert window_leaks(tasks) == ("rec-leak",)


def test_window_numbers_are_only_secrets_for_recommend():
    tasks = [
        _task("log-1", family="log", query="I ate 200 g of rice for lunch."),
    ]
    assert window_leaks(tasks) == ()
