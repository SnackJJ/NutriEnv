"""Factory-gate tests: each new check rejects a broken draft and accepts a good one."""

from __future__ import annotations

from dataclasses import replace

from nutrienv.bench import Generator
from nutrienv.bench.realizations import UPDATE_ROWS
from nutrienv.bench.validator import validate_draft


def _sample_until(family: str, predicate, limit: int = 80, **kwargs):
    generator = Generator()
    for seed in range(limit):
        task = generator.sample(seed, family=family, **kwargs)
        if predicate(task):
            return task
    raise AssertionError(f"no {family} task matched in {limit} seeds")


def test_update_gate_rejects_mismatched_delta_and_accepts_gold_both():
    good = _sample_until("update", lambda task: "200" in task.query and "shrimp" in task.query.lower())
    assert validate_draft(good) == []

    s0_kcal = good.s0.profile.windows["kcal"]
    broken_profile = replace(
        good.oracle.profile,
        windows={
            **good.oracle.profile.windows,
            "kcal": (s0_kcal[0] + 300.0, s0_kcal[1] + 300.0),
        },
    )
    broken = replace(good, oracle=replace(good.oracle, profile=broken_profile))
    issues = validate_draft(broken)
    assert any("200" in item or "delta" in item or "window" in item for item in issues)

    nothing = replace(good, oracle=replace(good.oracle, profile=good.s0.profile))
    assert any("moved" in item or "unchanged" in item or "profile" in item for item in validate_draft(nothing))

    shrimp = replace(
        good,
        oracle=replace(
            good.oracle,
            profile=replace(good.oracle.profile, allergies=("shrimp",)),
        ),
    )
    assert any("shrimp" in item or "tag" in item for item in validate_draft(shrimp))


def test_update_gold_shaped_shellfish_kcal_row_exists():
    assert any(
        "reacted to shrimp" in row.query.lower() and "200" in row.query
        for row in UPDATE_ROWS
    )
    task = _sample_until(
        "update",
        lambda item: "reacted to shrimp" in item.query.lower() and "200" in item.query,
    )
    assert "shellfish" in task.oracle.profile.allergies
    assert "shrimp" not in task.oracle.profile.allergies
    s0_kcal = task.s0.profile.windows["kcal"]
    assert task.oracle.profile.windows["kcal"] == (s0_kcal[0] + 200.0, s0_kcal[1] + 200.0)
    assert task.oracle.profile != task.s0.profile
    assert task.oracle.profile.medications == task.s0.profile.medications
    assert validate_draft(task) == []


def test_condition_gate_rejects_wrong_oracle_and_wide_windows():
    good = Generator().sample(7, situation="condition_suitability")
    assert validate_draft(good) == []
    assert good.oracle.last_plan == []
    assert good.oracle.allow_empty_plan is False

    empty_ok = replace(good, oracle=replace(good.oracle, allow_empty_plan=True))
    assert validate_draft(empty_ok)

    planned = replace(
        good,
        oracle=replace(good.oracle, last_plan=[{"food_id": "chicken_breast", "grams": 150.0}]),
    )
    assert validate_draft(planned)

    good.s0.profile = replace(
        good.s0.profile,
        windows={"kcal": (400.0, 900.0), "protein_g": (20.0, 50.0)},
    )
    assert any("800" in item or "kcal" in item for item in validate_draft(good))


def test_conflict_gate_rejects_satisfiable_windows_and_empty_s0_plan():
    good = Generator().sample(8, situation="conflict_windows")
    assert validate_draft(good) == []
    assert good.s0.last_plan
    assert good.oracle.last_plan is None
    assert good.oracle.allow_empty_plan is True

    good.s0.last_plan = []
    assert validate_draft(good)
    good.s0.last_plan = [{"food_id": "chicken_breast", "grams": 200.0}]

    good.s0.profile = replace(
        good.s0.profile,
        windows={"kcal": (200.0, 800.0), "protein_g": (10.0, 40.0)},
    )
    assert any("unsatisfiable" in item or "satisfiable" in item for item in validate_draft(good))


def test_evaluate_gate_rejects_instead_wrong_grams_and_unmentioned_food():
    good = Generator().sample(4, family="evaluate")
    assert validate_draft(good) == []
    assert good.oracle.last_plan

    instead = replace(good, query=good.query + " what instead")
    assert any("instead" in item for item in validate_draft(instead))

    tweaked = [dict(item) for item in good.oracle.last_plan]
    tweaked[0] = {**tweaked[0], "grams": float(tweaked[0]["grams"]) + 50.0}
    wrong_grams = replace(good, oracle=replace(good.oracle, last_plan=tweaked))
    assert any("grams" in item or "resolve" in item for item in validate_draft(wrong_grams))

    silent = replace(good, query="Evaluate this as my plan: a mystery plate.")
    assert any("mention" in item or "named" in item for item in validate_draft(silent))

    good.s0.profile = replace(
        good.s0.profile,
        windows={"kcal": (1.0, 2.0), "protein_g": (1.0, 2.0)},
    )
    assert any("window" in item or "outside" in item for item in validate_draft(good))
