"""The ablation summariser's accounting.

Two ways an infrastructure failure used to reach a published number, both measured on real runs:

* ``run_ablation`` stamped every future at submission and compared that against the per-task
  budget, so the budget behaved as a since-launch deadline. A 23-task scaffold on 5 workers voided 10
  of its tasks without those tasks ever having been given their 900s.
* ``_summarize`` counted those voids in the denominator, so the same run read as 43.5% when the
  13 tasks that actually executed gave 76.9%.

ADR 0028 forbids both. These tests pin the contract rather than the implementation.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
ABLATION_SCRIPT = ROOT / "scripts" / "run_ablation.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their defining module through sys.modules; register first.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ablation_module() -> ModuleType:
    return _load(ABLATION_SCRIPT, "run_ablation_under_test")


def _row(task_id: str, *, family: str = "composite", passed: bool, void: bool = False) -> dict:
    return {
        "id": task_id,
        "family": family,
        "persona": "p",
        "query": "q",
        "passed": passed,
        "tag": "VOID_INFRA_ERROR" if void else ("pass" if passed else "window"),
        "n_steps": 0 if void else 5,
        "ops": [],
        "regen_fired": 0,
        "gate_fired_and_passed": False,
        "gate_status": {},
        "wall_time_seconds": 1.0,
        "void": void,
    }


def test_void_is_excluded_from_the_denominator(ablation_module):
    rows = [
        _row("a", passed=True),
        _row("b", passed=False),
        _row("c", passed=False, void=True),
        _row("d", passed=False, void=True),
    ]
    summary = ablation_module._summarize(rows, scaffold="none", model="m", split="s")

    assert summary["n"] == 4
    assert summary["clean_n"] == 2
    # 1 of the 2 tasks that actually ran, not 1 of 4.
    assert summary["pass_rate"] == pytest.approx(0.5)
    # The void-inclusive figure stays visible so the exclusion can be audited.
    assert summary["raw_pass_rate"] == pytest.approx(0.25)
    assert summary["void_count"] == 2
    assert summary["void_ids"] == ["c", "d"]


def test_family_rates_exclude_voids_too(ablation_module):
    rows = [
        _row("a", family="log", passed=True),
        _row("b", family="log", passed=False, void=True),
        _row("c", family="update", passed=True),
    ]
    summary = ablation_module._summarize(rows, scaffold="none", model="m", split="s")

    assert summary["family"]["log"]["void"] == 1
    assert summary["family"]["log"]["pass_rate"] == pytest.approx(1.0)
    assert summary["family"]["update"]["pass_rate"] == pytest.approx(1.0)


def test_all_void_does_not_divide_by_zero(ablation_module):
    summary = ablation_module._summarize(
        [_row("a", passed=False, void=True)], scaffold="none", model="m", split="s"
    )
    assert summary["clean_n"] == 0
    assert summary["pass_rate"] == 0.0
    assert summary["raw_pass_rate"] == 0.0


def test_void_bracket_orders_both_extremes_around_the_clean_rate(ablation_module):
    """ADR 0028 excludes voids from the denominator, which is gameable in the aggregate: a scaffold
    slow enough to void the tasks it would have failed raises its clean rate. So the clean rate
    is reported with both extremes, and neither may be quoted alone."""
    rows = [
        _row("a", passed=True),
        _row("b", passed=False),
        _row("c", passed=False, void=True),
        _row("d", passed=False, void=True),
    ]
    summary = ablation_module._summarize(rows, scaffold="none", model="m", split="s")

    assert summary["raw_pass_rate"] == pytest.approx(0.25)  # voids counted as failures
    assert summary["pass_rate"] == pytest.approx(0.50)  # voids excluded (the ADR 0028 rate)
    assert summary["pass_rate_voids_pass"] == pytest.approx(0.75)  # voids counted as passes
    assert (
        summary["raw_pass_rate"] <= summary["pass_rate"] <= summary["pass_rate_voids_pass"]
    )
    assert summary["void_rate"] == pytest.approx(0.5)


def test_avg_steps_ignores_void_rows(ablation_module):
    """A void row records 0 steps because nothing ran, so averaging over every row lets an
    infrastructure failure pull a reported number toward zero -- in proportion to how much of the
    scaffold failed to run, which is the direction that flatters nothing and hides everything."""
    rows = [
        _row("a", passed=True),
        _row("b", passed=False),
        _row("c", passed=False, void=True),
    ]
    summary = ablation_module._summarize(rows, scaffold="none", model="m", split="s")

    assert summary["avg_steps"] == pytest.approx(5.0)  # not 10/3
    assert summary["void_rate"] == pytest.approx(1 / 3)




def test_run_scaffold_gives_each_arm_harness_its_family_step_budget(ablation_module, monkeypatch):
    """Every scaffold's harness renders the step budget into its prompt, so the budget has to arrive
    per task: one for `update` (6), another for `composite` (30). Left at the constructor default
    the model is told 12 steps on a 30-step task, and the measured task is not the exam's."""
    seen: list[tuple[str, int]] = []

    class _StubHarness:
        def clone(self):
            return self

        def set_step_budget(self, max_steps: int) -> None:
            seen.append(("set", max_steps))

        def act(self, observation, query, history):  # pragma: no cover - never stepped
            raise AssertionError("the stub episode is monkeypatched")

    class _Task:
        def __init__(self, task_id: str, family: str) -> None:
            self.id = task_id
            self.family = family
            self.persona = "p"
            self.query = "q"

    monkeypatch.setattr(ablation_module, "build_scaffold", lambda *a, **k: _StubHarness())
    monkeypatch.setattr(
        ablation_module,
        "_run_episode",
        lambda task, harness, max_steps: {
            "id": task.id,
            "family": task.family,
            "persona": task.persona,
            "query": task.query,
            "passed": True,
            "tag": "pass",
            "n_steps": 1,
            "ops": [],
            "regen_fired": 0,
            "gate_fired_and_passed": False,
            "gate_status": {},
            "wall_time_seconds": 0.0,
        },
    )

    summary = ablation_module.run_scaffold(
        "none",
        [_Task("a", "update"), _Task("b", "composite")],
        model="m",
        workers=1,
        max_steps=None,
        timeout=1.0,
    )

    assert sorted(budget for _, budget in seen) == [6, 30]
    assert summary["config"]["budget"] == "per_family"
    # The loop identity is part of the provenance: since 2026-09-25 the ablation loop is
    # aligned with the exam text loop (message parity pinned by test_ablation_none_matches_exam).
    assert summary["config"]["loop"] == "ablation-exam-aligned"


