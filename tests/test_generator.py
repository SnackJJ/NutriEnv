"""Realize-seam contracts that used to live on the retired Generator factory."""

from __future__ import annotations

from nutrienv.bench.realize import material_from_row, realize, spoken_query
from nutrienv.bench.realizations import (
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    FUZZY_ROWS,
    LEDGER_GAP_ROWS,
    LEFTOVER_ROWS,
    MULTI_ITEM_LOG_ROWS,
    NEAR_SYNONYM_ROWS,
    RECOMMEND_ROWS,
    UNIT_CONVERT_ROWS,
    UPDATE_ROWS,
)
from nutrienv.bench.situations import SITUATIONS
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, ledger_totals


def _task(row, *, catalog=None):
    foods = catalog if catalog is not None else load_catalog()
    material = material_from_row(row, catalog=foods)
    return realize(material, spoken_query(row), catalog=foods)


def _row(table, seed_id: str):
    return next(item for item in table if item.seed_id == seed_id)


def test_realize_covers_every_situation():
    by_situation = {
        "fuzzy_portion": FUZZY_ROWS[0],
        "multi_item_log": _row(MULTI_ITEM_LOG_ROWS, "mi-lunch-chicken-rice"),
        "condition_suitability": next(
            row for row in CONSTRAIN_ROWS if row.kind == "condition"
        ),
        "unit_convert": UNIT_CONVERT_ROWS[0],
        "near_synonym": NEAR_SYNONYM_ROWS[0],
        "conflict_windows": next(
            row for row in CONSTRAIN_ROWS if row.kind == "conflict"
        ),
        "ledger_gap": _row(LEDGER_GAP_ROWS, "lg-miss-breakfast"),
    }
    assert set(by_situation) == set(SITUATIONS)
    tasks = [_task(row) for row in by_situation.values()]
    assert {task.situations[0] for task in tasks} == set(SITUATIONS)
    assert all(len(task.s0.catalog) >= 15 for task in tasks)

    condition = _task(next(row for row in CONSTRAIN_ROWS if row.seed_id == "co-gold-shrimp"))
    assert condition.family == "constrain"
    assert condition.s0.profile.allergies
    assert condition.oracle.last_plan == []
    assert condition.oracle.allow_empty_plan is False
    assert condition.oracle.plan_must_be_safe
    assert condition.oracle.plan_must_fit_windows
    assert condition.s0.profile.windows["kcal"][1] <= 800


def test_update_oracle_normalizes_and_preserves_unmentioned_fields():
    task = _task(_row(UPDATE_ROWS, "up-gold-both"))
    row = _row(UPDATE_ROWS, "up-gold-both")
    added = set(task.oracle.profile.allergies) - set(task.s0.profile.allergies)
    removed = set(task.s0.profile.allergies) - set(task.oracle.profile.allergies)
    assert added == set(row.add_allergens)
    assert removed == set(row.remove_allergens)
    for key, delta in (row.window_shifts or {}).items():
        dlo, dhi = delta if isinstance(delta, tuple) else (delta, delta)
        s0_lo, s0_hi = task.s0.profile.windows[key]
        ora_lo, ora_hi = task.oracle.profile.windows[key]
        assert (ora_lo, ora_hi) == (s0_lo + dlo, s0_hi + dhi)
    for key, bounds in task.s0.profile.windows.items():
        if key in (row.window_shifts or {}):
            continue
        assert task.oracle.profile.windows[key] == bounds
    assert task.oracle.profile.plan_preset == task.s0.profile.plan_preset
    assert task.oracle.profile.medications == task.s0.profile.medications
    assert task.oracle.profile.version == task.s0.profile.version
    assert task.oracle.profile.user_id == task.s0.profile.user_id
    assert "shrimp" not in task.oracle.profile.allergies


def test_situation_realizations_have_concrete_oracles():
    spec = FUZZY_ROWS[0]
    fuzzy = _task(spec)
    food = fuzzy.s0.catalog.canonical_id(spec.food_id)
    grams = resolve_portion(spec.food_id, spec.phrase, fuzzy.s0.catalog)
    assert fuzzy.oracle.ledger_tail == [LedgerRow(food, grams, spec.slot)]

    unit_row = UNIT_CONVERT_ROWS[0]
    converted = _task(unit_row)
    unit_food = converted.s0.catalog.canonical_id(unit_row.food_id)
    unit_grams = resolve_portion(unit_row.food_id, unit_row.phrase, converted.s0.catalog)
    assert converted.oracle.ledger_tail == [LedgerRow(unit_food, unit_grams, unit_row.slot)]


def test_log_drafts_pin_profile_and_full_ledger():
    rows = [
        FUZZY_ROWS[0],
        MULTI_ITEM_LOG_ROWS[0],
        UNIT_CONVERT_ROWS[0],
        LEDGER_GAP_ROWS[0],
    ]
    for row in rows:
        task = _task(row)
        assert task.oracle.profile == task.s0.profile, row.seed_id
        assert task.oracle.ledger_tail
        assert task.oracle.ledger == (*task.s0.ledger, *task.oracle.ledger_tail), row.seed_id
        assert task.s0.ledger, row.seed_id
        slots = {item.eaten_at for item in task.s0.ledger}
        needed = {item.eaten_at for item in task.oracle.ledger_tail}
        if "ledger_gap" in task.situations:
            assert any(slot.startswith("today-") for slot in slots)
            assert needed.isdisjoint(slots)
        else:
            assert needed <= slots, (row.seed_id, needed, slots)
            assert any(slot.endswith("-snack") or slot.startswith("yesterday-") for slot in slots)


