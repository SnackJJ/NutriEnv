"""Query-traceable spoken grams: log/freezer gate and evaluate food binding."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from nutrienv.bench.pipeline.freezer import freeze_tasks
from nutrienv.bench.realize import GOLD_WINDOWS, Oracle, Task, material_from_row, realize, spoken_query
from nutrienv.bench.realizations import EVALUATE_ROWS
from nutrienv.bench.split import load_exam
from nutrienv.bench.validator import validate_draft, validate_oracle_grams
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.types import LedgerRow, Profile, WorldState

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import landing_verify  # noqa: E402

CATALOG_V1 = ROOT / "data" / "fdc" / "catalog-v1.sqlite"
V05 = ROOT / "data" / "splits" / "v0.5-gold.json"
V05_SHA256 = "bb4f246044308670f567c24bc6b099e23f617268b532a088c27187dbda66e520"


@pytest.fixture(scope="module")
def catalog_v1():
    return load_catalog(CATALOG_V1)


def _log_task(query: str, food_id: str, grams: float, catalog) -> Task:
    return _log_items(query, [(food_id, grams)], catalog)


def _log_items(query: str, items: list[tuple[str, float]], catalog) -> Task:
    return Task(
        "draft-oral-log",
        "log",
        query,
        WorldState(
            profile=Profile(user_id="draft", windows=dict(GOLD_WINDOWS)),
            ledger=[],
            catalog=catalog,
        ),
        Oracle(
            ledger_tail=[
                LedgerRow(food_id, grams, "today-lunch") for food_id, grams in items
            ]
        ),
        situations=("fuzzy_portion",),
    )


def _eval_items(query: str, items: list[tuple[str, float]], catalog) -> Task:
    return Task(
        "draft-oral-eval",
        "evaluate",
        query,
        WorldState(
            profile=Profile(user_id="draft", windows=dict(GOLD_WINDOWS)),
            ledger=[],
            catalog=catalog,
        ),
        Oracle(last_plan=[{"food_id": food_id, "grams": grams} for food_id, grams in items]),
    )


def _eval_row(seed_id: str):
    return next(row for row in EVALUATE_ROWS if row.seed_id == seed_id)


def _authorizes(query: str, food_id: str, grams: float, catalog, *, evaluate: bool) -> bool:
    if not evaluate:
        return validate_oracle_grams(_log_task(query, food_id, grams, catalog)) == []
    issues = validate_draft(_eval_items(query, [(food_id, grams)], catalog))
    return not any("grams" in item and food_id in item for item in issues)


def test_spoken_grams_of_chicken_pass_oracle_gate(catalog_v1):
    task = _log_task(
        "Please log that I ate 150 g of chicken.",
        "chicken_breast",
        150.0,
        catalog_v1,
    )

    assert validate_oracle_grams(task) == []


def test_spoken_grams_chicken_can_freeze(catalog_v1, tmp_path: Path):
    task = _log_task(
        "Please log that I ate 150 g of chicken.",
        "chicken_breast",
        150.0,
        catalog_v1,
    )

    payload, path = freeze_tasks(
        [task],
        catalog=catalog_v1,
        output_path=tmp_path / "oral-chicken.json",
        overwrite=True,
    )

    assert path.is_file()
    assert payload["items"][0]["oracle"]["ledger_tail"][0]["grams"] == 150.0


def test_cup_of_chicken_still_matches_portion_table(catalog_v1):
    task = _log_task(
        "Please log a cup of chicken.",
        "chicken_breast",
        140.0,
        catalog_v1,
    )

    assert validate_oracle_grams(task) == []


def test_off_table_grams_without_spoken_amount_still_rejected(catalog_v1):
    task = _log_task(
        "Please log the chicken I ate.",
        "chicken_breast",
        150.0,
        catalog_v1,
    )

    issues = validate_oracle_grams(task)
    assert any("grams" in issue and "portion table" in issue for issue in issues)


def test_spoken_grams_of_rice_do_not_authorize_chicken(catalog_v1):
    task = _log_task(
        "Please log that I ate 150 g of rice.",
        "chicken_breast",
        150.0,
        catalog_v1,
    )

    issues = validate_oracle_grams(task)
    assert any("grams" in issue and "chicken_breast" in issue for issue in issues)


@pytest.mark.parametrize(
    "query",
    [
        "Please log that I ate 150g of chicken.",
        "Please log that I ate 150 grams of chicken.",
        "Log 150 g chicken after the gym.",
    ],
)
def test_spoken_gram_spellings_of_named_food_pass(catalog_v1, query):
    task = _log_task(query, "chicken_breast", 150.0, catalog_v1)

    assert validate_oracle_grams(task) == []


def test_evaluate_spoken_yogurt_grams_still_pass():
    task = realize(
        material_from_row(_eval_row("ev-gold-snack")),
        "Check this snack: 150 g of Greek yogurt and a banana.",
    )

    assert validate_draft(task) == []


def test_evaluate_spoken_grams_bind_to_the_named_food():
    good = realize(material_from_row(_eval_row("ev-pair-chicken-rice")), spoken_query(_eval_row("ev-pair-chicken-rice")))
    assert validate_draft(good) == []

    rebound = replace(
        good,
        query="Evaluate this as lunch: 150 g of rice and a cup of chicken.",
    )
    issues = validate_draft(rebound)
    # realize canonicalizes chicken_breast → 171477; 150 g is bound to rice.
    assert any("grams" in item and "171477" in item for item in issues)


def test_log_rice_grams_with_chicken_do_not_authorize_chicken(catalog_v1):
    task = _log_task(
        "Please log 150 g of rice with chicken",
        "chicken_breast",
        150.0,
        catalog_v1,
    )

    issues = validate_oracle_grams(task)
    assert any("grams" in issue and "chicken_breast" in issue for issue in issues)


def test_log_chicken_grams_and_cup_of_rice(catalog_v1):
    query = "Please log 150 g of chicken and a cup of rice"
    chicken = _log_task(query, "chicken_breast", 150.0, catalog_v1)
    assert validate_oracle_grams(chicken) == []

    both = _log_items(
        query,
        [("chicken_breast", 150.0), ("white_rice", 158.0)],
        catalog_v1,
    )
    assert validate_oracle_grams(both) == []


def test_evaluate_rice_grams_with_chicken_do_not_authorize_chicken():
    good = realize(
        material_from_row(_eval_row("ev-pair-chicken-rice")),
        spoken_query(_eval_row("ev-pair-chicken-rice")),
    )
    rebound = replace(good, query="Evaluate: 150 g of rice with chicken")
    issues = validate_draft(rebound)
    assert any("grams" in item and "171477" in item for item in issues)


def test_two_spoken_amounts_bind_to_their_own_foods(catalog_v1):
    query = "150 g of chicken and 200 g of rice"
    ok = [("chicken_breast", 150.0), ("white_rice", 200.0)]
    swapped = [("chicken_breast", 200.0), ("white_rice", 150.0)]

    assert validate_oracle_grams(_log_items(query, ok, catalog_v1)) == []
    assert validate_oracle_grams(_eval_items(query, ok, catalog_v1)) == []

    log_swap = validate_oracle_grams(_log_items(query, swapped, catalog_v1))
    eval_swap = validate_oracle_grams(_eval_items(query, swapped, catalog_v1))
    assert any("chicken_breast" in issue and "200" in issue for issue in log_swap)
    assert any("white_rice" in issue and "150" in issue for issue in log_swap)
    assert any("chicken_breast" in issue and "200" in issue for issue in eval_swap)
    assert any("white_rice" in issue and "150" in issue for issue in eval_swap)


def test_postposed_grams_with_adjunct_bind_preceding_food(catalog_v1):
    query = "chicken 150 g with rice"
    assert validate_oracle_grams(_log_task(query, "chicken_breast", 150.0, catalog_v1)) == []
    assert validate_oracle_grams(_eval_items(query, [("chicken_breast", 150.0)], catalog_v1)) == []

    rice_log = validate_oracle_grams(_log_task(query, "white_rice", 150.0, catalog_v1))
    rice_eval = validate_oracle_grams(_eval_items(query, [("white_rice", 150.0)], catalog_v1))
    assert any("white_rice" in issue and "150" in issue for issue in rice_log)
    assert any("white_rice" in issue and "150" in issue for issue in rice_eval)


def test_adjacent_grams_without_conjunction_do_not_fail_open(catalog_v1):
    query = "150 g of chicken 200 g of rice"
    for evaluate in (False, True):
        assert _authorizes(query, "chicken_breast", 150.0, catalog_v1, evaluate=evaluate)
        assert _authorizes(query, "white_rice", 200.0, catalog_v1, evaluate=evaluate)
        assert not _authorizes(query, "white_rice", 150.0, catalog_v1, evaluate=evaluate)
        assert not _authorizes(query, "chicken_breast", 200.0, catalog_v1, evaluate=evaluate)


def test_adjacent_postposed_grams_without_conjunction_do_not_fail_open(catalog_v1):
    query = "chicken 150 g rice 200 g"
    for evaluate in (False, True):
        assert not _authorizes(query, "white_rice", 150.0, catalog_v1, evaluate=evaluate)
        assert not _authorizes(query, "chicken_breast", 200.0, catalog_v1, evaluate=evaluate)
        # FOOD GRAM FOOD GRAM has no unique local NP for the first amount.
        assert not _authorizes(query, "chicken_breast", 150.0, catalog_v1, evaluate=evaluate)


def test_postposed_grams_and_second_amount_bind_separately(catalog_v1):
    query = "chicken 150 g and rice 200 g"
    ok = [("chicken_breast", 150.0), ("white_rice", 200.0)]
    swapped = [("chicken_breast", 200.0), ("white_rice", 150.0)]

    assert validate_oracle_grams(_log_items(query, ok, catalog_v1)) == []
    assert validate_oracle_grams(_eval_items(query, ok, catalog_v1)) == []

    log_swap = validate_oracle_grams(_log_items(query, swapped, catalog_v1))
    eval_swap = validate_oracle_grams(_eval_items(query, swapped, catalog_v1))
    assert any("chicken_breast" in issue and "200" in issue for issue in log_swap)
    assert any("white_rice" in issue and "150" in issue for issue in log_swap)
    assert any("chicken_breast" in issue and "200" in issue for issue in eval_swap)
    assert any("white_rice" in issue and "150" in issue for issue in eval_swap)


def test_span_with_two_food_identities_authorizes_neither(catalog_v1):
    query = "150 g of chicken rice"
    for evaluate in (False, True):
        assert not _authorizes(query, "chicken_breast", 150.0, catalog_v1, evaluate=evaluate)
        assert not _authorizes(query, "white_rice", 150.0, catalog_v1, evaluate=evaluate)


def test_v05_gold_oracle_grams_only_legacy_exemptions_fail():
    assert hashlib.sha256(V05.read_bytes()).hexdigest() == V05_SHA256
    failing = {
        task.id for task in load_exam(V05) if validate_oracle_grams(task)
    }
    assert failing == landing_verify.V05_ORACLE_GRAMS_EXEMPT_IDS
    assert len(failing) == 9


