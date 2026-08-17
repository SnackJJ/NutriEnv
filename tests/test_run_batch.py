"""S1: run_batch through injectable fakes. External behaviour only."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nutrienv.bench.pipeline import catalog_digest, pass_through_reviewer, run_batch
from nutrienv.bench.split import load_exam

V10 = Path("data/splits/v1.0-gold.json")


def _catalog() -> dict:
    return {
        "apple": {
            "name": "Apple, raw",
            "portions": {"piece": 182.0},
            "aliases": ["apple", "apples"],
            "allergen_tags": [],
        },
        "orange": {
            "name": "Orange, raw",
            "portions": {"piece": 131.0},
            "aliases": ["orange", "oranges"],
            "allergen_tags": [],
        },
        "milk_whole": {
            "name": "Milk, whole",
            "portions": {"cup": 244.0},
            "aliases": ["milk", "whole milk"],
            "allergen_tags": ["milk"],
        },
        "oats": {
            "name": "Oats, rolled",
            "portions": {"cup": 81.0},
            "aliases": ["oatmeal", "oats"],
            "allergen_tags": [],
        },
        "banana": {
            "name": "Banana, raw",
            "portions": {"piece": 118.0},
            "aliases": ["banana", "bananas"],
            "allergen_tags": [],
        },
        "egg": {
            "name": "Egg, whole",
            "portions": {"piece": 50.0},
            "aliases": ["eggs", "egg"],
            "allergen_tags": ["egg"],
        },
        "white_rice": {
            "name": "Rice, white",
            "portions": {"cup": 158.0},
            "aliases": ["rice"],
            "allergen_tags": [],
        },
        "broccoli": {
            "name": "Broccoli, cooked",
            "portions": {"cup": 156.0},
            "aliases": ["broccoli"],
            "allergen_tags": [],
        },
        "chicken_breast": {
            "name": "Chicken breast",
            "portions": {"piece": 172.0},
            "aliases": ["chicken"],
            "allergen_tags": [],
        },
        "tofu": {
            "name": "Tofu, firm",
            "portions": {"piece": 80.0},
            "aliases": ["tofu"],
            "allergen_tags": ["soy"],
        },
    }


def _ok_judge(_food: str, _grams: float) -> str:
    return "ok"


def _suspect_judge(_food: str, _grams: float) -> str:
    return "suspect"


def _expander(payloads):
    def expand(_pool, *, persona, family):
        return payloads

    return expand


def _spec(tmp_path: Path, catalog, **overrides) -> dict:
    spec = {
        "seed": 7,
        "sampler_rule_version": "sampler-v1",
        "catalog_sha": catalog_digest(catalog),
        "persona": "everyday",
        "family_quotas": {"log": 1},
        "model_route": {},
        "catalog": "fixture",
        "output_path": tmp_path / "v1.0-gold.json",
    }
    spec.update(overrides)
    return spec


def _run(tmp_path: Path, payloads, *, judge=_ok_judge, catalog=None, **overrides):
    foods = catalog if catalog is not None else _catalog()
    return run_batch(
        _spec(tmp_path, foods, **overrides),
        expander=_expander(payloads),
        judge=judge,
        reviewer=pass_through_reviewer,
        catalog=foods,
    )


_PASS = {
    "items": [{"food": "milk_whole", "expression": "a cup"}],
    "query": "Please log a cup of milk for lunch.",
}


def test_resolvable_candidate_passes_end_to_end(tmp_path: Path) -> None:
    result = _run(tmp_path, [_PASS])
    assert len(result.accepted) == 1
    task = result.accepted[0]
    assert task.family == "log"
    assert task.oracle.ledger_tail
    assert task.oracle.ledger_tail[0].grams == 244.0
    assert result.path is not None and result.path.is_file()
    assert result.payload["version"] == "v1.0-gold"
    assert result.review["anomalies"] == []


def test_unresolvable_expression_is_rejected(tmp_path: Path) -> None:
    bad = {
        "items": [{"food": "milk_whole", "expression": "a slice"}],
        "query": "Please log a slice of milk for lunch.",
    }
    result = _run(tmp_path, [bad])
    assert result.accepted == []
    assert any(item.reason == "unresolvable" for item in result.rejected)
    assert result.path is None


def test_absurd_grams_rejected_by_judge(tmp_path: Path) -> None:
    off_table = {
        "items": [{"food": "milk_whole", "expression": "30 g"}],
        "query": "Please log 30 g of milk for lunch.",
    }
    result = _run(tmp_path, [off_table], judge=_suspect_judge)
    assert result.accepted == []
    assert any(item.reason == "implausible" for item in result.rejected)


@pytest.mark.parametrize(
    "query",
    [
        "Please log a cup of milk_whole for lunch.",
        "Please log a cup of milk. kcal 1800",
    ],
    ids=["slug", "window"],
)
def test_leaking_query_is_rejected(tmp_path: Path, query: str) -> None:
    leak = {"items": [{"food": "milk_whole", "expression": "a cup"}], "query": query}
    result = _run(tmp_path, [leak])
    assert result.accepted == []
    assert any(item.reason == "leak" for item in result.rejected)


def test_near_duplicate_pools_are_deduped(tmp_path: Path) -> None:
    first = {
        "items": [{"food": "milk_whole", "expression": "a cup"}],
        "query": "Please log a cup of milk for lunch.",
    }
    second = {
        "items": [{"food": "whole milk", "expression": "one cup"}],
        "query": "Log one cup of whole milk at lunch.",
    }
    result = _run(tmp_path, [first, second], family_quotas={"log": 1})
    assert len(result.accepted) == 1
    assert any(item.reason == "duplicate" for item in result.rejected)


def test_same_seed_frozen_output_is_byte_identical(tmp_path: Path) -> None:
    catalog = _catalog()
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _run(first_dir, [_PASS], catalog=catalog)
    second = _run(second_dir, [_PASS], catalog=catalog)
    assert first.path is not None and second.path is not None
    left = first.path.read_bytes()
    right = second.path.read_bytes()
    assert left == right
    assert hashlib.sha256(left).hexdigest() == hashlib.sha256(right).hexdigest()


def test_catalog_sha_mismatch_raises(tmp_path: Path) -> None:
    catalog = _catalog()
    spec = _spec(tmp_path, catalog)
    spec["catalog_sha"] = "0" * 64
    with pytest.raises(ValueError, match="catalog sha256 mismatch"):
        run_batch(
            spec,
            expander=_expander([_PASS]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=catalog,
        )


def test_sample_v10_gold_loads_via_load_exam() -> None:
    assert V10.is_file()
    tasks = load_exam(V10)
    assert 2 <= len(tasks) <= 5
    assert {task.family for task in tasks} <= {"log", "evaluate"}
    payload = V10.read_text(encoding="utf-8")
    assert '"version": "v1.0-gold"' in payload
    assert "data/fdc/catalog-v1.sqlite" in payload
