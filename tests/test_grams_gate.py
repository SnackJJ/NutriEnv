"""Whitelist-first plausibility gate: table values skip the LLM judge."""

from __future__ import annotations

from nutrienv.bench.grams_gate import (
    DEFAULT_K,
    DEFAULT_THRESHOLD,
    MAX_TOKENS,
    MODEL,
    TEMPERATURE,
    accept_from_verdicts,
    call_judge,
    judge_model,
    plausibility_gate,
    sample_verdicts,
)
from nutrienv.io.chat import DASHSCOPE_CHAT_URL, DEEPSEEK_CHAT_URL


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


def test_partial_parse_fail_uses_valid_denominator() -> None:
    verdicts = ["ok", "parse_fail", "ok", "suspect", "parse_fail"]
    assert accept_from_verdicts(verdicts, 0.6) is True
    assert accept_from_verdicts(verdicts, 0.7) is False


def test_all_parse_fail_rejects() -> None:
    assert accept_from_verdicts(["parse_fail"] * 5, 0.6) is False
    assert plausibility_gate(
        "steak", 30.0, _catalog(), judge=lambda *_: "", k=3
    ) == (False, "judge")


def test_sample_verdicts_calls_judge_k_times() -> None:
    calls = []

    def fake(_food, _grams):
        calls.append(1)
        return "ok"

    verdicts = sample_verdicts("steak", 30.0, judge=fake, k=5, parse_retries=0)
    assert verdicts == ["ok"] * 5
    assert len(calls) == 5


def test_default_model_and_parameters_unchanged() -> None:
    assert MODEL == "deepseek-v4-flash-0731"
    assert TEMPERATURE == 0.7
    assert MAX_TOKENS == 512
    assert DEFAULT_K == 5
    assert DEFAULT_THRESHOLD == 0.6


def test_judge_model_env_override(monkeypatch) -> None:
    monkeypatch.delenv("NUTRIENV_JUDGE_MODEL", raising=False)
    assert judge_model() == MODEL
    monkeypatch.setenv("NUTRIENV_JUDGE_MODEL", "qwen3.7-flash-2026-07-15")
    assert judge_model() == "qwen3.7-flash-2026-07-15"
    monkeypatch.setenv("NUTRIENV_JUDGE_MODEL", "  ")
    assert judge_model() == MODEL


def _capture_post(monkeypatch):
    captured: dict = {}

    def fake_post(url, payload, api_key, **_kwargs):
        captured["url"] = url
        captured["model"] = payload["model"]
        captured["temperature"] = payload["temperature"]
        captured["max_tokens"] = payload["max_tokens"]
        captured["api_key"] = api_key
        return '{"verdict": "ok", "reason": "x"}'

    monkeypatch.setattr("nutrienv.bench.grams_gate.post_chat_completion", fake_post)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-dummy")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-dummy")
    return captured


def test_call_judge_default_posts_to_dashscope(monkeypatch) -> None:
    captured = _capture_post(monkeypatch)
    monkeypatch.delenv("NUTRIENV_JUDGE_MODEL", raising=False)
    assert call_judge("steak", 160.0) == '{"verdict": "ok", "reason": "x"}'
    assert captured["model"] == "deepseek-v4-flash-0731"
    assert captured["url"] == DASHSCOPE_CHAT_URL
    assert captured["api_key"] == "dash-dummy"
    assert captured["temperature"] == 0.7
    assert captured["max_tokens"] == 512


def test_call_judge_native_deepseek_override_stays_on_deepseek(monkeypatch) -> None:
    captured = _capture_post(monkeypatch)
    monkeypatch.setenv("NUTRIENV_JUDGE_MODEL", "deepseek-v4-flash")
    call_judge("steak", 160.0)
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["url"] == DEEPSEEK_CHAT_URL
    assert captured["api_key"] == "ds-dummy"


def test_call_judge_qwen_override_uses_dashscope(monkeypatch) -> None:
    captured = _capture_post(monkeypatch)
    monkeypatch.setenv("NUTRIENV_JUDGE_MODEL", "qwen3.7-flash-2026-07-15")
    call_judge("steak", 160.0)
    assert captured["model"] == "qwen3.7-flash-2026-07-15"
    assert captured["url"] == DASHSCOPE_CHAT_URL
    assert captured["api_key"] == "dash-dummy"
