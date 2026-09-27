"""What the text loop does when a turn is not a legal Action.

The published behaviour is a silent substitution: an unparseable turn becomes
``{"op": "get_profile"}``, the env executes it, and the report shows nothing. These tests
pin the measurement (`resolve_action`, the violation log) and the two policies that replace
the substitution with a visible retry, because a comparison between them is the point of the
``--parse-error-policy`` flag.

"Not a legal Action" is wider than "not parseable": an action that names a real op but breaks
its envelope is refused by Env too, and the loop's turn handling has to cover both.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from nutrienv.bench.realize import Oracle
from nutrienv.harness.react import (
    PARSE_ERROR_POLICIES,
    PARSE_ERROR_RESAMPLE,
    _parse_action,
    resolve_action,
    violation_feedback,
)
from nutrienv.world.types import Profile, WorldState

ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPT = ROOT / "scripts" / "eval_benchmark_suite.py"

PROSE = (
    "I'll recommend a lunch that fits the remaining daily window. Breakfast already used "
    "243 kcal, so I have room for about 1480 kcal."
)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def eval_module() -> ModuleType:
    return _load(EVAL_SCRIPT, "eval_benchmark_suite_parse_errors")


# ---------------------------------------------------------------------------
# resolve_action: the measurement
# ---------------------------------------------------------------------------


def test_resolve_action_reports_a_prose_turn() -> None:
    assert resolve_action(PROSE) == (None, "no_action")


def test_resolve_action_reports_an_unknown_op() -> None:
    action, why = resolve_action('{"op": "recommend_lunch"}')
    assert action == {"op": "recommend_lunch"}
    assert why == "unknown_op"


def test_resolve_action_accepts_a_fenced_action() -> None:
    action, why = resolve_action('Sure.\n```json\n{"op": "get_dri"}\n```')
    assert action == {"op": "get_dri"}
    assert why is None


def test_parse_action_keeps_the_published_substitution() -> None:
    """Reports depend on the fallback; the measurement must not change it."""
    assert _parse_action(PROSE) == {"op": "get_profile"}
    assert _parse_action('{"op": "get_dri"}') == {"op": "get_dri"}


def test_submit_plan_survives_a_model_written_bad_amount() -> None:
    """A non-numeric `grams` must not raise: the loop is not inside a retry that survives it."""
    action, why = resolve_action(
        '{"op": "submit_plan", "items": [{"food_id": "a", "grams": "two cups"}, '
        '{"food_id": "b", "grams": 120}, {"grams": 50}]}'
    )
    assert why is None
    assert action is not None and action["items"] == [{"food_id": "b", "grams": 120}]


def test_policies_are_named_and_distinct() -> None:
    assert set(PARSE_ERROR_POLICIES) == {"silent", "feedback", "resample"}
    assert "not a legal action" in violation_feedback("feedback", "x")
    with pytest.raises(ValueError, match="no feedback for policy"):
        violation_feedback("silent", "x")


# ---------------------------------------------------------------------------
# The loop: each policy's observable behaviour
# ---------------------------------------------------------------------------


def _stub_task(module: ModuleType):
    """A one-task split the loop can run without a catalog or a network.

    A real ``Oracle()`` and a real ``WorldState``, not stubs: the Scorer type-checks both, and a
    stub would make this test pass for a reason that cannot happen in a run.
    """

    class _Task:
        id = "stub-1"
        family = "recommend"
        query = "what should I eat for lunch?"
        persona = "everyday"
        s0 = WorldState(profile=Profile(user_id="stub"), catalog={})
        # No plan is judged: `last_plan=None` and no windows, so the episode scores on the
        # profile alone. This test is about the loop's turn handling, not about grading.
        oracle = Oracle()

    return _Task()


def _run(module: ModuleType, monkeypatch, policy: str, replies: list[str]):
    """Run one episode whose model turns are the given replies, in order."""
    sent: list[dict] = []
    turns = list(replies)

    def _fake_post(url, payload, api_key, **kwargs):
        sent.append(payload)
        text = turns.pop(0)
        return {
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "completion_tokens_details": {"reasoning_tokens": 0}},
        }

    monkeypatch.setattr(module, "post_chat_completion_raw", _fake_post)
    monkeypatch.setattr(module, "load_dotenv_keys", lambda *a, **k: None)
    spec = {
        "model": "stub-model",
        "url": "http://stub",
        "api_key": "stub",
        "timeout": 1.0,
        "retries": 0,
        "version": "v2",
        "context_limit": None,
        "temperature": 0.0,
        "contract": "text-json",
        "parse_error_policy": policy,
    }
    telemetry = module.evaluate_task_with_telemetry(_stub_task(module), spec, None)
    return telemetry, sent


def test_silent_policy_executes_the_fallback_and_records_it(
    eval_module: ModuleType, monkeypatch
) -> None:
    telemetry, sent = _run(eval_module, monkeypatch, "silent", [PROSE, '{"op": "finish"}'])
    assert telemetry.protocol_violations == 1
    assert [s.action["op"] for s in telemetry.steps] == ["get_profile", "finish"]
    assert telemetry.steps[0].protocol_violation is True
    assert telemetry.steps[0].violation_reason == "no_action"
    assert telemetry.steps[0].raw_text == PROSE[:1200]
    # Silent means silent: no correction was sent back.
    assert len(sent) == 2


def test_feedback_policy_tells_the_model_and_spends_the_turn(
    eval_module: ModuleType, monkeypatch
) -> None:
    telemetry, sent = _run(
        eval_module, monkeypatch, "feedback", [PROSE, '{"op": "finish"}']
    )
    assert telemetry.protocol_violations == 1
    # The violating turn executed nothing, so the env only saw `finish`.
    assert [s.action["op"] for s in telemetry.steps] == ["get_profile", "finish"]
    # The correction is appended at the end of the previous turn's history; the loop then adds
    # the next step's budget/observation message after it, so it is second from the end.
    correction = sent[1]["messages"][-2]
    assert correction["role"] == "user"
    assert correction["content"].startswith("Your previous message was not a legal action")
    assert "Breakfast already used" in correction["content"]  # the model's own words, echoed


def test_resample_policy_spends_the_same_call_without_diagnosing(
    eval_module: ModuleType, monkeypatch
) -> None:
    telemetry, sent = _run(
        eval_module, monkeypatch, "resample", [PROSE, '{"op": "finish"}']
    )
    assert telemetry.protocol_violations == 1
    assert sent[1]["messages"][-2]["content"] == PARSE_ERROR_RESAMPLE


def test_report_summary_carries_the_policy_and_the_rate(eval_module: ModuleType) -> None:
    telemetry, _ = _run_sync(eval_module)
    summary = eval_module._build_summary(
        "stub-model",
        "stub-split",
        None,
        [telemetry.task_id],
        {telemetry.task_id: telemetry},
        parse_error_policy="feedback",
    )
    assert summary["parse_error_policy"] == "feedback"
    assert summary["total_protocol_violations"] == 1
    assert summary["protocol_violation_rate"] > 0


def test_unknown_policy_raises(eval_module: ModuleType) -> None:
    with pytest.raises(ValueError, match="unknown parse_error_policy"):
        eval_module.run_benchmark_suite("data/splits/nutrienv-mini.json", parse_error_policy="nope")


def test_a_handin_env_refused_does_not_end_the_episode(
    eval_module: ModuleType, monkeypatch
) -> None:
    """A reject without the schema's `items` is an Illegal Action, not a hand-in.

    Env refuses it (`ok=False`) and leaves the world untouched, so the episode has to go on:
    ending here scored that untouched world as the model's answer, and `last_plan=None` failed
    the Scorer's `None != []` check for a reject.
    """
    telemetry, sent = _run(
        eval_module,
        monkeypatch,
        "silent",
        [
            '{"op": "submit_plan", "verdict": "reject", "reasons": ["allergy"]}',
            '{"op": "finish"}',
        ],
    )
    # Both turns reached the model, so the refused hand-in did not break the loop.
    assert len(sent) == 2
    assert [s.action["op"] for s in telemetry.steps] == ["submit_plan", "finish"]
    # And the refusal is what the next turn is shown, so the envelope can be repaired.
    assert "bad_schema" in json.dumps(sent[1]["messages"])
    # And it is counted: the op is known, so no other column sees it.
    assert [s.refused for s in telemetry.steps] == [True, False]


def test_native_tools_hand_in_env_refused_does_not_end_the_episode(
    eval_module: ModuleType, monkeypatch
) -> None:
    """The native-tools loop broke on any submit_plan, accepted or not, as the text loop did."""
    import nutrienv.harness.tool_call as tool_call

    calls = [
        ("submit_plan", {"verdict": "reject", "reasons": ["allergy"]}),
        ("finish", {}),
    ]
    sent: list[dict] = []

    def _fake_post(url, payload, api_key, **kwargs):
        sent.append(payload)
        name, args = calls.pop(0)
        call = {"id": f"c{len(sent)}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    monkeypatch.setattr(tool_call, "post_chat_completion_raw", _fake_post)
    spec = {"model": "stub-model", "url": "http://stub", "api_key": "stub", "timeout": 1.0,
            "retries": 0, "context_limit": None, "temperature": 0.0}
    telemetry = tool_call.run_episode_tool_call(
        _stub_task(eval_module), spec, None, eval_module.StepTelemetry, eval_module.TaskTelemetry
    )
    assert len(sent) == 2
    assert [s.action["op"] for s in telemetry.steps] == ["submit_plan", "finish"]
    assert [s.refused for s in telemetry.steps] == [True, False]


def _run_sync(module: ModuleType):
    """One feedback episode without pytest's monkeypatch fixture (module-scope fixture reuse)."""

    class _MP:
        def __init__(self) -> None:
            self._undo: list[tuple[object, str, object]] = []

        def setattr(self, obj, name, value):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)

        def undo(self) -> None:
            for obj, name, old in self._undo:
                setattr(obj, name, old)

    mp = _MP()
    try:
        return _run(module, mp, "feedback", [PROSE, '{"op": "finish"}'])
    finally:
        mp.undo()


