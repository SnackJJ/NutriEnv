"""Factory-gate tests: each new check rejects a broken draft and accepts a good one."""

from __future__ import annotations

from dataclasses import replace

from nutrienv.bench.pipeline.resolver import resolve_candidate
from nutrienv.bench.pipeline.types import Candidate
from nutrienv.bench.realize import (
    GOLD_WINDOWS,
    Oracle,
    Task,
    material_from_row,
    realize,
    spoken_query,
)
from nutrienv.bench.realizations import CONSTRAIN_ROWS, EVALUATE_ROWS, LEFTOVER_ROWS, UPDATE_ROWS
from nutrienv.bench.validator import fitting_plan, validate_draft
from nutrienv.bench.windows import windows_unsatisfiable
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.types import Profile, WorldState, normalize_tags


def _task(row):
    return realize(material_from_row(row), spoken_query(row))


def _update_until(predicate):
    for row in UPDATE_ROWS:
        task = _task(row)
        if predicate(task):
            return task
    raise AssertionError("no update row matched")


def _draft_s0() -> WorldState:
    return WorldState(
        profile=Profile(
            user_id="draft",
            allergies=("peanut",),
            windows=dict(GOLD_WINDOWS),
        ),
        ledger=[],
        catalog=load_catalog(),
        last_plan=[],
    )


def _custom_update(query: str, *, add_allergens=(), window_shifts=None) -> Task:
    s0 = _draft_s0()
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
    good = _update_until(lambda task: "200" in task.query and "shrimp" in task.query.lower())
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
    task = _update_until(
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
    good = _task(next(row for row in CONSTRAIN_ROWS if row.kind == "condition"))
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
    good = _task(next(row for row in CONSTRAIN_ROWS if row.kind == "conflict"))
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


def test_evaluate_gate_accepts_rewritten_query_when_grams_anchored():
    """F1/R1: D4 is semantic gram backresolve, not query↔Row verbatim.

    The old gate rejected any paraphrase that did not match an
    EVALUATE_ROWS query byte-for-byte. A rewritten query that keeps the
    oracle grams and still names every plan food must now pass.
    """
    good = _task(EVALUATE_ROWS[0])
    assert validate_draft(good) == []
    rewritten = replace(good, query="Today, " + good.query)
    assert not any(row.query == rewritten.query for row in EVALUATE_ROWS)
    assert validate_draft(rewritten) == []


def test_evaluate_gate_rejects_rewritten_query_with_off_table_grams():
    """D4 stays fail-closed: a rewritten query cannot smuggle off-table grams."""
    good = _task(EVALUATE_ROWS[0])
    tweaked = [dict(item) for item in good.oracle.last_plan]
    tweaked[0] = {**tweaked[0], "grams": float(tweaked[0]["grams"]) + 50.0}
    rewritten = replace(
        good,
        query="Today, " + good.query,
        oracle=replace(good.oracle, last_plan=tweaked),
    )
    assert not any(row.query == rewritten.query for row in EVALUATE_ROWS)
    issues = validate_draft(rewritten)
    assert any("portion table" in item for item in issues)


def test_evaluate_gate_accepts_llm_style_query_when_grams_anchored():
    """An LLM evaluate query realized through the pipeline must pass the gate."""
    query = (
        "Does this work as my dinner: a can of tuna, a cup of rice, "
        "and a cup of broccoli?"
    )
    candidate = Candidate(
        items=(("tuna", "a can"), ("rice", "a cup"), ("broccoli", "a cup")),
        query=query,
        family="evaluate",
        persona="everyday",
    )
    task, rejected = resolve_candidate(
        candidate,
        catalog=load_catalog(),
        task_id="r1-eval-llm-dinner",
        seen=set(),
    )
    assert rejected is None
    assert task is not None
    assert not any(row.query == task.query for row in EVALUATE_ROWS)
    assert validate_draft(task) == []


def test_evaluate_gate_rejects_instead_wrong_grams_and_unmentioned_food():
    good = _task(EVALUATE_ROWS[0])
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
    good = _task(row)
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
    conflict = _task(next(row for row in CONSTRAIN_ROWS if row.kind == "conflict"))
    assert validate_draft(conflict) == []
    assert validate_draft(
        replace(conflict, oracle=replace(conflict.oracle, plan_must_fit_windows=False))
    )
    assert validate_draft(replace(conflict, oracle=replace(conflict.oracle, profile=None)))
    assert validate_draft(replace(conflict, oracle=replace(conflict.oracle, ledger=None)))

    evaluate = _task(EVALUATE_ROWS[0])
    assert validate_draft(evaluate) == []
    assert validate_draft(replace(evaluate, oracle=replace(evaluate.oracle, profile=None)))
    assert validate_draft(replace(evaluate, oracle=replace(evaluate.oracle, ledger=None)))

    update = _task(next(row for row in UPDATE_ROWS if row.add_allergens))
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
    task = _task(row)
    assert validate_draft(task) == []
    task.s0.profile = replace(task.s0.profile, allergies=("peanut",))
    issues = validate_draft(task)
    assert any("unpassable" in item for item in issues)


def test_factory_evaluate_rows_are_not_unpassable():
    for row in EVALUATE_ROWS:
        task = _task(row)
        issues = validate_draft(task)
        assert issues == [], (row.seed_id, issues)
        allergies = set(task.s0.profile.allergies)
        for item in task.oracle.last_plan:
            tags = set((task.s0.catalog.get(item["food_id"]) or {}).get("allergen_tags") or [])
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
            row.windows.get("kcal", (0.0, 0.0))[1] <= 90
            and row.windows.get("protein_g", (0.0, 0.0))[0] >= 70
        )
    ]
    assert len(novel) >= 3
    frozen = {row.seed_id for row in CONSTRAIN_ROWS} & {
        "cf-50-70",
        "cf-70-90",
        "cf-90-110",
    }
    assert frozen == {"cf-50-70", "cf-70-90", "cf-90-110"}


