"""Ticket 14: split-agnostic exam quality gates pinned on synthetic splits."""

import pytest

from nutrienv.bench.realize import Oracle, Task
from nutrienv.bench.quality_gates import (
    DEFAULT_EVALUATE_TIER_FLOORS,
    CoverageReport,
    LeftoverFloorReport,
    SituationFloorReport,
    classify_evaluate_tier,
    constrained_recommends,
    evaluate_tier_coverage,
    evaluate_unfits,
    leftover_floor,
    leftover_recommends,
    recommend_coverage,
    situation_floors,
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
    floors = {"single": 1, "pair": 1, "triple": 1, "long": 0, "explicit_grams": 1}
    report = evaluate_tier_coverage(tasks, floors=floors)
    assert report.missing == ()
    assert report.counts == {
        "single": 1,
        "pair": 1,
        "triple": 1,
        "long": 0,
        "explicit_grams": 1,
        "synonym": 0,
    }

    holed = [task for task in tasks if task.id != "ev-pair"]
    assert evaluate_tier_coverage(holed, floors=floors).missing == ("pair",)


def test_evaluate_tier_floors_are_declared_by_the_caller():
    tasks = [_eval_task(f"ev-{index}", meal=[_FOOD]) for index in range(5)]
    assert evaluate_tier_coverage(tasks, floors={"single": 4}).missing == ()
    assert evaluate_tier_coverage(tasks, floors={"single": 6, "pair": 0}).missing == ("single",)


def test_leftover_recommends_count_by_scene_ledger_or_persona():
    tasks = [
        _task("rec-plain"),
        _task(
            "rec-scene",
            query="Anything left for dinner?",
            ledger=(LedgerRow("white_rice", 200.0, "lunch"),),
        ),
        _task("rec-persona", persona="leftover"),
        _task(
            "log-1",
            family="log",
            query="I ate rice.",
            ledger=(LedgerRow("white_rice", 100.0, "dinner"),),
        ),
    ]
    assert leftover_recommends(tasks) == ("rec-scene", "rec-persona")


def test_leftover_floor_defaults_to_the_adr_number():
    tasks = [
        _task(f"rec-left-{index}", ledger=(LedgerRow("banana", 118.0, "lunch"),))
        for index in range(24)
    ]
    assert leftover_floor(tasks) == LeftoverFloorReport(count=24, minimum=24)
    assert leftover_floor(tasks[:-1]) == LeftoverFloorReport(count=23, minimum=24)


def _unfit_eval_task(task_id="ev-unfit"):
    return _task(
        task_id,
        family="evaluate",
        oracle=Oracle(
            last_plan=[],
            evaluated_plan=[_FOOD],
            last_verdict="reject",
            last_reasons=("kcal_hi",),
        ),
    )


def test_evaluate_unfit_reads_the_reject_verdict():
    tasks = [
        _unfit_eval_task("ev-unfit"),
        _task(
            "ev-fit",
            family="evaluate",
            oracle=Oracle(last_plan=[_FOOD], evaluated_plan=[_FOOD], last_verdict="accept"),
        ),
    ]
    assert evaluate_unfits(tasks) == ("ev-unfit",)


def test_constrained_recommends_are_hard_s0_items():
    tasks = [
        _task("rec-plain"),
        _task("rec-conflict", windows={"kcal": (0.0, 10.0), "protein_g": (90.0, 140.0)}),
        _task("rec-trap", query="Shrimp tonight?", allergies=("shellfish",)),
        _task("rec-trap-alias", query="Any prawn ideas?", allergies=("shellfish",)),
        _task("rec-declared", query="Dinner?", situations=("condition_suitability",)),
        _task("rec-safe-named", query="Rice and chicken tonight?", allergies=("soy",)),
        _task("ev-x", family="evaluate", query="Is shrimp okay?", allergies=("shellfish",)),
    ]
    assert constrained_recommends(tasks) == (
        "rec-conflict",
        "rec-trap",
        "rec-trap-alias",
        "rec-declared",
    )


def test_situation_floors_default_to_the_adr_numbers():
    tasks = [_unfit_eval_task(f"ev-unfit-{i}") for i in range(8)] + [
        _task(f"rec-trap-{i}", query="Shrimp tonight?", allergies=("shellfish",))
        for i in range(8)
    ]
    assert situation_floors(tasks) == SituationFloorReport(
        unfit_count=8,
        unfit_minimum=8,
        constrained_count=8,
        constrained_minimum=8,
    )

    short = [task for task in tasks if task.id != "ev-unfit-7"]
    assert situation_floors(short).unfit_count == 7


def test_default_tier_floors_are_immutable_policy():
    with pytest.raises(TypeError):
        DEFAULT_EVALUATE_TIER_FLOORS["single"] = 99
    for mutator in ("update", "pop", "setdefault", "clear", "popitem"):
        with pytest.raises(AttributeError):
            getattr(DEFAULT_EVALUATE_TIER_FLOORS, mutator)


def test_tier_gate_results_do_not_leak_through_the_default_floors():
    tasks = [_eval_task("ev-single", meal=[_FOOD])]
    before = evaluate_tier_coverage(tasks)
    try:
        DEFAULT_EVALUATE_TIER_FLOORS["single"] = 99
    except TypeError:
        pass
    assert evaluate_tier_coverage(tasks) == before


def test_plan_window_numbers_are_secrets_too():
    tasks = [
        _task("rec-clean"),
        _task(
            "rec-slot-leak",
            query="What is for dinner? I have about 600 kcal to work with.",
            oracle=Oracle(plan_windows={"kcal": (400.0, 600.0)}),
        ),
        _task(
            "rec-plan-clean",
            query="Any dinner ideas?",
            oracle=Oracle(plan_windows={"kcal": (400.0, 600.0)}),
        ),
    ]
    assert window_leaks(tasks) == ("rec-slot-leak",)


def _meal(food_ids):
    return [
        {"food_id": food_id, "grams": 90.0 + 30 * index}
        for index, food_id in enumerate(food_ids)
    ]


def _eval_of_size(task_id, food_ids):
    menu = ", ".join(food_id.replace("_", " ") for food_id in food_ids)
    return _eval_task(task_id, query=f"Evaluate this as dinner: {menu}.", meal=_meal(food_ids))


def test_evaluate_tier_defaults_are_the_migrated_floors():
    assert dict(DEFAULT_EVALUATE_TIER_FLOORS) == {
        "single": 7,
        "pair": 11,
        "triple": 11,
        "long": 5,
        "explicit_grams": 4,
        "synonym": 3,
    }


def test_long_and_synonym_tiers_are_classified():
    four = _eval_of_size("ev-long", ["chicken_breast", "white_rice", "broccoli", "olive_oil"])
    five = _eval_of_size(
        "ev-longer",
        ["chicken_breast", "white_rice", "broccoli", "olive_oil", "spinach"],
    )
    assert classify_evaluate_tier(four) == "long"
    assert classify_evaluate_tier(five) == "long"

    prawns = _eval_task(
        "ev-syn",
        query="Does this work as dinner: prawns?",
        meal=[{"food_id": "shrimp", "grams": 150.0}],
    )
    assert classify_evaluate_tier(prawns) == "synonym"
    spoken = _eval_task(
        "ev-syn-grams",
        query="I had 150 g of prawns.",
        meal=[{"food_id": "shrimp", "grams": 150.0}],
    )
    assert classify_evaluate_tier(spoken) == "synonym"

    canonical_alias = _eval_task(
        "ev-pair-alias",
        query="Would a chicken and rice dinner work?",
        meal=_meal(["chicken_breast", "white_rice"]),
    )
    assert classify_evaluate_tier(canonical_alias) == "pair"


def _six_tier_split():
    tasks = []
    for index, food in enumerate(
        ["oats", "banana", "egg", "cheddar", "tuna", "potato", "tofu"]
    ):
        tasks.append(_eval_of_size(f"ev-single-{index}", [food]))
    pool = [
        "chicken_breast", "white_rice", "broccoli", "olive_oil", "spinach",
        "salmon", "milk_whole", "apple", "greek_yogurt", "whole_wheat_bread",
        "almond",
    ]
    cursor = 0

    def _take(count):
        nonlocal cursor
        foods = [pool[(cursor + offset) % len(pool)] for offset in range(count)]
        cursor += count
        return foods

    for index in range(11):
        tasks.append(_eval_of_size(f"ev-pair-{index}", _take(2)))
    for index in range(11):
        tasks.append(_eval_of_size(f"ev-triple-{index}", _take(3)))
    for index in range(5):
        tasks.append(_eval_of_size(f"ev-long-{index}", _take(4)))
    gram_rows = (
        ("ev-g-0", ["salmon"], "Evaluate this as my plan: 120 g of salmon."),
        ("ev-g-1", ["chicken_breast"], "Submit this as dinner: 180 g chicken breast?"),
        ("ev-g-2", ["salmon", "white_rice"], "Was 100 g salmon with rice okay?"),
        ("ev-g-3", ["tofu"], "160 g of tofu as a light lunch?"),
    )
    for task_id, food_ids, query in gram_rows:
        tasks.append(_eval_task(task_id, query=query, meal=_meal(food_ids)))
    for index in range(3):
        tasks.append(_eval_task(
            f"ev-syn-{index}",
            query="Does this work as dinner: prawns?",
            meal=[{"food_id": "shrimp", "grams": 150.0}],
        ))
    return tasks


def test_a_split_missing_a_tier_or_below_floor_fails_the_gate():
    full = _six_tier_split()
    report = evaluate_tier_coverage(full)
    assert report.missing == ()
    assert report.counts == {
        "single": 7,
        "pair": 11,
        "triple": 11,
        "long": 5,
        "explicit_grams": 4,
        "synonym": 3,
    }

    short_pair = [task for task in full if task.id != "ev-pair-0"]
    assert evaluate_tier_coverage(short_pair).missing == ("pair",)

    no_synonym = [task for task in full if not task.id.startswith("ev-syn-")]
    assert evaluate_tier_coverage(no_synonym).missing == ("synonym",)

    no_long = [task for task in full if not task.id.startswith("ev-long-")]
    assert evaluate_tier_coverage(no_long).missing == ("long",)


def test_only_rejects_with_the_empty_plan_unfit_contract_count():
    tasks = [
        _unfit_eval_task("ev-contract"),
        _task(
            "ev-legacy-reject",
            family="evaluate",
            oracle=Oracle(
                last_plan=[_FOOD],
                evaluated_plan=[_FOOD],
                last_verdict="reject",
            ),
        ),
        _task(
            "ev-verdictless-empty",
            family="evaluate",
            oracle=Oracle(last_plan=[], evaluated_plan=[_FOOD]),
        ),
    ]
    assert evaluate_unfits(tasks) == ("ev-contract",)


def test_constrained_recommends_cover_remainder_and_judge_plan_windows():
    tasks = [
        _task("rec-plain"),
        _task(
            "rec-impossible-in-plan-windows",
            windows={"kcal": (1500.0, 2200.0), "protein_g": (90.0, 140.0)},
            oracle=Oracle(plan_windows={"kcal": (0.0, 300.0), "protein_g": (90.0, 140.0)}),
        ),
        _task(
            "rec-satisfiable-plan-windows",
            windows={"kcal": (1500.0, 2200.0), "protein_g": (90.0, 140.0)},
            oracle=Oracle(plan_windows={"kcal": (400.0, 600.0), "protein_g": (20.0, 60.0)}),
        ),
        _task(
            "rec-leftover-remainder",
            query="What can I still eat today?",
            ledger=(LedgerRow("white_rice", 200.0, "lunch"),),
            oracle=Oracle(plan_windows={"kcal": (100.0, 300.0)}),
        ),
        _task(
            "rec-ledger-without-remainder",
            query="What now?",
            ledger=(LedgerRow("banana", 118.0, "lunch"),),
        ),
    ]
    assert constrained_recommends(tasks) == (
        "rec-impossible-in-plan-windows",
        "rec-leftover-remainder",
    )
