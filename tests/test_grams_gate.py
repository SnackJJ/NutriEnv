"""Whitelist-first plausibility gate: table values skip the LLM judge."""

from __future__ import annotations

from nutrienv.bench.grams_gate import plausibility_gate


def _catalog():
    return {
        "steak": {"name": "Beef, steak, NFS", "portions": {"qns": 160.0}},
        "omelet": {"name": "Egg omelet", "portions": {"piece": 55.0}},
    }


def _boom(*_args, **_kwargs):
    raise AssertionError("judge should not be called on a table value")


def _seq_judge(replies):
    it = iter(replies)

    def fake(_food, _grams):
        return next(it)

    return fake


def test_table_steak_160_skips_judge():
    assert plausibility_gate("steak", 160.0, _catalog(), judge=_boom) == (True, "table")


def test_table_omelet_55_skips_judge():
    assert plausibility_gate("omelet", 55.0, _catalog(), judge=_boom) == (True, "table")


def test_off_table_30_calls_judge():
    calls = []

    def fake(food, grams):
        calls.append((food, grams))
        return "ok"

    assert plausibility_gate("steak", 30.0, _catalog(), judge=fake, k=5) == (True, "judge")
    assert len(calls) == 5


def test_judge_all_ok_accepts():
    assert plausibility_gate(
        "steak", 30.0, _catalog(), judge=_seq_judge(["ok"] * 5), k=5
    ) == (True, "judge")


def test_judge_threshold_boundary_accepts():
    replies = ["suspect", "suspect", "ok", "ok", "ok"]
    assert plausibility_gate(
        "steak", 30.0, _catalog(), judge=_seq_judge(replies), k=5, threshold=0.6
    ) == (True, "judge")


def test_judge_below_threshold_rejects():
    replies = ["suspect", "suspect", "suspect", "ok", "ok"]
    assert plausibility_gate(
        "steak", 30.0, _catalog(), judge=_seq_judge(replies), k=5, threshold=0.6
    ) == (False, "judge")


def test_empty_reply_retries_once():
    calls = []

    def fake(_food, _grams):
        calls.append(len(calls))
        return "" if len(calls) == 1 else "ok"

    assert plausibility_gate("steak", 30.0, _catalog(), judge=fake, k=1) == (True, "judge")
    assert len(calls) == 2
