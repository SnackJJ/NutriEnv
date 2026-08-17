"""Public realize(material, query) seam: deterministic, query-injectable."""

from __future__ import annotations

from dataclasses import replace

import pytest

from nutrienv.bench.realize import (
    iter_realization_rows,
    material_from_row,
    realize,
    spoken_query,
)
from nutrienv.world.catalog_store import load_catalog

_ROWS = list(iter_realization_rows())
_IDS = [row.seed_id for row in _ROWS]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.mark.parametrize("row", _ROWS, ids=_IDS)
def test_same_material_same_query_is_field_equal(row, catalog):
    material = material_from_row(row, catalog=catalog)
    query = spoken_query(row)
    first = realize(material, query, catalog=catalog)
    second = realize(material, query, catalog=catalog)
    assert first == second


@pytest.mark.parametrize("row", _ROWS, ids=_IDS)
def test_same_material_different_query_changes_only_query(row, catalog):
    material = material_from_row(row, catalog=catalog)
    spoken = spoken_query(row)
    other = spoken + " (paraphrase)"
    first = realize(material, spoken, catalog=catalog)
    second = realize(material, other, catalog=catalog)
    assert first.query == spoken
    assert second.query == other
    assert replace(first, query=other) == second
    assert first.s0.profile == second.s0.profile
    assert first.s0.ledger == second.s0.ledger
    assert first.s0.last_plan == second.s0.last_plan
    assert first.oracle == second.oracle
    assert first.id == second.id
    assert first.family == second.family
    assert first.situations == second.situations
    assert first.persona == second.persona
