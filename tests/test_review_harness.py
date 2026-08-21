"""Two-stage review committee: Stage A code-gate then injected voters."""

from __future__ import annotations

import pytest

from nutrienv.bench.pipeline.review_harness import (
    REASON_GRAMS_OFF_TABLE,
    make_reviewer,
    stage_a_code_gate,
)
from nutrienv.bench.realize import Oracle, Task
from nutrienv.world.types import LedgerRow, Profile, WorldState

_CATALOG = {
    "milk_whole": {
        "name": "Milk, whole",
        "portions": {"cup": 244.0},
        "aliases": ["milk", "whole milk"],
        "allergen_tags": ["milk"],
        "nutrients": {
            "kcal": 61.0,
            "protein_g": 3.2,
            "carb_g": 4.8,
            "fat_g": 3.3,
            "fiber_g": 0.0,
            "sodium_mg": 43.0,
        },
    },
}


def _log_task(
    task_id: str,
    query: str,
    *,
    food_id: str = "milk_whole",
    grams: float = 244.0,
) -> Task:
    s0 = WorldState(profile=Profile(user_id=task_id), catalog=_CATALOG)
    oracle = Oracle(ledger_tail=[LedgerRow(food_id, grams, "today-lunch")])
    return Task(task_id, "log", query, s0, oracle, ("multi_item_log",), "everyday")


def _boom(_prompt: str) -> str:
    raise AssertionError("LLM voter must not be used")


_TABLE = _log_task("log-table", "Please log a cup of milk for lunch.", grams=244.0)
_OFF = _log_task("log-off", "Please log a cup of milk for lunch.", grams=300.0)


def test_code_gate_off_table_grams_rejects_without_llm_vote() -> None:
    assert REASON_GRAMS_OFF_TABLE in stage_a_code_gate(_OFF)
    assert stage_a_code_gate(_TABLE) == []

    calls: list[str] = []

    def track(prompt: str) -> str:
        calls.append(prompt)
        return '{"eatable": true, "reason": "ok"}'

    review = make_reviewer(
        stage_a={"a1": track, "a2": track, "a3": track},
        stage_b={"b1": _boom, "b2": _boom, "b3": _boom},
    )([_OFF, _TABLE])

    assert _OFF.id in {row["id"] for row in review["dropped"]}
    assert _TABLE.id not in {row["id"] for row in review["dropped"]}
    off = review["per_candidate"][_OFF.id]
    assert off["dropped"] is True
    assert REASON_GRAMS_OFF_TABLE in off["stage_a"]["code_gate"]
    table = review["per_candidate"][_TABLE.id]
    assert table["dropped"] is False
    assert table["stage_a"]["code_gate"] == []
    assert calls, "table-gram candidate still receives Stage A votes"
    for prompt in calls:
        assert _TABLE.query not in prompt
        assert "300" not in prompt
