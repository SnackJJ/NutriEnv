"""Harness-mode wiring: native function calling vs the text ReAct loop.

Covers the two things a ``--contract text-json`` vs ``--contract native-tools`` comparison
depends on: the mode actually selects the harness, and the comparison tool refuses to
print a delta when the two reports are not comparable.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Path-shaped only: the comparison reads the basename, nothing here opens it.
SCRATCH_DIR = ROOT / "reports"
EVAL_SCRIPT = ROOT / "scripts" / "eval_benchmark_suite.py"
COMPARE_SCRIPT = ROOT / "scripts" / "compare_harness_modes.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their defining module through sys.modules; register first.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def eval_module() -> Any:
    # `Any`, not ModuleType: the tests inject fakes onto the loaded script's globals, which a
    # static checker cannot verify for a module loaded from a path at runtime.
    return _load(EVAL_SCRIPT, "eval_benchmark_suite_under_test")


@pytest.fixture(scope="module")
def compare_module() -> Any:
    return _load(COMPARE_SCRIPT, "compare_harness_modes_under_test")


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------


def test_mode_selects_harness(eval_module: Any) -> None:
    """tool_call routes to the native FC episode; react keeps the text loop."""
    calls: list[str] = []

    def _fake_tool_call(*args, **kwargs):
        calls.append("native-tools")
        return "by-tool-call"

    def _fake_react(*args, **kwargs):
        calls.append("text-json")
        return "by-react"

    eval_module.run_episode_tool_call = _fake_tool_call
    eval_module.evaluate_task_with_telemetry = _fake_react

    assert eval_module.evaluate_task_with_episode_retry(None, {"contract": "native-tools"}, None) == "by-tool-call"
    assert eval_module.evaluate_task_with_episode_retry(None, {"contract": "text-json"}, None) == "by-react"
    # An unset mode must fall back to the text loop, never to native FC.
    assert eval_module.evaluate_task_with_episode_retry(None, {}, None) == "by-react"
    assert calls == ["native-tools", "text-json", "text-json"]


def test_programmatic_default_matches_cli_default(eval_module: Any) -> None:
    """A caller who passes no mode gets the same harness as the CLI default."""
    for fn in (eval_module.run_benchmark_suite, eval_module._build_summary):
        assert inspect.signature(fn).parameters["contract"].default == "native-tools"


def test_cli_exposes_both_contracts_and_defaults_to_native_tools(eval_module: Any) -> None:
    parser = eval_module.build_parser()
    action = next(a for a in parser._actions if a.dest == "contract")
    assert action.default == "native-tools"
    assert set(action.choices) == {"text-json", "native-tools"}


def test_cli_runs_as_a_script() -> None:
    """The module-level guard must still work after the parser was extracted."""
    proc = subprocess.run(
        [sys.executable, str(EVAL_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "native-tools" in proc.stdout


def test_summary_records_the_mode(eval_module: Any) -> None:
    """The mode must land in the report, or two runs cannot be told apart later."""
    source = inspect.getsource(eval_module._build_summary)
    assert '"contract": contract' in source
    assert '"scorer_version": SCORER_VERSION' in source
    assert '"loop_version": LOOP_VERSION' in source


# ---------------------------------------------------------------------------
# Comparison tool
# ---------------------------------------------------------------------------


def _report(mode: str, passed: int, *, split: str = "nutrienv-v1.0.json", model: str = "commandcode/vendor/model") -> dict:
    return {
        "model": model,
        "split": str(SCRATCH_DIR / split),
        "contract": mode,
        "total_tasks": 3,
        "passed_tasks": passed,
        "pass_rate_pct": round(passed / 3 * 100, 2),
        "clean_pass_rate_pct": round(passed / 3 * 100, 2),
        "void_count": 0,
        "overall_avg_steps": 7.0,
        "total_invalid_tool_calls": 0,
        "total_allergen_violations": 0,
        "family_breakdown": {
            "log": {"total": 2, "passed": min(passed, 2)},
            "composite": {"total": 1, "passed": max(0, passed - 2)},
        },
        "tasks": [
            {"task_id": f"t{i}", "family": "log", "passed": i < passed} for i in range(3)
        ],
    }


def test_comparison_reports_delta_for_same_setup(compare_module: Any) -> None:
    comp = compare_module.build_comparison([_report("text-json", 1), _report("native-tools", 2)])
    assert comp["comparable"] is True
    rendered = compare_module.render(comp)
    assert "+1 tasks" in rendered
    assert "composite" in rendered


def test_comparison_refuses_different_splits(compare_module: Any) -> None:
    comp = compare_module.build_comparison(
        [_report("text-json", 1), _report("native-tools", 2, split="v2.8-gold.json")]
    )
    assert comp["comparable"] is False
    rendered = compare_module.render(comp)
    assert "NOT COMPARABLE" in rendered
    assert "+1 tasks" not in rendered


def test_comparison_refuses_different_scorer_versions(compare_module: Any) -> None:
    old = _report("text-json", 1)
    new = _report("native-tools", 2)
    new["scorer_version"] = "s2"
    comp = compare_module.build_comparison([old, new])
    assert comp["comparable"] is False
    assert any("scorer versions" in note for note in comp["notes"])


def test_comparison_refuses_different_loop_versions(compare_module: Any) -> None:
    old = _report("text-json", 1)
    new = _report("native-tools", 2)
    new["loop_version"] = "l2"
    comp = compare_module.build_comparison([old, new])
    assert comp["comparable"] is False
    assert any("episode loops" in note for note in comp["notes"])


def test_comparison_refuses_same_mode(compare_module: Any) -> None:
    comp = compare_module.build_comparison([_report("text-json", 1), _report("text-json", 2)])
    assert comp["comparable"] is False
    assert any("nothing to compare" in note for note in comp["notes"])


def test_comparison_cli_exit_codes(compare_module: Any, tmp_path: Path) -> None:
    good_a = tmp_path / "react.json"
    good_b = tmp_path / "toolcall.json"
    bad = tmp_path / "legacy.json"
    good_a.write_text(json.dumps(_report("text-json", 1)), encoding="utf-8")
    good_b.write_text(json.dumps(_report("native-tools", 2)), encoding="utf-8")
    bad.write_text(json.dumps(_report("text-json", 1, split="v2.8-gold.json")), encoding="utf-8")

    assert compare_module.main([str(good_a), str(good_b)]) == 0
    assert compare_module.main([str(good_a), str(bad)]) == 2


def test_legacy_report_without_contract_is_flagged(compare_module: Any) -> None:
    legacy = _report("text-json", 1)
    del legacy["contract"]
    comp = compare_module.build_comparison([legacy, _report("native-tools", 2)])
    assert comp["comparable"] is True
    assert any("legacy" in note for note in comp["notes"])


# ---------------------------------------------------------------------------
# Context-window symmetry (both harnesses must honour --context-limit)
# ---------------------------------------------------------------------------


def test_fc_path_applies_the_same_context_window() -> None:
    """A window ablation must measure the window, not a harness asymmetry.

    The native-FC history pairs every assistant ``tool_calls`` message with the
    ``tool`` replies that answer it; sliding the window must not leave an orphan,
    which providers reject.
    """
    from nutrienv.harness.tool_call import _windowed_messages

    msgs = [
        {"role": "system", "content": "manual"},
        {"role": "user", "content": "Task: x"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a"}]},
        {"role": "tool", "tool_call_id": "a", "content": "obs"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "b"}]},
        {"role": "tool", "tool_call_id": "b", "content": "obs"},
    ]

    assert _windowed_messages(msgs, None) == msgs

    slid = _windowed_messages(msgs, 3)
    assert slid[0]["role"] == "system", "system manual must stay pinned"
    answered = {
        call["id"]
        for m in slid
        if m.get("role") == "assistant"
        for call in (m.get("tool_calls") or [])
    }
    orphans = [
        m for m in slid if m.get("role") == "tool" and m.get("tool_call_id") not in answered
    ]
    assert orphans == [], f"orphaned tool replies would be rejected: {orphans}"


def test_both_arms_carry_the_identical_task_contract() -> None:
    """Parity is the reason the shared spec exists; only the tool presentation may differ.

    The text arm and the native-FC arm are compared against each other, so anything the
    contract says has to reach both arms byte-for-byte. An edit that lands in one arm only
    turns a protocol comparison into an advice comparison (the 2026-09-17 incident: the text
    manual carried nine task-guidance sentences the FC arm did not).
    """
    from nutrienv.harness.prompt_freeze import SHARED_TASK_SPEC
    from nutrienv.harness.react import react_manual
    from nutrienv.harness.tools_schema import TOOL_SYSTEM_PROMPT

    assert SHARED_TASK_SPEC.strip(), "the shared contract must not be empty"
    assert react_manual("v2").endswith(SHARED_TASK_SPEC), (
        "the ReAct v2 manual no longer ends with the shared contract"
    )
    assert TOOL_SYSTEM_PROMPT.endswith(SHARED_TASK_SPEC), (
        "the native-FC system prompt no longer ends with the shared contract"
    )


def test_prompt_artifacts_stay_within_budget() -> None:
    """Budgets are per artifact, because the two artifacts fail differently.

    The shared contract growing moves BOTH arms and every earlier report, so it gets its own
    budget; an arm preamble growing only biases that arm. A single total on ``react_manual("v2")``
    cannot tell the two apart, which is what this replaces.
    """
    from nutrienv.harness.prompt_freeze import SHARED_TASK_SPEC
    from nutrienv.harness.react import react_manual
    from nutrienv.harness.tools_schema import TOOL_SYSTEM_PROMPT

    assert len(SHARED_TASK_SPEC.split()) <= 400
    assert len(TOOL_SYSTEM_PROMPT.split()) <= 440
    assert len(react_manual("v2").split()) <= 560


def test_prompt_fingerprint_is_frozen() -> None:
    """Prompts shape every number in the ablation and the protocol comparison.

    If this fails, the prompts moved. That is allowed only deliberately: bump
    PROMPT_VERSION, re-freeze the hash, and treat every earlier report as a different
    generation (the 2026-09-17 incident was exactly an unrecorded prompt drift).
    """
    from nutrienv.harness.prompt_freeze import (
        PROMPT_FINGERPRINT,
        PROMPT_VERSION,
        prompt_fingerprint,
    )

    assert PROMPT_VERSION, "a prompt generation must be named"
    assert prompt_fingerprint() == PROMPT_FINGERPRINT, (
        "harness prompts changed; bump PROMPT_VERSION and set PROMPT_FINGERPRINT to the new value"
    )


def test_native_tools_carry_exactly_the_text_manuals_op_lines() -> None:
    """Same ops, same descriptions, same argument names and optionality as the text manual.

    The shared spec covers the contract; this covers the per-op lines, where the arms used to
    differ (the FC arm had no update_plan, and told a reject to send `items: []` while the text
    arm said a reject "carries no items").
    """
    import re

    from nutrienv.harness.react import _SYSTEM_V2
    from nutrienv.harness.tools_schema import NUTRIENV_TOOLS

    lines = _SYSTEM_V2.split("Ops, with their arguments:\n", 1)[1].strip().splitlines()
    manual = {}
    for line in lines:
        name, _, rest = line[2:].partition(" ")
        args = ""
        if rest.startswith("{"):  # the signature, whose braces may nest
            depth = 0
            for end, char in enumerate(rest):
                depth += {"{": 1, "}": -1}.get(char, 0)
                if depth == 0:
                    break
            args, rest = rest[1:end], rest[end + 1 :]
        manual[name] = (args, rest.strip())
    tools = {t["function"]["name"]: t["function"] for t in NUTRIENV_TOOLS}
    assert set(tools) == set(manual)
    for name, (args, description) in manual.items():
        fn = tools[name]
        assert fn["description"] == description, name
        params = fn["parameters"]
        # Top-level argument names from the signature, `?` marking optional ones.
        names = re.findall(r"(\w+)(\??)(?::\s*\[[^\]]*\])?", re.sub(r"\[.*?\]", "", args))
        assert set(params["properties"]) == {n for n, _ in names}, name
        assert set(params.get("required", [])) == {n for n, opt in names if not opt}, name
        # Nothing beyond the manual line: no parameter carries its own description.
        assert all("description" not in p for p in params["properties"].values()), name


def test_text_equivalent_fingerprints_hold_only_while_the_text_arm_is_unchanged(monkeypatch) -> None:
    """An FC-only prompt change keeps earlier text-json reports current, and nothing else does."""
    import nutrienv.harness.prompt_freeze as pf
    import nutrienv.harness.react as react

    old = "0" * 64
    monkeypatch.setitem(pf.TEXT_EQUIVALENT_FINGERPRINTS, old, pf.text_arm_sha256())
    text = {"prompt_fingerprint": old, "contract": "text-json"}
    assert pf.effective_fingerprint(text) == pf.PROMPT_FINGERPRINT
    pf.assert_frozen(text)
    for other in ({"prompt_fingerprint": old, "contract": "native-tools"},
                  {"prompt_fingerprint": "someotherhash", "contract": "text-json"}):
        with pytest.raises(RuntimeError, match="prompt generation"):
            pf.assert_frozen(other)
    # Any edit to what the text arm says retires the equivalence by itself.
    monkeypatch.setattr(react, "PARSE_ERROR_RESAMPLE", "Continue, please.")
    with pytest.raises(RuntimeError, match="prompt generation"):
        pf.assert_frozen(text)


def test_comparison_accepts_a_text_equivalent_report_against_a_current_fc_report(
    compare_module: Any, monkeypatch
) -> None:
    import nutrienv.harness.prompt_freeze as pf
    from nutrienv.harness.prompt_freeze import PROMPT_FINGERPRINT

    old = "0" * 64
    monkeypatch.setitem(pf.TEXT_EQUIVALENT_FINGERPRINTS, old, pf.text_arm_sha256())
    text = _report("text-json", 1)
    text["prompt_fingerprint"] = old
    fc = _report("native-tools", 2)
    fc["prompt_fingerprint"] = PROMPT_FINGERPRINT
    assert compare_module.build_comparison([text, fc])["comparable"] is True