@pytest.mark.parametrize("policy", ["silent", "feedback", "resample"])
def test_native_tools_loop_mirrors_the_text_loop(eval_module: ModuleType, monkeypatch, policy) -> None:
    """The same decisions through both contracts: same accounting, same world, same observations.

    Only how an action is expressed may differ between the arms. A prose turn is `no_action` in
    both, an unknown op is `unknown_op` in both, a refused hand-in does not end either episode,
    and the model is shown the same Task line and per-step observation text.
    """
    import nutrienv.harness.tool_call as tool_call

    decisions = [
        None,  # prose, no action
        ("recommend_lunch", {}),
        ("update_profile", {"patch": {"allergies": ["peanut"]}}),
        ("submit_plan", {"verdict": "reject", "reasons": ["allergy"]}),  # no items: refused
        ("finish", {}),
    ]
    text_replies = [
        PROSE if d is None else json.dumps({"op": d[0], **d[1]}) for d in decisions
    ]
    text_tel, text_sent = _run(eval_module, monkeypatch, policy, list(text_replies))

    fc_sent: list[dict] = []
    fc_turns = list(decisions)

    def _fake_fc(url, payload, api_key, **kwargs):
        fc_sent.append(payload)
        d = fc_turns.pop(0)
        if d is None:
            message = {"role": "assistant", "content": PROSE}
        else:
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"c{len(fc_sent)}", "type": "function",
                 "function": {"name": d[0], "arguments": json.dumps(d[1])}}]}
        return {"choices": [{"message": message}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                          "completion_tokens_details": None}}

    monkeypatch.setattr(tool_call, "post_chat_completion_raw", _fake_fc)
    spec = {"model": "stub-model", "url": "http://stub", "api_key": "stub", "timeout": 1.0,
            "retries": 0, "context_limit": None, "temperature": 0.0,
            "parse_error_policy": policy}
    fc_tel = tool_call.run_episode_tool_call(
        _stub_task(eval_module), spec, None, eval_module.StepTelemetry, eval_module.TaskTelemetry
    )

    def summary(tel):
        return {
            "n_steps": tel.n_steps,
            "tool_counts": tel.tool_counts,
            "invalid": tel.invalid_tool_count,
            "violations": tel.protocol_violations,
            "reasons": [v["reason"] for v in tel.violation_log],
            "ops": [s.action.get("op") for s in tel.steps],
            "refused": [s.refused for s in tel.steps],
            "flagged": [s.protocol_violation for s in tel.steps],
            "passed": tel.passed,
            "tag": tel.score_tag,
        }

    assert summary(fc_tel) == summary(text_tel)
    # The opening turns after the system prompt are the same text in both arms.
    assert fc_sent[0]["messages"][1:] == text_sent[0]["messages"][1:]


