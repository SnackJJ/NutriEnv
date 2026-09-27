"""Independent checks that Oracle grams come from deterministic portion anchors."""

from __future__ import annotations

from dataclasses import replace

from nutrienv.bench.realize import material_from_row, realize, spoken_query
from nutrienv.bench.realizations import FUZZY_ROWS
from nutrienv.bench.validator import validate_oracle_grams


def _fuzzy_task():
    row = FUZZY_ROWS[0]
    material = material_from_row(row)
    return realize(material, spoken_query(row))


def test_oracle_grams_accepts_portion_table_amount():
    task = _fuzzy_task()

    assert validate_oracle_grams(task) == []


def test_oracle_grams_does_not_depend_on_matching_query_row():
    task = replace(
        _fuzzy_task(),
        query="I polished off the amount from that little blue bowl after my walk.",
    )

    assert validate_oracle_grams(task) == []


def test_oracle_grams_rejects_amount_outside_portion_table():
    task = _fuzzy_task()
    row = task.oracle.ledger_tail[0]
    task = replace(
        task,
        oracle=replace(
            task.oracle,
            ledger_tail=None,
            last_plan=[{"food_id": row.food_id, "grams": 0.01}],
        ),
    )

    issues = validate_oracle_grams(task)

    assert any("grams" in issue and "portion table" in issue for issue in issues)
