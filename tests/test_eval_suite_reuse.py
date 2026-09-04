"""Reuse-from a prior report must not copy crashed or, when asked, failed tasks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_benchmark_suite as suite  # noqa: E402


def _task(**overrides) -> dict:
    row = {
        "task_id": "t",
        "family": "log",
        "query": "q",
        "passed": True,
        "score_tag": "pass",
        "n_steps": 2,
        "max_budget": 12,
        "total_tokens": 10,
        "steps": [],
    }
    row.update(overrides)
    return row


def test_write_report_replaces_atomically(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    suite._write_report(path, {"ok": True, "n": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True, "n": 1}
    assert not path.with_name(path.name + ".tmp").exists()


def test_reuse_skips_zero_token_and_step_errors(tmp_path: Path) -> None:
    path = tmp_path / "rep.json"
    path.write_text(
        json.dumps(
            {
                "tasks": [
                    _task(task_id="ok"),
                    _task(task_id="crash", passed=False, n_steps=1, total_tokens=0, steps=[{"error": "timeout"}]),
                    _task(task_id="fail", passed=False, n_steps=3, score_tag="log_miss"),
                ]
            }
        ),
        encoding="utf-8",
    )
    reused = suite._reuse_short_tasks(path, 5)
    assert set(reused) == {"ok", "fail"}
    skipped = suite._reuse_short_tasks(path, 5, skip_failed=True)
    assert set(skipped) == {"ok"}