def test_native_tools_quirks_match_the_text_arm(eval_module: ModuleType, monkeypatch) -> None:
    """done/stop finish in both arms; decoded-object arguments are the call, not no_action."""
    import nutrienv.harness.tool_call as tool_call

    assert tool_call._resolve_call({"function": {"name": "done", "arguments": "{}"}})[1] is None
    call = {"function": {"name": "get_food", "arguments": {"food_id": "oats"}}}
    assert tool_call._resolve_call(call) == ({"op": "get_food", "food_id": "oats"}, None)

    turns = [{"tool_calls": {"not": "a list"}}, {"tool_calls": [
        {"id": "c", "function": {"name": "finish", "arguments": "{}"}}]}]

    def _fake(url, payload, api_key, **kwargs):
        return {"choices": [{"message": {"role": "assistant", "content": None, **turns.pop(0)}}]}

    monkeypatch.setattr(tool_call, "post_chat_completion_raw", _fake)
    spec = {"model": "m", "url": "u", "api_key": "k", "context_limit": None,
            "parse_error_policy": "silent"}
    tel = tool_call.run_episode_tool_call(
        _stub_task(eval_module), spec, None, eval_module.StepTelemetry, eval_module.TaskTelemetry
    )
    assert [s.violation_reason for s in tel.steps] == ["no_action", None]


