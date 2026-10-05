"""Goal-specific daily ranges and explicit single-meal protein requirements."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from nutrienv.bench import Oracle, Scorer, load_exam, load_split
from nutrienv.bench.achievable import check_achievable
from nutrienv.bench.pipeline.freezer import task_to_item
from nutrienv.bench.realize import scored_oracles
from nutrienv.bench.validator import fitting_plan, validate_ledger_variants
from nutrienv.harness.buddy import ObservationCache, check_write, verify_plan
from nutrienv.harness.prompt_freeze import SHARED_TASK_SPEC
from nutrienv.harness.react import react_manual
from nutrienv.harness.tools_schema import TOOL_SYSTEM_PROMPT
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.daily_windows import derive_daily_windows
from nutrienv.world.portions import resolve_portion


@pytest.fixture(scope="module")
def exam():
    return {task.id: task for task in load_exam()}


def test_cut_macros_use_target_energy_not_maintenance():
    daily = derive_daily_windows(sex="female", age_y=34, height_cm=165,
                                 weight_kg=62, activity="light", phase="cut")
    target = 1515.34375
    assert daily["kcal"] == (target, target)
    assert daily["protein_g"] == pytest.approx((49.6, target * .35 / 4))
    assert daily["carb_g"] == pytest.approx((target * .45 / 4, target * .65 / 4))
    assert daily["fat_g"] == pytest.approx((target * .20 / 9, target * .35 / 9))
    assert daily["fiber_g"] == pytest.approx((target * 28 / 2000,) * 2)


def test_muscle_has_a_finite_body_weight_range():
    daily = derive_daily_windows(sex="female", age_y=34, height_cm=165,
                                 weight_kg=62, activity="light", phase="muscle")
    assert daily["protein_g"] == pytest.approx((99.2, 136.4))


def test_conflicting_protein_floor_and_target_ceiling_fail_loudly():
    with pytest.raises(ValueError, match="protein requirement.*exceeds"):
        derive_daily_windows(sex="female", age_y=100, height_cm=80,
                             weight_kg=100, activity="sedentary", phase="cut")


@pytest.mark.parametrize("protein,tag", [(9.99, "protein_share"), (10, "pass"), (25, "pass")])
def test_high_protein_uses_plan_energy_and_an_inclusive_threshold(protein, tag):
    state = demo_state()
    state.catalog = {**state.catalog, "test_meal": {
        "name": "Test meal", "portions": {"qns": 100}, "allergen_tags": [], "aliases": [],
        "nutrients": {"kcal": 200, "protein_g": protein},
    }}
    state.profile = replace(state.profile, windows={"kcal": (0, 400), "protein_g": (0, 30)})
    state.last_plan = [{"food_id": "test_meal", "grams": 100}]
    oracle = Oracle(last_plan=[], plan_must_fit_windows=True, plan_high_protein=True)
    assert Scorer().score(state, oracle)["tag"] == tag
    assert Scorer().score(state, replace(oracle, plan_high_protein=False))["passed"]
    state.last_plan[0]["grams"] = 301
    assert Scorer().score(state, oracle)["tag"] == "window"


def test_all_four_natural_high_protein_queries_are_scored(exam):
    expected = {"adr24-comp-8239", "adr29-fridge-03", "adr29-conv-02", "adr29-conv-05"}
    flagged = {t.id for t in exam.values() if any(o.plan_high_protein for o in scored_oracles(t.oracle))}
    assert flagged == expected
    assert {t.id for t in exam.values() if "high-protein" in t.query} == expected
    for task_id in expected:
        task = exam[task_id]
        child = next(o for o in scored_oracles(task.oracle) if o.plan_high_protein)
        profile = child.profile or task.s0.profile
        assert child.plan_windows is not None
        plan = fitting_plan(task.s0.catalog, child.plan_windows, profile.allergies,
                            allowed_food_ids=task.s0.allowed_food_ids, high_protein=True)
        assert plan is not None, task_id
        state = replace(task.s0, profile=profile, ledger=list(child.ledger or ()), last_plan=plan)
        assert Scorer().score(state, child)["passed"], task_id


@pytest.mark.parametrize("task_id,food,grams,tag", [
    ("adr29-conv-05", "2710541", 2757, "implausible_quantity"),
    ("adr29-conv-02", "2710542", 1, "protein_share"),
])
def test_cola_cannot_satisfy_high_protein_queries(exam, task_id, food, grams, tag):
    task = exam[task_id]
    state = replace(task.s0, last_plan=[{"food_id": food, "grams": grams}])
    assert Scorer().score(state, task.oracle)["tag"] == tag


def test_edamame_soy_repair_is_observed_and_scored_without_changing_old_catalog(exam):
    task = exam["adr29-conv-01"]
    assert "soy" in task.s0.catalog["2707436"]["allergen_tags"]
    state = replace(task.s0, last_plan=[{"food_id": "2707436", "grams": 356.9}])
    assert Scorer().score(state, task.oracle)["tag"] == "allergy"
    original = load_catalog(Path(__file__).resolve().parents[1] / "data/fdc/catalog.sqlite")
    assert tuple(original["2707436"]["allergen_tags"]) == ()


def test_missing_default_never_substitutes_piece_or_cup():
    catalog = {"meal": {"name": "Meal", "portions": {"piece": 50, "cup": 100}}}
    assert resolve_portion("meal", "a meal", catalog) is None
    assert resolve_portion("meal", "a serving", catalog) is None
    assert resolve_portion("meal", "a piece", catalog) == 50
    catalog["meal"]["portions"]["qns"] = 200
    assert resolve_portion("meal", "a meal", catalog) == 200
    assert resolve_portion("meal", "two pieces", catalog) == 100
    assert resolve_portion("meal", "a slice", catalog) is None


def test_every_interpretation_is_checked_and_reachable(exam):
    for task in exam.values():
        assert validate_ledger_variants(task) == [], task.id
    assert check_achievable(list(exam.values())).unreachable == ()


@pytest.mark.parametrize("task_id", ["adr24-comp-8239", "adr29-amend-04"])
def test_freezer_preserves_requirements_and_complete_variants(exam, tmp_path, task_id):
    task = exam[task_id]
    path = tmp_path / "roundtrip.json"
    path.write_text(json.dumps({"items": [task_to_item(task)]}))
    rebuilt = load_split(path, catalog=task.s0.catalog)[0]
    assert rebuilt == task


def test_all_harness_manuals_expose_portion_and_high_protein_contract():
    assert len(SHARED_TASK_SPEC.split()) <= 400
    for manual in [TOOL_SYSTEM_PROMPT, *(react_manual(v) for v in ("v0", "v1", "v2"))]:
        assert SHARED_TASK_SPEC in manual
        assert "20%" in manual
        assert "portions.qns" in manual
        assert "1.6-2.2" in manual


def test_buddy_checks_the_explicit_meal_requirement():
    state = demo_state()
    cache = ObservationCache(profile={"windows": {"kcal": [0, 1000], "protein_g": [0, 100]}},
                             foods=dict(state.catalog), ledger_rows=[], ledger_totals={})
    action = {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 100}]}
    assert check_write(action, cache, "Recommend a snack.").ok
    assert not check_write(action, cache, "Recommend a high-protein snack.").ok
    assert not verify_plan(action, cache, "Recommend a high-protein snack.").ok


@pytest.mark.parametrize("flag", ["true", 1, None])
def test_loader_refuses_non_boolean_high_protein_flags(exam, tmp_path, flag):
    item = task_to_item(exam["adr29-conv-02"])
    item["oracle"]["plan_high_protein"] = flag
    path = tmp_path / "bad-flag.json"
    path.write_text(json.dumps({"items": [item]}))
    with pytest.raises(TypeError, match="must be a boolean"):
        load_split(path, catalog=exam["adr29-conv-02"].s0.catalog)


@pytest.mark.parametrize("energy,protein,passed", [
    (500, 24.99, False), (500, 25, True),
    (100, 9.99, False), (100, 10, True), (0, 10, False),
])
def test_ratio_and_gram_floor_are_independent(energy, protein, passed):
    from nutrienv.world.daily_windows import high_protein_pass

    assert high_protein_pass({"kcal": energy, "protein_g": protein}) is passed
