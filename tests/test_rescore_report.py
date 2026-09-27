"""Rescoring re-judges recorded trajectories and refuses what it cannot stand in for."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rescore_report as rescore  # noqa: E402

from nutrienv.bench import SCORER_VERSION, Oracle  # noqa: E402
from nutrienv.harness.prompt_freeze import prompt_fingerprint  # noqa: E402
from nutrienv.harness.runner import LOOP_VERSION  # noqa: E402
from nutrienv.world.types import Profile, WorldState  # noqa: E402


class _Task:
    id = "t"
    family = "update"
    s0 = WorldState(profile=Profile(user_id="u"), catalog={})
    oracle = Oracle(profile=Profile(user_id="u", allergies=("peanut",)))


def _report(steps: list[dict], **overrides) -> dict:
    report = {
        "prompt_fingerprint": prompt_fingerprint(),
        "loop_version": LOOP_VERSION,
        "scorer_version": "s0-old",
        "parse_error_policy": "silent",
        "void_count": 0,
        "passed_tasks": 0,
        "family_breakdown": {"update": {"total": 1, "passed": 0, "void": 0}},
        "tasks": [{"task_id": "t", "family": "update", "passed": False,
                   "score_tag": "update_miss", "steps": steps}],
    }
    report.update(overrides)
    return report


ADD_PEANUT = {"op": "update_profile", "patch": {"allergies": ["peanut"]}}


def test_rescore_rejudges_the_replayed_end_state() -> None:
    out = rescore.rescore_report(_report([{"action": ADD_PEANUT}, {"action": {"op": "finish"}}]),
                                 {"t": _Task()})
    assert out["tasks"][0]["passed"] is True
    assert out["passed_tasks"] == 1
    assert out["family_breakdown"]["update"]["passed"] == 1
    assert out["scorer_version"] == SCORER_VERSION
    assert out["rescored_from_scorer_version"] == "s0-old"


def test_rescore_refuses_a_replay_that_diverges_from_the_run() -> None:
    # The run recorded this write as refused; Env accepts it now, so the trajectory is not the run's.
    with pytest.raises(ValueError, match="recorded as refused"):
        rescore.rescore_report(_report([{"action": ADD_PEANUT, "refused": True}]), {"t": _Task()})


def test_rescore_refuses_another_loop_or_prompt() -> None:
    with pytest.raises(SystemExit, match="loop_version"):
        rescore.rescore_report(_report([], loop_version="l1"), {"t": _Task()})
    with pytest.raises(RuntimeError, match="prompt generation"):
        rescore.rescore_report(_report([], prompt_fingerprint="old"), {"t": _Task()})


def test_rescore_refuses_a_task_the_split_does_not_hold() -> None:
    with pytest.raises(ValueError, match="no task 't'"):
        rescore.rescore_report(_report([]), {})
