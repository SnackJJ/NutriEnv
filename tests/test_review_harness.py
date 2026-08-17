"""Table-driven review harness: synthetic candidates, injected models."""

from __future__ import annotations

import json

import pytest

from nutrienv.bench.pipeline.review_harness import (
    DISAGREEMENT_THRESHOLD,
    LOW_CONSISTENCY,
    LOW_ENTAILMENT,
    REASON_DISAGREEMENT,
    REASON_LOW_CONSISTENCY,
    REASON_LOW_ENTAILMENT,
    REASON_UNPARSEABLE,
    aggregate_reviews,
    format_review_prompt,
    make_reviewer,
    parse_review,
    resolved_items,
    review_candidates,
)
from nutrienv.bench.realize import Oracle, Task
from nutrienv.world.types import LedgerRow, Profile, WorldState

_CATALOG = {
    "milk_whole": {
        "name": "Milk, whole",
        "portions": {"cup": 244.0},
        "aliases": ["milk", "whole milk"],
    },
    "chicken_breast": {
        "name": "Chicken breast",
        "portions": {"piece": 172.0},
        "aliases": ["chicken"],
    },
}


def _task(
    task_id: str,
    query: str,
    *,
    food_id: str = "milk_whole",
    grams: float = 244.0,
    persona: str = "everyday",
    family: str = "log",
    last_plan: list | None = None,
) -> Task:
    s0 = WorldState(profile=Profile(user_id=task_id), catalog=_CATALOG)
    if last_plan is not None:
        oracle = Oracle(last_plan=last_plan)
    else:
        oracle = Oracle(ledger_tail=[LedgerRow(food_id, grams, "today-lunch")])
    return Task(task_id, family, query, s0, oracle, ("multi_item_log",), persona)


def _scores(consistency: float, naturalness: float, entailment: float, reason: str = "ok") -> str:
    return json.dumps(
        {
            "consistency": consistency,
            "naturalness": naturalness,
            "entailment": entailment,
            "reason": reason,
        }
    )


def _const(text: str):
    def fn(_prompt: str) -> str:
        return text

    return fn


HIGH = _scores(5, 5, 5, "query names the cup")
LOW_CONTRA = _scores(1, 4, 1, "query says half but resolved is 2.0x")
LOW_SHIFT = _scores(1, 4, 1, "query names a food not in the items")

_GOOD = _task("good-001", "Please log a cup of milk for lunch.", grams=244.0)
_CONTRA = _task(
    "contra-001",
    "Please log half a cup of milk for lunch.",
    grams=488.0,
)
_SHIFT = _task(
    "shift-001",
    "Please log a cup of chicken for lunch.",
    food_id="milk_whole",
    grams=244.0,
)
_JUNK = _task("junk-001", "Please log a cup of milk for lunch.", grams=244.0)


@pytest.mark.parametrize(
    "task, replies, expect_anomaly, expect_reasons",
    [
        (_GOOD, {"m1": HIGH, "m2": HIGH}, False, []),
        (
            _CONTRA,
            {"m1": LOW_CONTRA, "m2": LOW_CONTRA},
            True,
            [REASON_LOW_CONSISTENCY, REASON_LOW_ENTAILMENT],
        ),
        (
            _SHIFT,
            {"m1": LOW_SHIFT, "m2": LOW_SHIFT},
            True,
            [REASON_LOW_CONSISTENCY, REASON_LOW_ENTAILMENT],
        ),
        (
            _JUNK,
            {"m1": "not-json", "m2": "???"},
            True,
            [REASON_UNPARSEABLE],
        ),
    ],
    ids=["natural_good", "contradictory", "semantic_shift", "unparseable"],
)
def test_synthetic_candidates_mark_anomalies(task, replies, expect_anomaly, expect_reasons):
    models = {name: _const(text) for name, text in replies.items()}
    review = make_reviewer(models)([task])
    assert set(review) >= {"anomalies", "per_candidate"}
    entry = review["per_candidate"][task.id]
    assert set(entry) >= {"models", "aggregate", "anomaly"}
    assert set(entry["aggregate"]) >= {
        "consistency",
        "naturalness",
        "entailment",
        "disagreement",
        "unparseable",
        "reasons",
    }
    if expect_anomaly:
        assert entry["anomaly"]
        assert entry["aggregate"]["reasons"] == expect_reasons
        assert review["anomalies"] == [{"id": task.id, "reasons": expect_reasons}]
    else:
        assert entry["anomaly"] is False
        assert entry["aggregate"]["reasons"] == []
        assert review["anomalies"] == []


def test_prompt_carries_query_and_portion_facts() -> None:
    prompt = format_review_prompt(_GOOD)
    assert "Please log a cup of milk for lunch." in prompt
    assert "Milk, whole" in prompt
    assert "milk_whole" in prompt
    assert "1 × cup" in prompt
    assert "portion key=cup" in prompt
    assert "244 g" in prompt
    assert "everyday" in prompt
    items = resolved_items(_GOOD)
    assert items[0]["portion_key"] == "cup"
    assert items[0]["quantity"] == 1.0
    assert items[0]["grams"] == 244.0


