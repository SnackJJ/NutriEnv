"""Runner: Env is the exam; subject is Harness+Model."""

from __future__ import annotations

from nutrienv.harness.runner import HARNESS_LABEL, MODEL_LABEL, run_split


def test_run_split_finishes_and_writes_manifest() -> None:
    result = run_split(n=6, seed=0)
    assert 0.0 <= result["pass_rate"] <= 1.0
    manifest = result["manifest"]
    assert manifest["env"]
    assert manifest["harness"] == HARNESS_LABEL == "script-v0"
    assert manifest["model"] == MODEL_LABEL == "script"
    assert set(manifest) >= {"env", "harness", "model"}


def test_run_split_reports_pass_at_k_and_pass_k() -> None:
    from nutrienv.bench import GOLD_SPLIT_PATH

    result = run_split(split_path=GOLD_SPLIT_PATH, k=2, task_ids=["v0-update-kcal-001"])
    assert result["k"] == 2
    assert "pass_at_k" in result
    assert "pass_k" in result
    assert 0.0 <= result["pass_at_k"] <= 1.0
    assert 0.0 <= result["pass_k"] <= 1.0
    assert result["details"][0]["k_hits"] in {0, 1, 2}


def test_run_split_reads_frozen_gold_file() -> None:
    from nutrienv.bench import GOLD_SPLIT_PATH

    result = run_split(split_path=GOLD_SPLIT_PATH)
    assert result["n"] >= 10
    assert result["split"]
    assert 0.0 <= result["pass_rate"] <= 1.0
    assert len(result["details"]) == result["n"]
    assert {row["id"] for row in result["details"]}


def test_react_reset_clears_episode_messages() -> None:
    from nutrienv.harness.react import ReActHarness

    harness = ReActHarness(api_key="dummy")
    harness.messages.append({"role": "user", "content": "old task"})
    harness.reset()
    assert len(harness.messages) == 1
    assert harness.messages[0]["role"] == "system"
    assert "DIAGNOSTIC LEAK" not in harness.messages[0]["content"]


def test_run_split_filters_task_ids() -> None:
    from nutrienv.bench import GOLD_SPLIT_PATH, load_split

    first = load_split(GOLD_SPLIT_PATH)[0].id
    result = run_split(split_path=GOLD_SPLIT_PATH, task_ids=[first])
    assert result["n"] == 1
    assert result["details"][0]["id"] == first


def test_run_split_redacts_oracle_from_reset_unless_leaked() -> None:
    from nutrienv.bench import GOLD_SPLIT_PATH

    class _Probe:
        def __init__(self) -> None:
            self.seen: list[object] = []

        def reset(self, task: object) -> None:
            self.seen.append(task)

        def act(self, observation: dict, query: str, history: list) -> dict:
            return {"op": "finish"}

    dry = _Probe()
    sealed = run_split(
        split_path=GOLD_SPLIT_PATH,
        task_ids=["v0-update-kcal-001"],
        harness=dry,
    )
    assert sealed["leak_oracle"] is False
    assert sealed["manifest"]["leak_oracle"] is False
    assert len(dry.seen) == 1
    view = dry.seen[0]
    assert getattr(view, "oracle", None) is None
    assert getattr(view, "s0", None) is None
    assert not hasattr(view, "oracle")
    assert view.id == "v0-update-kcal-001"
    assert view.query
    assert view.family == "update"

    leak = _Probe()
    opened = run_split(
        split_path=GOLD_SPLIT_PATH,
        task_ids=["v0-update-kcal-001"],
        harness=leak,
        leak_oracle=True,
    )
    assert opened["leak_oracle"] is True
    assert opened["manifest"]["leak_oracle"] is True
    assert len(leak.seen) == 1
    leaked = leak.seen[0]
    assert getattr(leaked, "oracle", None) is not None
    assert getattr(leaked, "s0", None) is not None


def test_run_split_rejects_bad_workers() -> None:
    import pytest

    with pytest.raises(ValueError, match="workers"):
        run_split(n=1, seed=0, workers=0)


def test_run_split_workers_match_serial_results() -> None:
    from nutrienv.bench import GOLD_SPLIT_PATH

    ids = ["v0-update-kcal-001", "v0-rec-dinner-001"]
    serial = run_split(split_path=GOLD_SPLIT_PATH, task_ids=ids, workers=1)
    parallel = run_split(split_path=GOLD_SPLIT_PATH, task_ids=ids, workers=2)
    assert parallel["workers"] == 2
    assert [(row["id"], row["passed"], row["tag"]) for row in parallel["details"]] == [
        (row["id"], row["passed"], row["tag"]) for row in serial["details"]
    ]


