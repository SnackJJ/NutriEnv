"""ReAct harness presentation: pinned context and diagnostic oracle leak."""

from __future__ import annotations

from nutrienv.bench import Oracle
from nutrienv.harness.react import (
    REACT_VERSIONS,
    ReActHarness,
    _parse_action,
    context_messages,
    oracle_hint,
    react_manual,
)
from nutrienv.world.types import LedgerRow, Profile


def test_context_messages_pins_system_and_task() -> None:
    messages = [{"role": "system", "content": "rules"}]
    messages.append({"role": "user", "content": "Task:\nlog the milk"})
    for index in range(20):
        messages.append({"role": "user", "content": f"Observation:\n{index}"})
        messages.append({"role": "assistant", "content": '{"op": "get_profile"}'})

    sent = context_messages(messages, limit=12)
    assert sent[0] == {"role": "system", "content": "rules"}
    assert sent[1]["content"].startswith("Task:")
    assert len(sent) == 12
    assert sent[-1]["content"] == '{"op": "get_profile"}'
    assert all(row.get("content") != "Observation:\n0" for row in sent)


def test_oracle_hint_names_writes_not_the_catalog() -> None:
    profile = Profile(
        user_id="u",
        allergies=("peanut",),
        windows={"kcal": (400.0, 800.0)},
    )
    hint = oracle_hint(
        Oracle(
            profile=profile,
            ledger_tail=[LedgerRow("egg", 100.0, "today-breakfast")],
            last_plan=[],
            plan_must_fit_windows=True,
            plan_windows={"kcal": (291.0, 691.0)},
        )
    )
    assert "today-breakfast" in hint
    assert "egg" in hint
    assert "291" in hint
    assert "DIAGNOSTIC LEAK" in hint


def test_qwen_model_selects_dashscope_key_and_url() -> None:
    harness = ReActHarness(api_key="dash-dummy", model="qwen3-8b")
    assert "aliyuncs.com" in harness.base_url
    assert harness.api_key == "dash-dummy"


def test_judge_snapshot_ids_route_to_dashscope() -> None:
    from nutrienv.io.chat import DASHSCOPE_CHAT_URL

    for model in ("deepseek-v4-flash-0731", "qwen3.7-flash-2026-07-15"):
        harness = ReActHarness(api_key="dash-dummy", model=model)
        assert harness.base_url == DASHSCOPE_CHAT_URL
        assert harness.model == model


def test_react_v0_is_the_frozen_baseline_manual() -> None:
    harness = ReActHarness(api_key="dummy")
    assert harness.version == "v0"
    assert harness.label == "react-v0"
    assert harness.messages[0]["content"] == react_manual("v0")
    assert "portions" not in react_manual("v0")


def test_react_v1_extends_v0_with_catalog_portions_only() -> None:
    v0 = react_manual("v0")
    v1 = react_manual("v1")
    assert v1.startswith(v0)
    assert v1 != v0
    assert "portions" in v1
    assert "get_food" in v1
    assert "122" not in v1
    assert "13.5" not in v1
    harness = ReActHarness(api_key="dummy", version="v1")
    assert harness.label == "react-v1"
    assert "portions" in harness.messages[0]["content"]


def test_react_manual_teaches_evaluate_verdict_not_empty_items_as_reject() -> None:
    for version in REACT_VERSIONS:
        text = react_manual(version)
        assert "If last_plan already violates the windows" not in text
        assert "verdict=accept" in text
        assert "verdict=reject" in text
        assert "omit verdict" in text
        assert "25-30%" in text
        assert "30-40%" in text
        assert "allergy" in text
        for nutrient in (
            "kcal",
            "protein_g",
            "carb_g",
            "fat_g",
            "fiber_g",
            "sodium_mg",
        ):
            assert nutrient in text
        assert "_hi" in text
        assert "_lo" in text
    assert len(react_manual("v0").split()) <= 400


def test_react_version_rejects_unknown_and_clone_keeps_it() -> None:
    import pytest

    with pytest.raises(ValueError, match="version"):
        ReActHarness(api_key="dummy", version="v9")
    original = ReActHarness(api_key="dummy", version="v1")
    clone = original.clone()
    assert clone.version == "v1"
    assert clone.label == "react-v1"


def test_clone_starts_a_fresh_message_log() -> None:
    original = ReActHarness(api_key="dummy", model="deepseek-v4-flash")
    original.messages.append({"role": "user", "content": "old task"})
    clone = original.clone()
    assert clone is not original
    assert clone.messages is not original.messages
    assert clone.messages == [{"role": "system", "content": clone.messages[0]["content"]}]
    assert "old task" not in str(clone.messages)
    assert clone.model == original.model
    assert clone.api_key == original.api_key
    assert clone.leak_oracle is original.leak_oracle


def test_reset_leak_appends_hint_only_when_enabled() -> None:
    task_oracle = Oracle(ledger_tail=[LedgerRow("egg", 100.0, "today-breakfast")])

    class _Task:
        oracle = task_oracle

    dry = ReActHarness(api_key="dummy")
    dry.reset(_Task())
    assert "DIAGNOSTIC LEAK" not in dry.messages[0]["content"]

    leak = ReActHarness(api_key="dummy", leak_oracle=True)
    leak.reset(_Task())
    assert "DIAGNOSTIC LEAK" in leak.messages[0]["content"]
    assert "today-breakfast" in leak.messages[0]["content"]
    leak.reset()
    assert "DIAGNOSTIC LEAK" not in leak.messages[0]["content"]


def test_act_tells_model_remaining_default_step_budget() -> None:
    harness = ReActHarness(api_key="dummy")
    harness._complete = lambda: '{"op": "get_profile"}'  # type: ignore[method-assign]

    action = harness.act({"op": "reset"}, "What should I eat?", [{}] * 5)

    assert action == {"op": "get_profile"}
    message = harness.messages[-2]["content"]
    assert "Step budget: 7 action(s) remaining, including this turn." in message
    assert "Observation:\n" in message


def test_act_preserves_finish_as_a_harness_action() -> None:
    harness = ReActHarness(api_key="dummy")
    harness._complete = lambda: '{"op": "finish"}'  # type: ignore[method-assign]

    assert harness.act({"op": "get_profile"}, "Done", []) == {"op": "finish"}


def test_parse_action_handles_nested_json_braces_and_prose() -> None:
    text = 'Action follows: ```json\n{"op":"update_profile","patch":{"note":"{ok}"}}\n```'
    assert _parse_action(text) == {
        "op": "update_profile",
        "patch": {"note": "{ok}"},
    }


def test_parse_action_falls_back_after_invalid_output() -> None:
    assert _parse_action("not JSON") == {"op": "get_profile"}
    assert _parse_action('[{"op": "finish"}]') == {"op": "get_profile"}