def _recommend_draft(windows, allergies=(), query="What should I eat tonight?"):
    s0 = _draft_s0()
    s0.profile = replace(s0.profile, windows=dict(windows), allergies=allergies)
    s0.ledger = []
    return Task(
        "draft",
        "recommend",
        query,
        s0,
        Oracle(
            profile=s0.profile,
            last_plan=[],
            plan_must_be_safe=True,
            plan_must_fit_windows=True,
            ledger=tuple(s0.ledger),
        ),
    )


def test_recommend_gate_rejects_unsatisfiable_windows():
    task = _recommend_draft({"kcal": (0.0, 50.0), "protein_g": (70.0, 120.0)})
    issues = validate_draft(task)
    assert any("unpassable" in item for item in issues)


def test_recommend_gate_accepts_a_normal_meal():
    task = _recommend_draft({"kcal": (400.0, 800.0), "protein_g": (20.0, 50.0)})
    assert validate_draft(task) == []


def test_recommend_gate_searches_the_oracle_profile():
    task = _recommend_draft({"kcal": (400.0, 800.0), "protein_g": (20.0, 50.0)})
    assert validate_draft(task) == []
    task = replace(
        task,
        oracle=replace(
            task.oracle,
            profile=replace(
                task.oracle.profile,
                windows={"kcal": (0.0, 1.0), "protein_g": (100.0, 110.0)},
            ),
        ),
    )
    issues = validate_draft(task)
    assert any("unpassable" in item for item in issues)


def test_leftover_gate_keeps_plan_windows_precedence():
    task = _task(LEFTOVER_ROWS[0])
    assert validate_draft(task) == []
    task = replace(
        task,
        oracle=replace(
            task.oracle,
            profile=replace(
                task.oracle.profile,
                windows={"kcal": (0.0, 1.0), "protein_g": (100.0, 110.0)},
            ),
        ),
    )
    assert validate_draft(task) == []


def test_fitting_plan_normalizes_allergy_tags():
    catalog = {
        "peanut_butter": {
            "allergen_tags": [" Peanut "],
            "nutrients": {"kcal": 500.0, "protein_g": 20.0},
        },
    }
    windows = {"kcal": (80.0, 120.0), "protein_g": (3.0, 10.0)}
    assert fitting_plan(catalog, windows, ()) is not None
    assert fitting_plan(catalog, windows, ("peanut",)) is None
    assert fitting_plan(
        {
            "peanut_butter": {
                "allergen_tags": ["peanut"],
                "nutrients": {"kcal": 500.0, "protein_g": 20.0},
            },
        },
        windows,
        (" Peanut ",),
    ) is None


def test_every_frozen_item_still_validates():
    from pathlib import Path

    from nutrienv.bench.split import load_split

    for task in load_split(Path("data/splits/v0.5-gold.json")):
        assert validate_draft(task) == [], (task.id, validate_draft(task))


def test_update_gate_rejects_undeclared_preset_change():
    good = _update_until(lambda task: "200" in task.query and "shrimp" in task.query.lower())
    assert validate_draft(good) == []
    broken = replace(
        good,
        oracle=replace(
            good.oracle,
            profile=replace(good.oracle.profile, plan_preset={"goal": "muscle"}),
        ),
    )
    issues = validate_draft(broken)
    assert any("plan_preset" in item for item in issues)