def test_summary_records_the_generation_it_was_measured_on(ablation_module):
    summary = ablation_module._summarize([], scaffold="none", model="m", split="s")
    assert summary["prompt_version"]
    assert summary["prompt_fingerprint"] == ablation_module._PROMPT_FINGERPRINT
    assert summary["scorer_version"] == ablation_module.SCORER_VERSION
    assert summary["loop_version"] == ablation_module.LOOP_VERSION


def test_a_handin_env_refused_does_not_end_the_ablation_episode(ablation_module):
    from nutrienv.bench.realize import Oracle
    from nutrienv.world.types import Profile, WorldState

    class _Task:
        id = "stub-1"
        family = "recommend"
        query = "q"
        persona = "everyday"
        s0 = WorldState(profile=Profile(user_id="stub"), catalog={})
        oracle = Oracle()

    class _Harness:
        turns = [
            {"op": "submit_plan", "verdict": "reject", "reasons": ["allergy"]},  # no items
            {"op": "finish"},
        ]

        def act(self, observation, query, history):
            return self.turns[len(history)]

    row = ablation_module._run_episode(_Task(), _Harness(), 5)
    assert row["ops"] == ["submit_plan", "finish"]


def test_run_interleaved_runs_each_tasks_arms_back_to_back(ablation_module, monkeypatch):
    import threading

    calls: list[tuple[str, str, int]] = []

    class _Stub:
        def __init__(self, name):
            self.name = name

    class _Task:
        def __init__(self, task_id):
            self.id, self.family, self.persona, self.query = task_id, "composite", "p", "q"

    monkeypatch.setattr(ablation_module, "build_scaffold", lambda name, **k: _Stub(name))

    def episode(template, task, max_steps):
        calls.append((task.id, template.name, threading.get_ident()))
        return {"id": task.id, "family": task.family, "persona": "p", "query": "q",
                "passed": True, "tag": "pass", "n_steps": 1, "ops": [], "regen_fired": 0,
                "gate_fired_and_passed": False, "gate_status": {}, "wall_time_seconds": 0.0}

    monkeypatch.setattr(ablation_module, "_episode_with_retry", episode)
    tasks = [_Task(f"t{i}") for i in range(6)]
    out = ablation_module.run_interleaved(
        ["verify", "verify-placebo"], tasks, model="m", workers=3, max_steps=None,
        timeout=1.0, split="s.json",
    )
    for task in tasks:
        mine = [c for c in calls if c[0] == task.id]
        assert [c[1] for c in mine] == ["verify", "verify-placebo"]
        assert mine[0][2] == mine[1][2]  # same worker
    for name in ("verify", "verify-placebo"):
        assert out[name]["n"] == 6 and out[name]["split"] == "s.json"
        assert out[name]["config"]["interleave"] == ["verify", "verify-placebo"]
        assert all(row["run_window_id"] == out[name]["config"]["run_window_id"]
                   for row in out[name]["tasks"])