def test_run_split_workers_clone_harness_per_episode() -> None:
    from nutrienv.bench import GOLD_SPLIT_PATH

    class _Probe:
        born = 0

        def __init__(self) -> None:
            type(self).born += 1

        def clone(self) -> "_Probe":
            return type(self)()

        def reset(self, task: object) -> None:
            return None

        def act(self, observation: dict, query: str, history: list) -> dict:
            return {"op": "finish"}

    _Probe.born = 0
    ids = ["v0-update-kcal-001", "v0-rec-dinner-001"]
    run_split(
        split_path=GOLD_SPLIT_PATH,
        task_ids=ids,
        k=2,
        workers=2,
        harness=_Probe(),
    )
    assert _Probe.born == 1 + len(ids) * 2


class _Scripted:
    def __init__(self, actions: list[dict]) -> None:
        self.actions = list(actions)
        self.calls = 0

    def act(self, observation: dict, query: str, history: list) -> dict:
        self.calls += 1
        if not self.actions:
            return {"op": "get_profile"}
        return self.actions.pop(0)


def _update_task():
    from nutrienv.bench import GOLD_SPLIT_PATH, load_split

    return next(task for task in load_split(GOLD_SPLIT_PATH) if task.id == "v0-update-kcal-001")


def test_runner_stops_on_finish_and_keeps_the_first_write() -> None:
    from nutrienv.bench.scorer import Scorer
    from nutrienv.harness.runner import _run_episode

    task = _update_task()
    kcal = task.oracle.profile.windows["kcal"]
    harness = _Scripted(
        [
            {"op": "update_profile", "patch": {"windows": {"kcal": [kcal[0], kcal[1]]}}},
            {"op": "finish"},
            {"op": "update_profile", "patch": {"windows": {"kcal": [kcal[0] + 200, kcal[1] + 200]}}},
        ]
    )
    passed, tag, _ops = _run_episode(task, harness, Scorer(), max_steps=10)
    assert passed is True
    assert tag == "pass"
    assert harness.calls == 2


def test_runner_stops_after_idle_reads_following_a_write() -> None:
    from nutrienv.bench.scorer import Scorer
    from nutrienv.harness.runner import IDLE_READS_AFTER_WRITE, _run_episode

    task = _update_task()
    kcal = task.oracle.profile.windows["kcal"]
    actions = [
        {"op": "update_profile", "patch": {"windows": {"kcal": [kcal[0], kcal[1]]}}},
        *[{"op": "get_profile"} for _ in range(IDLE_READS_AFTER_WRITE)],
        {"op": "update_profile", "patch": {"windows": {"kcal": [kcal[0] + 200, kcal[1] + 200]}}},
    ]
    harness = _Scripted(actions)
    passed, tag, _ops = _run_episode(task, harness, Scorer(), max_steps=10)
    assert passed is True
    assert tag == "pass"
    assert harness.calls == 1 + IDLE_READS_AFTER_WRITE


def test_runner_does_not_stop_on_reads_before_any_write() -> None:
    from nutrienv.bench.scorer import Scorer
    from nutrienv.harness.runner import IDLE_READS_AFTER_WRITE, _run_episode

    task = _update_task()
    kcal = task.oracle.profile.windows["kcal"]
    harness = _Scripted(
        [
            *[{"op": "get_profile"} for _ in range(IDLE_READS_AFTER_WRITE + 1)],
            {"op": "update_profile", "patch": {"windows": {"kcal": [kcal[0], kcal[1]]}}},
            {"op": "finish"},
        ]
    )
    passed, tag, _ops = _run_episode(task, harness, Scorer(), max_steps=10)
    assert passed is True
    assert tag == "pass"


def test_runner_stops_after_submit_plan() -> None:
    from nutrienv.bench import GOLD_SPLIT_PATH, load_split
    from nutrienv.bench.scorer import Scorer
    from nutrienv.harness.runner import _run_episode

    task = next(
        item
        for item in load_split(GOLD_SPLIT_PATH)
        if item.id == "v0-rec-dinner-001"
    )
    harness = _Scripted(
        [
            {
                "op": "submit_plan",
                "items": [
                    {"food_id": "chicken_breast", "grams": 150.0},
                    {"food_id": "olive_oil", "grams": 20.0},
                ],
            },
            {"op": "update_plan", "patch": {"goal": "junk"}},
        ]
    )
    passed, tag, ops = _run_episode(task, harness, Scorer(), max_steps=10)
    assert passed is True
    assert tag == "pass"
    assert ops == ["submit_plan"]
    assert harness.calls == 1