def test_native_tools_id_less_call_is_paired_with_its_reply(eval_module: ModuleType, monkeypatch) -> None:
    """A provider rejects a tool reply whose id no assistant call carries."""
    import nutrienv.harness.tool_call as tool_call

    sent: list[dict] = []
    turns = [
        [{"function": {"name": "get_profile", "arguments": "{}"}}],  # no id
        [{"id": "x", "function": {"name": "finish", "arguments": "{}"}}],
    ]

    def _fake(url, payload, api_key, **kwargs):
        sent.append(payload)
        return {"choices": [{"message": {"role": "assistant", "content": None,
                                         "tool_calls": turns.pop(0)}}]}

    monkeypatch.setattr(tool_call, "post_chat_completion_raw", _fake)
    spec = {"model": "m", "url": "u", "api_key": "k", "context_limit": None}
    tool_call.run_episode_tool_call(
        _stub_task(eval_module), spec, None, eval_module.StepTelemetry, eval_module.TaskTelemetry
    )
    history = sent[1]["messages"]
    call_ids = [c["id"] for m in history if m.get("role") == "assistant" for c in m["tool_calls"]]
    reply_ids = [m["tool_call_id"] for m in history if m.get("role") == "tool"]
    assert call_ids == reply_ids and all(call_ids)
