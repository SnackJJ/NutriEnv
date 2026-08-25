from __future__ import annotations

from nutrienv.bench.pipeline.resolver import resolve_candidate
from nutrienv.bench.pipeline.types import Candidate

_CATALOG = {
    "wing_food": {
        "name": "Chicken wing, roasted",
        "nutrients": {},
        "allergen_tags": [],
        "aliases": [],
        "portions": {"qns": 70.0},
    }
}


def _candidate(query: str = "I had two chicken wings.") -> Candidate:
    return Candidate(
        items=(("wing_food", "two chicken wings"),),
        query=query,
        family="log",
        persona="everyday",
        pool_id="anchor-pool",
    )


def test_gram_anchor_accepts_table_valid_proposal() -> None:
    def anchor(food_id: str, expression: str, query: str) -> float:
        assert food_id == "wing_food"
        assert expression == "two chicken wings"
        return 70.0

    task, rejected = resolve_candidate(
        _candidate(),
        catalog=_CATALOG,
        task_id="anchor-0001",
        seen=set(),
        skip_gram_backresolve=True,
        gram_anchor=anchor,
    )
    assert rejected is None
    assert task is not None
    assert [row.grams for row in task.oracle.ledger_tail] == [70.0]


def test_gram_anchor_rejects_off_table_grams() -> None:
    def anchor(food_id: str, expression: str, query: str) -> float:
        return 99.0

    task, rejected = resolve_candidate(
        _candidate(),
        catalog=_CATALOG,
        task_id="anchor-0002",
        seen=set(),
        skip_gram_backresolve=True,
        gram_anchor=anchor,
    )
    assert task is None
    assert rejected is not None
    assert rejected.reason == "unresolvable"


def test_gram_anchor_swallows_anchor_failures() -> None:
    def anchor(food_id: str, expression: str, query: str) -> float:
        raise RuntimeError("anchor down")

    task, rejected = resolve_candidate(
        _candidate(),
        catalog=_CATALOG,
        task_id="anchor-0003",
        seen=set(),
        skip_gram_backresolve=True,
        gram_anchor=anchor,
    )
    assert task is None
    assert rejected is not None
    assert rejected.reason == "unresolvable"
