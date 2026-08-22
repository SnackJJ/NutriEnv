"""Ticket 14: split-agnostic exam quality gates pinned on synthetic splits."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from nutrienv.bench.realize import Oracle, Task
from nutrienv.bench.split import load_split
from nutrienv.bench.quality_gates import (
    DEFAULT_EVALUATE_TIER_FLOORS,
    CoverageReport,
    LeftoverFloorReport,
    SituationFloorReport,
    evaluate_tier_coverage,
    constrained_recommends,
    evaluate_unfits,
    leftover_floor,
    leftover_recommends,
    recommend_coverage,
    situation_floors,
    window_leaks,
)
from nutrienv.world.catalog_fixture import demo_catalog
from nutrienv.world.types import LedgerRow, Profile, WorldState

from dataclasses import replace

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
    tier="",
):
    profile = Profile(
        user_id=f"{task_id}-user",
        allergies=allergies,
        windows=windows or {"kcal": (400.0, 700.0)},
    )
    s0 = WorldState(profile=profile, ledger=list(ledger), catalog=demo_catalog())
    return Task(task_id, family, query, s0, oracle or Oracle(), situations, persona, tier)


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


def _eval_task(task_id="ev-1", query="Is this dinner okay?", meal=None, tier=""):
    plan = list(meal or [])
    return _task(
        task_id,
        family="evaluate",
        query=query,
        oracle=Oracle(last_plan=plan, evaluated_plan=plan),
        tier=tier,
    )


def test_gate_groups_evaluate_items_by_declared_tier():
    tasks = [
        _eval_task("ev-single", meal=[_FOOD], tier="single"),
        _eval_task("ev-pair", meal=[_FOOD], tier="pair"),
        _eval_task(
            "ev-grams",
            query="Was 130 g of chicken okay?",
            meal=[_FOOD],
            tier="explicit_grams",
        ),
    ]
    floors = {"single": 1, "pair": 1, "triple": 0, "long": 0, "explicit_grams": 1}
    report = evaluate_tier_coverage(tasks, floors=floors)
    assert report.missing == ()
    assert report.counts == {
        "single": 1,
        "pair": 1,
        "triple": 0,
        "long": 0,
        "explicit_grams": 1,
    }

    holed = [task for task in tasks if task.id != "ev-pair"]
    assert evaluate_tier_coverage(holed, floors=floors).missing == ("pair",)


def test_content_never_guesses_a_declared_tier():
    synonym = _eval_task("ev-a", meal=[_FOOD], tier="synonym")
    single = _eval_task("ev-b", meal=[_FOOD], tier="single")
    report = evaluate_tier_coverage([synonym, single], floors={"synonym": 1})
    assert report.counts == {"synonym": 1}
    assert report.missing == ()


def test_undeclared_tiers_count_toward_no_floor():
    tasks = [_eval_task(f"ev-{index}", meal=[_FOOD]) for index in range(5)]
    assert evaluate_tier_coverage(tasks).missing == tuple(
        sorted(DEFAULT_EVALUATE_TIER_FLOORS)
    )


def test_evaluate_slice_must_cover_every_structural_tier():
    tasks = [
        _eval_task("ev-single", meal=[_FOOD], tier="single"),
        _eval_task("ev-pair", meal=[_FOOD], tier="pair"),
        _eval_task("ev-triple", meal=[_FOOD], tier="triple"),
        _eval_task(
            "ev-grams",
            query="Was 130 g of chicken okay?",
            meal=[_FOOD],
            tier="explicit_grams",
        ),
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
    }

    holed = [task for task in tasks if task.id != "ev-pair"]
    assert evaluate_tier_coverage(holed, floors=floors).missing == ("pair",)


def test_evaluate_tier_floors_are_declared_by_the_caller():
    tasks = [
        _eval_task(f"ev-{index}", meal=[_FOOD], tier="single") for index in range(5)
    ]
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


def test_constrained_recommends_are_verified_hard_s0_items():
    tasks = [
        _task("rec-plain"),
        _task(
            "rec-impossible-pinned",
            oracle=Oracle(plan_windows={"kcal": (0.0, 300.0), "protein_g": (90.0, 140.0)}),
        ),
        _task("rec-tight-400", oracle=Oracle(plan_windows={"kcal": (400.1, 400.1)})),
        _task("rec-trap", query="Shrimp tonight?", allergies=("shellfish",)),
        _task("rec-trap-alias", query="Any prawn ideas?", allergies=("shellfish",)),
        _task(
            "rec-leftover-remainder",
            query="What can I still eat today?",
            ledger=(LedgerRow("white_rice", 200.0, "lunch"),),
            oracle=Oracle(plan_windows={"kcal": (100.0, 300.0)}),
        ),
        _task(
            "rec-double",
            query="Shrimp tonight?",
            allergies=("shellfish",),
            ledger=(LedgerRow("white_rice", 200.0, "lunch"),),
            oracle=Oracle(plan_windows={"kcal": (100.0, 300.0)}),
        ),
        _task("rec-safe-named", query="Rice and chicken tonight?", allergies=("soy",)),
        _task("ev-x", family="evaluate", query="Is shrimp okay?", allergies=("shellfish",)),
    ]
    assert constrained_recommends(tasks) == (
        "rec-impossible-pinned",
        "rec-tight-400",
        "rec-trap",
        "rec-trap-alias",
        "rec-leftover-remainder",
        "rec-double",
    )


def test_a_lying_situation_label_never_satisfies_the_floor():
    tasks = [
        _task("rec-liar", query="Dinner?", situations=("conflict_windows",)),
        _task(
            "rec-real",
            query="Shrimp tonight?",
            allergies=("shellfish",),
        ),
    ]
    report = situation_floors(tasks)
    assert constrained_recommends(tasks) == ("rec-real",)
    assert report.constrained_count == 1


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


def test_evaluate_tier_defaults_are_the_migrated_floors():
    assert dict(DEFAULT_EVALUATE_TIER_FLOORS) == {
        "single": 7,
        "pair": 11,
        "triple": 11,
        "long": 5,
        "explicit_grams": 4,
        "synonym": 3,
    }


def _six_tier_split():
    """Every evaluate item declares its tier; content is irrelevant."""
    tasks = []
    for index in range(7):
        tasks.append(_eval_task(
            f"ev-single-{index}", meal=[{"food_id": "oats", "grams": 60.0}], tier="single",
        ))
    for index in range(11):
        tasks.append(_eval_task(f"ev-pair-{index}", meal=[_FOOD, _RICE], tier="pair"))
    for index in range(11):
        tasks.append(_eval_task(
            f"ev-triple-{index}", meal=[_FOOD, _RICE, _BROCCOLI], tier="triple",
        ))
    for index in range(5):
        tasks.append(_eval_task(
            f"ev-long-{index}",
            meal=[_FOOD, _RICE, _BROCCOLI, {"food_id": "olive_oil", "grams": 10.0}],
            tier="long",
        ))
    for index in range(4):
        tasks.append(_eval_task(
            f"ev-g-{index}",
            query=f"Was {120 + 10 * index} g of chicken okay?",
            meal=[_FOOD],
            tier="explicit_grams",
        ))
    for index in range(3):
        tasks.append(_eval_task(
            f"ev-syn-{index}",
            query="Does this work as dinner: prawns?",
            meal=[{"food_id": "shrimp", "grams": 150.0}],
            tier="synonym",
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

    relabeled = [
        replace(task, tier="single") if task.id == "ev-pair-0" else task
        for task in full
    ]
    report = evaluate_tier_coverage(relabeled)
    assert report.counts["pair"] == 10
    assert report.counts["single"] == 8
    assert report.missing == ("pair",)


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


def test_declared_tiers_survive_realization_freeze_and_reload(tmp_path):
    from nutrienv.bench.pipeline.freezer import task_to_item
    from nutrienv.bench.realizations.tables.evaluate import EvaluateRow
    from nutrienv.bench.realize import material_from_row, realize, realize_evaluate
    from nutrienv.world.catalog_fixture import demo_catalog, demo_profile
    from nutrienv.world.daily_windows import derive_daily_windows
    from nutrienv.world.types import WorldState

    def _full_window_state():
        return WorldState(
            profile=replace(
                demo_profile(),
                windows=derive_daily_windows(
                    sex="female",
                    age_y=34,
                    height_cm=165.0,
                    weight_kg=62.0,
                    activity="light",
                    phase="maintain",
                ),
            ),
            catalog=demo_catalog(),
        )

    rows = (
        EvaluateRow(
            "ev-tier-pair",
            "Evaluate this as lunch: 150 g chicken and a cup of rice.",
            (("chicken_breast", "150 g"), ("white_rice", "a cup")),
            tier="pair",
        ),
        EvaluateRow(
            "ev-tier-synonym",
            "Evaluate this as dinner: prawns?",
            (("shrimp", "150 g"),),
            tier="synonym",
        ),
        EvaluateRow(
            "ev-tier-default",
            "Check this snack for me: a piece of banana.",
            (("banana", "a piece"),),
        ),
    )
    catalog = demo_catalog()
    tasks = [
        realize(material_from_row(row, tag="t", catalog=catalog), row.query, catalog=catalog)
        for row in rows
    ]
    assert [task.tier for task in tasks] == ["pair", "synonym", ""]

    direct = realize_evaluate(
        task_id="ev-direct",
        query="Is this okay?",
        items=[{"food_id": "egg", "grams": 50.0}],
        s0=_full_window_state(),
        occasion="dinner",
        tier="long",
    )
    assert direct.tier == "long"

    path = tmp_path / "tiered.json"
    path.write_text(
        json.dumps({"items": [task_to_item(task) for task in tasks + [direct]]}),
        encoding="utf-8",
    )
    reloaded = load_split(path)
    report = evaluate_tier_coverage(reloaded, floors={"pair": 1, "synonym": 1, "long": 1})
    assert report.missing == ()
    assert report.counts["pair"] == 1
    assert report.counts["synonym"] == 1
    assert report.counts["long"] == 1


def test_named_dish_matches_the_spoken_name_segment():
    catalog = {
        "salmon_dish": {
            "name": "Grilled salmon, 150g portion",
            "nutrients": {"kcal": 200.0},
            "allergen_tags": ["fish"],
            "aliases": [],
        },
    }
    base = _task("rec-dish", query="Grilled salmon tonight?", allergies=("fish",))
    task = replace(base, s0=replace(base.s0, catalog=catalog))
    assert constrained_recommends([task]) == ("rec-dish",)


def test_two_decimal_window_values_are_secrets():
    tasks = [
        _task(
            "rec-decimal",
            query="I have about 612.75 kcal left, what should I eat?",
            windows={"kcal": (400.0, 612.75)},
        ),
        _task("rec-clean-frac", query="Half of my budget?", windows={"kcal": (400.0, 612.75)}),
    ]
    assert window_leaks(tasks) == ("rec-decimal",)


def test_number_leaks_need_word_boundaries():
    tasks = [
        _task(
            "rec-thousands",
            query="I ate 6000 kcal yesterday, what now?",
            windows={"kcal": (400.0, 600.0)},
        ),
        _task(
            "rec-real-leak",
            query="I have 600 kcal left for dinner.",
            windows={"kcal": (400.0, 600.0)},
        ),
    ]
    assert window_leaks(tasks) == ("rec-real-leak",)


def test_caller_declared_custom_tiers_are_counted():
    tasks = [
        _eval_task("ev-a", meal=[_FOOD], tier="knife_swap"),
        _eval_task("ev-b", meal=[_FOOD], tier="knife_allergy"),
    ]
    assert evaluate_tier_coverage(tasks, floors={"knife_swap": 1}).counts[
        "knife_swap"
    ] == 1
    assert evaluate_tier_coverage(tasks, floors={"knife_swap": 2}).missing == (
        "knife_swap",
    )


def test_custom_floors_key_the_report_exactly_by_the_supplied_tiers():
    tasks = [
        _eval_task("ev-knife", meal=[_FOOD], tier="knife_swap"),
        _eval_task("ev-builtin", meal=[_FOOD], tier="single"),
    ]
    report = evaluate_tier_coverage(tasks, floors={"knife_swap": 1})
    assert report.counts == {"knife_swap": 1}
    assert report.missing == ()


def test_default_call_keys_counts_by_the_six_builtin_tiers():
    report = evaluate_tier_coverage([_eval_task("ev-single", meal=[_FOOD], tier="single")])
    assert set(report.counts) == set(DEFAULT_EVALUATE_TIER_FLOORS)


def test_allergen_matching_normalizes_tags():
    tasks = [
        _task("rec-messy", query="Shrimp tonight?", allergies=("  Shellfish ",)),
        _task("rec-clean", query="Shrimp tonight?", allergies=("shellfish",)),
    ]
    assert constrained_recommends(tasks) == ("rec-messy", "rec-clean")


def test_default_allergen_claim_is_the_union_of_split_catalogs():
    def _with_catalog(task_id, catalog, allergy):
        base = _task(task_id, allergies=(allergy,))
        return replace(base, s0=replace(base.s0, catalog=catalog))

    tasks = [
        _with_catalog("rec-a", {"food_a": {"allergen_tags": ["alpha"]}}, "alpha"),
        _with_catalog("rec-b", {"food_b": {"allergen_tags": ["beta"]}}, "alpha"),
    ]
    assert recommend_coverage(tasks).missing_allergens == ("beta",)
