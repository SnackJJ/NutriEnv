"""Factory-gate tests: each new check rejects a broken draft and accepts a good one."""

from __future__ import annotations

from dataclasses import replace

from nutrienv.bench import Generator
from nutrienv.bench.generator import Oracle, Task
from nutrienv.bench.realizations import CONSTRAIN_ROWS, EVALUATE_ROWS, UPDATE_ROWS
from nutrienv.bench.validator import validate_draft
from nutrienv.world.types import normalize_tags


def _sample_until(family: str, predicate, limit: int = 80, **kwargs):
    generator = Generator()
    for seed in range(limit):
        task = generator.sample(seed, family=family, **kwargs)
        if predicate(task):
            return task
    raise AssertionError(f"no {family} task matched in {limit} seeds")


def _custom_update(query: str, *, add_allergens=(), window_shifts=None) -> Task:
    generator = Generator()
    s0 = generator._make_s0(0, generator._difficulty(None))
    allergies = list(s0.profile.allergies)
    for tag in add_allergens:
        if tag not in allergies:
            allergies.append(tag)
    windows = dict(s0.profile.windows)
    for key, delta in (window_shifts or {}).items():
        lo, hi = windows[key]
        windows[key] = (float(lo) + float(delta), float(hi) + float(delta))
    expected = replace(
        s0.profile,
        allergies=normalize_tags(allergies),
        windows=windows,
    )
    return Task(
        "draft",
        "update",
        query,
        s0,
        Oracle(profile=expected, ledger=tuple(s0.ledger)),
    )


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


def test_allergen_evidence_requires_a_whole_word():
    task = _custom_update(
        "My eggplant won a prize at the fair.",
        add_allergens=("egg",),
    )
    issues = validate_draft(task)
    assert any("evidenced" in item for item in issues)


def test_window_delta_rejects_an_unrelated_number_and_asymmetric_bounds():
    incidental = _custom_update(
        "Raise my calorie range by 100 at both ends. My weight is 200.",
        window_shifts={"kcal": 200.0},
    )
    issues = validate_draft(incidental)
    assert any("magnitude" in item or "delta" in item for item in issues)

    good = _custom_update(
        "Raise my calorie range by 200 at both ends.",
        window_shifts={"kcal": 200.0},
    )
    s0_kcal = good.s0.profile.windows["kcal"]
    uneven = replace(
        good,
        oracle=replace(
            good.oracle,
            profile=replace(
                good.oracle.profile,
                windows={
                    **good.oracle.profile.windows,
                    "kcal": (s0_kcal[0] + 200.0, s0_kcal[1] + 300.0),
                },
            ),
        ),
    )
    assert any("asymmetric" in item for item in validate_draft(uneven))


def test_update_oracle_must_perform_every_declared_mutation():
    row = next(item for item in UPDATE_ROWS if item.seed_id == "up-milk-kcal-200")
    generator = Generator()
    s0 = generator._make_s0(0, generator._difficulty(None))
    query, oracle = generator._update_from_row(s0, row)
    good = Task("draft", "update", query, s0, oracle)
    assert validate_draft(good) == []

    dropped = replace(
        good,
        oracle=replace(
            good.oracle,
            profile=replace(
                good.oracle.profile,
                windows=dict(good.s0.profile.windows),
            ),
        ),
    )
    issues = validate_draft(dropped)
    assert any("missing" in item or "match" in item or "shift" in item for item in issues)


def test_structural_contracts_reject_missing_oracle_fields():
    conflict = Generator().sample(8, situation="conflict_windows")
    assert validate_draft(conflict) == []
    assert validate_draft(
        replace(conflict, oracle=replace(conflict.oracle, plan_must_fit_windows=False))
    )
    assert validate_draft(replace(conflict, oracle=replace(conflict.oracle, profile=None)))
    assert validate_draft(replace(conflict, oracle=replace(conflict.oracle, ledger=None)))

    evaluate = Generator().sample(4, family="evaluate")
    assert validate_draft(evaluate) == []
    assert validate_draft(replace(evaluate, oracle=replace(evaluate.oracle, profile=None)))
    assert validate_draft(replace(evaluate, oracle=replace(evaluate.oracle, ledger=None)))

    update = Generator().sample(3, family="update")
    assert validate_draft(update) == []
    assert validate_draft(replace(update, oracle=replace(update.oracle, ledger=None)))


def test_spelled_window_magnitude_is_accepted():
    task = _custom_update(
        "Move my whole calorie range up by two hundred",
        window_shifts={"kcal": 200.0},
    )
    assert validate_draft(task) == []


def test_evaluate_gate_rejects_a_plan_that_hits_s0_allergies():
    row = next(item for item in EVALUATE_ROWS if item.seed_id == "ev-single-pb-tbsp")
    generator = Generator()
    s0 = generator._make_s0(0, generator._difficulty(None))
    query, oracle = generator._evaluate_from_row(s0, row)
    task = Task("draft", "evaluate", query, s0, oracle)
    assert validate_draft(task) == []
    task.s0.profile = replace(task.s0.profile, allergies=("peanut",))
    issues = validate_draft(task)
    assert any("unpassable" in item for item in issues)


def test_factory_evaluate_rows_are_not_unpassable():
    generator = Generator()
    knobs = generator._difficulty(None)
    base = generator._make_s0(0, knobs)
    from nutrienv.world.types import WorldState

    for row in EVALUATE_ROWS:
        s0 = WorldState(
            profile=base.profile,
            ledger=list(base.ledger),
            catalog=base.catalog,
            last_plan=list(base.last_plan),
        )
        query, oracle = generator._evaluate_from_row(s0, row)
        issues = validate_draft(Task("draft", "evaluate", query, s0, oracle))
        assert issues == [], (row.seed_id, issues)
        allergies = set(s0.profile.allergies)
        for item in oracle.last_plan:
            tags = set((s0.catalog.get(item["food_id"]) or {}).get("allergen_tags") or [])
            assert not tags & allergies, (row.seed_id, item, tags & allergies)


def test_condition_rows_do_not_reuse_the_same_food():
    foods = [row.food_id for row in CONSTRAIN_ROWS if row.kind == "condition"]
    assert None not in foods
    assert len(foods) == len(set(foods))
    assert "shrimp" in foods
    assert foods.count("shrimp") == 1


def test_conflict_table_has_non_ramp_rows():
    novel = [
        row
        for row in CONSTRAIN_ROWS
        if row.kind == "conflict"
        and row.seed_id not in {"cf-50-70", "cf-70-90", "cf-90-110", "co-gold-conflict"}
        and not (
            row.windows["kcal"][1] <= 90 and row.windows["protein_g"][0] >= 70
        )
    ]
    assert len(novel) >= 3
    frozen = {row.seed_id for row in CONSTRAIN_ROWS} & {
        "cf-50-70",
        "cf-70-90",
        "cf-90-110",
    }
    assert frozen == {"cf-50-70", "cf-70-90", "cf-90-110"}