def test_fuzzy_and_unit_grams_come_from_resolve_portion():
    spec = FUZZY_ROWS[0]
    fuzzy = _task(spec)
    assert fuzzy.oracle.ledger_tail[0].food_id == fuzzy.s0.catalog.canonical_id(
        spec.food_id
    )
    assert fuzzy.oracle.ledger_tail[0].grams == resolve_portion(
        spec.food_id, spec.phrase, fuzzy.s0.catalog
    )

    unit_row = UNIT_CONVERT_ROWS[0]
    converted = _task(unit_row)
    assert converted.oracle.ledger_tail[0].grams == resolve_portion(
        unit_row.food_id, unit_row.phrase, converted.s0.catalog
    )


def test_non_log_drafts_pin_unchanged_ledger():
    update = _task(_row(UPDATE_ROWS, "up-gold-both"))
    recommend = _task(next(row for row in RECOMMEND_ROWS if row.persona == "everyday"))
    evaluate = _task(EVALUATE_ROWS[0])
    for task in (update, recommend, evaluate):
        assert task.oracle.ledger == tuple(task.s0.ledger), task.family
        assert task.oracle.profile is not None
    assert update.oracle.profile != update.s0.profile
    assert "shrimp" not in update.oracle.profile.allergies
    assert recommend.oracle.last_plan == []
    assert recommend.oracle.plan_must_be_safe
    assert recommend.oracle.plan_must_fit_windows
    assert recommend.persona == "everyday"


def test_conflict_windows_starts_with_a_violating_plan():
    row = next(item for item in CONSTRAIN_ROWS if item.kind == "conflict")
    task = _task(row)
    assert task.s0.last_plan
    assert task.oracle.ledger == tuple(task.s0.ledger)
    assert task.oracle.allow_empty_plan
    assert task.oracle.plan_must_fit_windows
    assert task.oracle.profile == task.s0.profile


def test_near_synonym_logs_the_catalog_food():
    row = NEAR_SYNONYM_ROWS[0]
    task = _task(row)
    assert task.family == "log"
    assert row.spoken.lower() in task.query.lower()
    assert row.food_id not in task.query.lower()
    food = task.s0.catalog.canonical_id(row.food_id)
    grams = resolve_portion(row.food_id, row.phrase, task.s0.catalog)
    assert task.oracle.ledger_tail == [LedgerRow(food, grams, row.slot)]
    assert task.oracle.profile == task.s0.profile
    assert task.oracle.ledger == (*task.s0.ledger, *task.oracle.ledger_tail)
    assert row.slot in {item.eaten_at for item in task.s0.ledger}


def test_generated_update_rejects_a_junk_log():
    from nutrienv.bench.scorer import Scorer
    from nutrienv.env import NutriEnv

    task = _task(_row(UPDATE_ROWS, "up-gold-both"))
    env = NutriEnv()
    env.reset(task.s0)
    env.step(
        {
            "op": "update_profile",
            "patch": {
                "allergies": list(task.oracle.profile.allergies),
                "windows": {
                    key: list(bounds)
                    for key, bounds in task.oracle.profile.windows.items()
                },
            },
        }
    )
    env.step(
        {
            "op": "log_meal",
            "food_id": "oats",
            "grams": 50.0,
            "eaten_at": "today-junk",
        }
    )
    score = Scorer().score(env.state(), task.oracle)
    assert score["passed"] is False
    assert score["tag"] == "log_miss"


def test_leftover_material_is_recommend_only():
    task = _task(LEFTOVER_ROWS[0])
    assert task.family == "recommend"
    assert task.persona == "leftover"


def test_table_personas_realize_as_recommend():
    for persona in ("cut", "gym", "flex", "htn"):
        row = next(item for item in RECOMMEND_ROWS if item.persona == persona)
        task = _task(row)
        assert task.persona == persona
        assert task.family == "recommend"


def test_leftover_recommend_uses_remainder_plan_windows():
    task = _task(LEFTOVER_ROWS[0])
    assert task.persona == "leftover"
    assert task.family == "recommend"
    assert task.s0.ledger
    assert task.oracle.ledger == tuple(task.s0.ledger)
    assert task.oracle.last_plan == []
    assert task.oracle.plan_must_be_safe
    assert task.oracle.plan_must_fit_windows
    assert task.oracle.profile == task.s0.profile
    assert task.oracle.plan_windows
    eaten = ledger_totals(task.s0.ledger, task.s0.catalog)
    for key, (lo, hi) in task.s0.profile.windows.items():
        used = eaten.get(key, 0.0)
        expected = (round(max(0.0, lo - used), 2), round(max(0.0, hi - used), 2))
        assert task.oracle.plan_windows[key] == expected, (key, expected)
