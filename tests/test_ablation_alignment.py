"""The ablation's `none` scaffold and the exam text loop say the same things to a model.

DESIGN_v2 (2026-09-25) §3-A7: two independent loop implementations drifted before (the step
line, the unknown-op fallback). A prompt fingerprint cannot catch that -- the step line is not in
it -- so this drives both loops with one scripted model and compares every request.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from nutrienv.bench import load_split
from nutrienv.harness.react import ReActHarness

ROOT = Path(__file__).resolve().parents[1]
SPLIT = ROOT / "data" / "splits" / "nutrienv-v1.0.json"

# Every path the two loops could treat differently: a read, prose with no JSON (silent
# get_profile), an unknown op and an op-less object (both go to Env and are refused), a search,
# and a hand-in carrying reasons without a verdict (sanitized, accepted, episode ends).
REPLIES = [
    '{"op": "get_ledger"}',
    "Let me think about the dinner first.",
    '{"op": "frobnicate", "x": 1}',
    '{"q": "chicken"}',
    '{"op": "search_foods", "q": "chicken breast"}',
    '{"op": "submit_plan", "items": [{"food_id": "2705956", "grams": 150}], "reasons": ["x"]}',
]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _scripted(sent: list[list[dict]]):
    replies = iter(REPLIES)

    def post(url, payload, api_key, **_kwargs):
        sent.append([dict(m) for m in payload["messages"]])
        return {
            "choices": [{"message": {"content": next(replies)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    return post


@pytest.fixture(scope="module")
def task():
    return next(t for t in load_split(SPLIT) if t.id == "adr20-comp-5050")


def test_ablation_none_matches_exam(task, monkeypatch):
    exam = _load(ROOT / "scripts" / "eval_benchmark_suite.py", "eval_suite_alignment")
    ablation = _load(ROOT / "scripts" / "run_ablation.py", "run_ablation_alignment")

    exam_sent: list[list[dict]] = []
    monkeypatch.setattr(exam, "post_chat_completion_raw", _scripted(exam_sent))
    spec = {
        "model": "m", "url": "http://fake", "api_key": "k", "timeout": 1.0, "retries": 1,
        "version": "v2", "context_limit": None, "temperature": 0.0,
        "contract": "text-json", "parse_error_policy": "silent",
    }
    exam_row = exam.evaluate_task_with_telemetry(task, spec, None)

    ablation_sent: list[list[dict]] = []
    monkeypatch.setattr(
        "nutrienv.harness.react.post_chat_completion_raw", _scripted(ablation_sent)
    )
    harness = ReActHarness(api_key="k", base_url="http://fake", version="v2")
    budget = ablation.task_step_budget(task, None)
    harness.set_step_budget(budget)
    ablation_row = ablation._run_episode(task, harness, budget)

    assert len(exam_sent) == len(REPLIES)
    assert ablation_sent == exam_sent
    assert [s["action"] for s in ablation_row["steps"]] == [s.action for s in exam_row.steps]
    assert [s["observation_snippet"] for s in ablation_row["steps"]] == [
        s.observation_snippet for s in exam_row.steps
    ]
    assert ablation_row["passed"] == exam_row.passed
    assert ablation_row["tag"] == exam_row.score_tag
    # The refused turns are refused in both loops, not silently turned into reads.
    assert [s.get("refused", False) for s in ablation_row["steps"]] == [
        s.refused for s in exam_row.steps
    ]
    assert ablation_row["completions"] == len(REPLIES)
    assert ablation_row["total_tokens"] == 15 * len(REPLIES)