def test_update_gate_rejects_unevidenced_removal():
    good = _custom_update(
        "Please add milk to my allergies after I reacted to it.",
        add_allergens=("milk",),
    )
    remaining = tuple(tag for tag in good.oracle.profile.allergies if tag != "peanut")
    broken = replace(
        good,
        oracle=replace(
            good.oracle,
            profile=replace(good.oracle.profile, allergies=remaining),
        ),
    )
    issues = validate_draft(broken)
    assert any("removal" in item or "removed" in item for item in issues)


def test_update_gate_rejects_two_window_query_with_one_magnitude():
    good = _custom_update(
        "Raise my calorie range by 200 at both ends and my protein range by 20 at both ends.",
        window_shifts={"kcal": 200.0, "protein_g": 20.0},
    )
    assert validate_draft(good) == []
    one_number = replace(
        good,
        query="Raise my calorie range by 200 at both ends and raise protein at both ends.",
    )
    issues = validate_draft(one_number)
    assert any("magnitude" in item for item in issues)


def test_update_gate_rejects_swapped_two_window_magnitudes():
    good = _custom_update(
        "Raise my calorie range by 200 at both ends and my protein range by 20 at both ends.",
        window_shifts={"kcal": 200.0, "protein_g": 20.0},
    )
    assert validate_draft(good) == []
    swapped = replace(
        good,
        query="Raise my calorie range by 20 at both ends and my protein range by 200 at both ends.",
    )
    issues = validate_draft(swapped)
    assert issues
    assert any("magnitude" in item for item in issues)


def test_update_gate_rejects_swapped_two_window_directions():
    good = _custom_update(
        "Raise my calorie range by 200 at both ends and my protein range by 20 at both ends.",
        window_shifts={"kcal": 200.0, "protein_g": 20.0},
    )
    assert validate_draft(good) == []
    swapped = replace(
        good,
        query="Raise my calorie range by 200 at both ends and lower my protein range by 20 at both ends.",
    )
    issues = validate_draft(swapped)
    assert issues
    assert any("down" in item or "up" in item or "direction" in item for item in issues)


def test_declared_update_axes_are_accepted():
    wanted = {
        "up-rm-peanut",
        "up-floor-protein-20",
        "up-two-kcal-200-prot-20",
        "up-add-milk-egg",
        "up-preset-cut-muscle",
    }
    for row in UPDATE_ROWS:
        if row.seed_id not in wanted:
            continue
        issues = validate_draft(_task(row))
        assert issues == [], (row.seed_id, issues)


def test_windows_unsatisfiable_accepts_any_nutrient_pair():
    catalog = load_catalog()
    assert windows_unsatisfiable(
        {"kcal": (0.0, 50.0), "protein_g": (70.0, 120.0)}, catalog
    )
    assert windows_unsatisfiable(
        {"kcal": (0.0, 200.0), "fiber_g": (90.0, 200.0)},
        catalog,
        floor_nutrient="fiber_g",
        ceiling_nutrient="kcal",
    )
    assert not windows_unsatisfiable(
        {"kcal": (0.0, 800.0), "fiber_g": (5.0, 40.0)},
        catalog,
        floor_nutrient="fiber_g",
        ceiling_nutrient="kcal",
    )
    # Catalog rounding puts soy isolate at 0.275 g protein/kcal and soybean
    # lecithin at 0.131 g fat/kcal. The gate must not trust those: protein
    # cannot exceed 0.25 g/kcal and fat cannot exceed 1/9 g/kcal.
    assert windows_unsatisfiable(
        {"kcal": (0.0, 200.0), "protein_g": (51.0, 80.0)}, catalog
    )
    assert not windows_unsatisfiable(
        {"kcal": (0.0, 200.0), "protein_g": (49.0, 80.0)}, catalog
    )
    assert windows_unsatisfiable(
        {"kcal": (0.0, 800.0), "fat_g": (90.0, 160.0)},
        catalog,
        floor_nutrient="fat_g",
        ceiling_nutrient="kcal",
    )
    assert not windows_unsatisfiable(
        {"kcal": (0.0, 800.0), "fat_g": (80.0, 160.0)},
        catalog,
        floor_nutrient="fat_g",
        ceiling_nutrient="kcal",
    )


def test_conflict_gate_rejects_a_satisfiable_other_pair():
    good = _task(next(row for row in CONSTRAIN_ROWS if row.kind == "conflict"))
    good.s0.profile = replace(
        good.s0.profile,
        allergies=(),
        windows={"kcal": (200.0, 800.0), "fiber_g": (4.0, 20.0)},
    )
    issues = validate_draft(good)
    assert any("unsatisfiable" in item or "satisfiable" in item for item in issues)
