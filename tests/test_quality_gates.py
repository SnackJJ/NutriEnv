"""Ticket 14: split-agnostic exam quality gates pinned on synthetic splits."""

from nutrienv.bench.realize import Oracle, Task
from nutrienv.bench.quality_gates import (
    CoverageReport,
    classify_evaluate_tier,
    evaluate_tier_coverage,
    recommend_coverage,
    window_leaks,
)
from nutrienv.world.catalog_fixture import demo_catalog
from nutrienv.world.types import LedgerRow, Profile, WorldState

# Every tag the fixture catalog declares on some food.
CATALOG_TAGS = (
    "peanut", "shellfish", "egg", "milk", "tree_nut",
    "fish", "soy", "gluten", "wheat",
)


def _covered_split():
    """A recommend slice whose profiles jointly carry every catalog tag."""
    return [
        _task(f"rec-{tag}", query="What is for dinner?", allergies=(tag,))
        for tag in CATALOG_TAGS
    ]


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


def test_recommend_coverage_reports_missing_personas_and_allergens():
    full = _covered_split() + [
        _task("rec-cut", query="Lunch?", allergies=("peanut",), persona="cut"),
    ]
    assert recommend_coverage(full, personas=("everyday", "cut")) == CoverageReport((), ())

    holed = [task for task in full if task.id != "rec-soy"]
    report = recommend_coverage(holed, personas=("everyday", "cut", "gym"))
    assert report.missing_personas == ("gym",)
    assert report.missing_allergens == ("soy",)


def test_recommend_coverage_ignores_other_families():
    tasks = [
        _task("rec-1", query="Dinner?"),
        _task("log-1", family="log", query="I ate eggs.", allergies=("egg",)),
    ]
    report = recommend_coverage(tasks, allergen_tags=("egg",))
    assert report.missing_allergens == ("egg",)


def test_recommend_coverage_defaults_to_every_catalog_tag():
    covered = recommend_coverage(_covered_split())
    assert covered.missing_allergens == ()
    thin = recommend_coverage([_task("rec-thin")])
    assert thin.missing_allergens == tuple(sorted(CATALOG_TAGS))


_FOOD = {"food_id": "chicken_breast", "grams": 130.0}
_RICE = {"food_id": "white_rice", "grams": 158.0}
_BROCCOLI = {"food_id": "broccoli", "grams": 91.0}


def _eval_task(task_id="ev-1", query="Is this dinner okay?", meal=None):
    plan = list(meal or [])
    return _task(
        task_id,
        family="evaluate",
        query=query,
        oracle=Oracle(last_plan=plan, evaluated_plan=plan),
    )


def test_evaluate_tier_reads_meal_size_and_spoken_grams():
    assert classify_evaluate_tier(_eval_task("ev-a", meal=[_FOOD])) == "single"
    assert classify_evaluate_tier(_eval_task("ev-b", meal=[_FOOD, _RICE])) == "pair"
    assert classify_evaluate_tier(_eval_task("ev-c", meal=[_FOOD, _RICE, _BROCCOLI])) == "triple"
    grams = _eval_task("ev-d", query="I had 130 g chicken with rice.", meal=[_FOOD, _RICE])
    assert classify_evaluate_tier(grams) == "explicit_grams"


def test_evaluate_slice_must_cover_every_structural_tier():
    tasks = [
        _eval_task("ev-single", meal=[_FOOD]),
        _eval_task("ev-pair", meal=[_FOOD, _RICE]),
        _eval_task("ev-triple", meal=[_FOOD, _RICE, _BROCCOLI]),
        _eval_task("ev-grams", query="Was 130 g of chicken okay?", meal=[_FOOD]),
    ]
    report = evaluate_tier_coverage(tasks)
    assert report.missing == ()
    assert report.counts == {"single": 1, "pair": 1, "triple": 1, "explicit_grams": 1}

    holed = [task for task in tasks if task.id != "ev-pair"]
    assert evaluate_tier_coverage(holed).missing == ("pair",)


def test_evaluate_tier_floors_are_declared_by_the_caller():
    tasks = [_eval_task(f"ev-{index}", meal=[_FOOD]) for index in range(5)]
    assert evaluate_tier_coverage(tasks, floors={"single": 4}).missing == ()
    assert evaluate_tier_coverage(tasks, floors={"single": 6, "pair": 0}).missing == ("single",)