def test_contradictory_resolved_amount_is_2x_cup() -> None:
    items = resolved_items(_CONTRA)
    assert items[0]["portion_key"] == "cup"
    assert items[0]["quantity"] == 2.0
    assert items[0]["grams"] == 488.0
    assert "half a cup" in _CONTRA.query


def test_empty_reply_retries_once() -> None:
    calls: list[str] = []

    def fake(prompt: str) -> str:
        calls.append(prompt)
        return "" if len(calls) == 1 else HIGH

    review = make_reviewer({"m1": fake})([_GOOD])
    assert len(calls) == 2
    entry = review["per_candidate"][_GOOD.id]
    assert entry["anomaly"] is False
    assert entry["models"]["m1"]["consistency"] == 5


def test_unparseable_after_retry_does_not_raise() -> None:
    calls: list[int] = []

    def fake(_prompt: str) -> str:
        calls.append(1)
        return "still not json"

    review = make_reviewer({"m1": fake})([_JUNK])
    assert len(calls) == 2
    entry = review["per_candidate"][_JUNK.id]
    assert entry["models"]["m1"]["unparseable"] is True
    assert entry["anomaly"]
    assert REASON_UNPARSEABLE in entry["aggregate"]["reasons"]
    assert review["anomalies"][0]["id"] == _JUNK.id


def test_model_disagreement_is_anomalous() -> None:
    models = {
        "high": _const(_scores(5, 4, 5, "fine")),
        "low": _const(_scores(1, 4, 5, "mismatch")),
    }
    review = make_reviewer(models)([_GOOD])
    entry = review["per_candidate"][_GOOD.id]
    assert entry["aggregate"]["disagreement"] == 4.0
    assert entry["aggregate"]["disagreement"] > DISAGREEMENT_THRESHOLD
    assert entry["aggregate"]["consistency"] == 3.0
    assert entry["aggregate"]["consistency"] >= LOW_CONSISTENCY
    assert entry["aggregate"]["reasons"] == [REASON_DISAGREEMENT]
    assert entry["anomaly"] == REASON_DISAGREEMENT


def test_low_naturalness_alone_is_not_anomalous() -> None:
    models = {
        "m1": _const(_scores(5, 1, 5, "stiff prose")),
        "m2": _const(_scores(4, 1, 4, "stiff prose")),
    }
    review = make_reviewer(models)([_GOOD])
    entry = review["per_candidate"][_GOOD.id]
    assert entry["aggregate"]["naturalness"] == 1.0
    assert entry["anomaly"] is False
    assert review["anomalies"] == []


def test_make_reviewer_injection_never_calls_network() -> None:
    def boom(_prompt: str) -> str:
        raise AssertionError("live reviewer must not be used")

    reviewer = make_reviewer({"stub": _const(HIGH)})
    # A live default factory is a different object; this bound one stays local.
    review = reviewer([_GOOD])
    assert review["anomalies"] == []
    assert "stub" in review["per_candidate"][_GOOD.id]["models"]
    with pytest.raises(AssertionError, match="live reviewer"):
        make_reviewer({"stub": boom})([_GOOD])


def test_parse_review_accepts_fenced_json_and_rejects_junk() -> None:
    fenced = "```json\n" + HIGH + "\n```"
    parsed = parse_review(fenced)
    assert parsed is not None
    assert parsed["consistency"] == 5
    assert parse_review("") is None
    assert parse_review("no object here") is None
    assert parse_review(_scores(9, 1, 1)) is None
    assert parse_review('{"consistency": 3, "naturalness": 3}') is None


def test_aggregate_means_ignore_unparseable_models() -> None:
    summary = aggregate_reviews(
        {
            "ok": {
                "consistency": 4.0,
                "naturalness": 5.0,
                "entailment": 4.0,
                "reason": "ok",
            },
            "bad": {
                "consistency": None,
                "naturalness": None,
                "entailment": None,
                "reason": "unparseable",
                "unparseable": True,
            },
        }
    )
    assert summary["consistency"] == 4.0
    assert summary["disagreement"] == 0.0
    assert summary["unparseable"] == ["bad"]
    assert summary["reasons"] == [REASON_UNPARSEABLE]


def test_empty_candidates_return_required_keys() -> None:
    review = review_candidates([], models={"m1": _const(HIGH)})
    assert review == {"anomalies": [], "per_candidate": {}}


def test_evaluate_last_plan_items_are_resolved() -> None:
    task = _task(
        "eval-001",
        "Evaluate this as my plan: a cup of milk.",
        family="evaluate",
        last_plan=[{"food_id": "milk_whole", "grams": 244.0}],
    )
    items = resolved_items(task)
    assert items[0]["food_id"] == "milk_whole"
    assert items[0]["portion_key"] == "cup"
    prompt = format_review_prompt(task)
    assert "Evaluate this as my plan" in prompt


def test_review_candidates_requires_models() -> None:
    with pytest.raises(ValueError, match="at least one model"):
        review_candidates([_GOOD], models={})


def test_low_consistency_threshold_constant() -> None:
    assert LOW_CONSISTENCY == 2.0
    assert LOW_ENTAILMENT == 2.0
    assert DISAGREEMENT_THRESHOLD == 2.0
