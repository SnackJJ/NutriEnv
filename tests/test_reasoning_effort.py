"""`--reasoning-effort`: sent with every request and recorded in the report.

Providers pick different defaults when no effort is sent (DeepSeek's API defaults to `high`;
the Command Code gateway's default is undocumented), so a report must say which one it ran at.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPT = ROOT / "scripts" / "eval_benchmark_suite.py"
MINI_SPLIT = ROOT / "data" / "splits" / "nutrienv-mini.json"


@pytest.fixture(scope="module")
def eval_module() -> Any:
    spec = importlib.util.spec_from_file_location("eval_suite_effort_under_test", EVAL_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their defining module through sys.modules; register first.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_summary_records_default_when_not_sent(eval_module: Any) -> None:
    summary = eval_module._build_summary("stub-model", "stub-split", None, [], {})
    assert summary["reasoning_effort"] == "default"


def test_summary_records_the_effort_sent(eval_module: Any) -> None:
    summary = eval_module._build_summary(
        "stub-model", "stub-split", None, [], {}, reasoning_effort="high"
    )
    assert summary["reasoning_effort"] == "high"


def test_cli_passes_the_effort_through(eval_module: Any, monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(eval_module, "run_benchmark_suite", lambda *a, **k: seen.update(k))
    eval_module.main(["--reasoning-effort", "max"])
    assert seen["reasoning_effort"] == "max"
    eval_module.main([])
    assert seen["reasoning_effort"] is None


@pytest.mark.skipif(not MINI_SPLIT.exists(), reason="needs the mini split and its catalog")
@pytest.mark.parametrize(("effort", "extra_body", "recorded"), [
    ("low", {"reasoning_effort": "low"}, "low"),
    (None, None, "default"),
])
def test_run_sends_the_effort_and_the_report_records_it(
    eval_module: Any, monkeypatch, tmp_path: Path, effort, extra_body, recorded
) -> None:
    specs: list[dict] = []

    def _fake_episode(task, harness_spec, catalog):
        specs.append(harness_spec)
        return eval_module.TaskTelemetry(
            task_id=task.id, family=task.family, query=task.query, persona=task.persona,
            passed=True, score_tag="pass", n_steps=1, max_budget=1, wall_time_seconds=0.0,
            total_prompt_tokens=0, total_completion_tokens=0, total_reasoning_tokens=0,
            total_tokens=0, tool_counts={}, invalid_tool_count=0, allergen_violated=False,
            steps=[],
        )

    monkeypatch.setattr(eval_module, "evaluate_task_with_episode_retry", _fake_episode)
    monkeypatch.setenv("STUB_EFFORT_KEY", "stub")
    out = tmp_path / "report.json"
    eval_module.run_benchmark_suite(
        str(MINI_SPLIT), "deepseek/stub", custom_url="http://stub",
        custom_key_env="STUB_EFFORT_KEY", workers=1, out=str(out), reasoning_effort=effort,
    )
    assert specs
    assert all(s.get("extra_body") == extra_body for s in specs)
    assert json.loads(out.read_text())["reasoning_effort"] == recorded


def test_summary_records_extra_body(eval_module: Any) -> None:
    body = {"top_p": 0.95, "chat_template_kwargs": {"enable_thinking": True}}
    summary = eval_module._build_summary(
        "stub-model", "stub-split", None, [], {}, extra_body=body
    )
    assert summary["extra_body"] == body
    assert eval_module._build_summary("m", "s", None, [], {})["extra_body"] == {}


def test_extra_body_parses_from_the_cli(eval_module: Any) -> None:
    args = eval_module.build_parser().parse_args(
        ["--extra-body", '{"top_k": 20, "chat_template_kwargs": {"enable_thinking": false}}']
    )
    assert args.extra_body == {"top_k": 20, "chat_template_kwargs": {"enable_thinking": False}}


def test_extra_body_may_not_override_reserved_fields(eval_module: Any) -> None:
    with pytest.raises(ValueError, match="temperature"):
        eval_module.run_benchmark_suite(
            str(MINI_SPLIT), "deepseek/stub", custom_key_env="PATH",
            extra_body={"temperature": 1.0},
        )
