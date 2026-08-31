"""Thin runner: Env is the exam; the subject is Harness+Model."""

from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from nutrienv import __version__
from nutrienv.bench import Scorer, load_exam, load_split
from nutrienv.env import NutriEnv

from .protocol import Harness, HarnessView
from .script import ScriptHarness

__all__ = [
    "ENV_LABEL",
    "HARNESS_LABEL",
    "MODEL_LABEL",
    "run_split",
    "DEFAULT_MAX_STEPS",
    "FAMILY_MAX_STEPS",
    "FINISH_OPS",
    "READ_OPS",
    "WRITE_OPS",
    "IDLE_READS_AFTER_WRITE",
]

FINISH_OPS = frozenset({"finish", "done", "stop"})
READ_OPS = frozenset(
    {"search_foods", "get_food", "get_profile", "get_ledger", "get_dri"}
)
WRITE_OPS = frozenset(
    {"log_meal", "submit_plan", "update_profile", "update_plan"}
)
IDLE_READS_AFTER_WRITE = 3

ENV_LABEL = f"nutrienv-{__version__}"
HARNESS_LABEL = "script-v0"
MODEL_LABEL = "script"
DEFAULT_MAX_STEPS = 12

FAMILY_MAX_STEPS = {
    "update": 6,
    "log": 12,
    "evaluate": 12,
    "recommend": 30,
    "composite": 30,
}


def run_split(
    seed: int | None = None,
    n: int | None = None,
    k: int = 1,
    family: str | None = None,
    situation: str | None = None,
    *,
    split_path: Path | str | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    harness: Harness | None = None,
    harness_label: str | None = None,
    model_label: str | None = None,
    task_ids: list[str] | None = None,
    verbose: bool = False,
    workers: int = 1,
    leak_oracle: bool = False,
) -> dict:
    """Run a frozen split and return Pass / pass^k.

    With no ``split_path``, this loads the published 240-item exam via
    :func:`load_exam`. ``seed`` and ``n`` remain on the signature so older
    callers still bind; any non-None value raises (the draft factory is
    retired — use a frozen split). ``k`` independent episodes are run per
    Task. ``pass_rate`` is the fraction of those episodes that Pass.
    ``pass_at_k`` (pass@k) is the fraction of Tasks that Pass on at least
    one of the k episodes. ``pass_k`` (pass^k) is the fraction that Pass
    on every episode. ``workers`` runs Tasks concurrently (each Task keeps
    its own Env and harness clone). Published numbers should use a frozen
    file.

    ``reset`` receives a :class:`HarnessView` (id, family, persona, situations,
    query) unless ``leak_oracle`` is True, in which case it receives the full
    Task. The flag is recorded on the result so a leaked run is self-identifying.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be an int >= 1")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("max_steps must be an int >= 1")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be an int >= 1")

    if seed is not None or n is not None:
        raise ValueError("draft factory retired; use a frozen split")
    if split_path is not None:
        tasks = load_split(split_path)
    else:
        tasks = load_exam()
    if task_ids is not None:
        wanted = set(task_ids)
        tasks = [task for task in tasks if task.id in wanted]
        missing = wanted - {task.id for task in tasks}
        if missing:
            raise ValueError(f"unknown task ids: {sorted(missing)}")
    policy = harness if harness is not None else ScriptHarness()
    scorer = Scorer()

    details: list[dict] = []
    if workers == 1:
        for task in tasks:
            row = _eval_task(
                task, policy, scorer, max_steps, k, fresh=False, leak_oracle=leak_oracle
            )
            details.append(row)
            if verbose:
                _log_task(row, k)
    else:
        log_lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _eval_task, task, policy, scorer, max_steps, k, True, leak_oracle
                ): index
                for index, task in enumerate(tasks)
            }
            slotted: list[dict | None] = [None] * len(tasks)
            for future in as_completed(futures):
                index = futures[future]
                row = future.result()
                slotted[index] = row
                if verbose:
                    with log_lock:
                        _log_task(row, k)
        details = [row for row in slotted if row is not None]

    episode_pass = sum(int(row["k_hits"]) for row in details)
    task_all_k = sum(1 for row in details if row["passed"])
    task_any_k = sum(1 for row in details if row["passed_any"])
    total = max(len(tasks) * k, 1)
    pass_rate = episode_pass / total if tasks else 0.0
    pass_k = task_all_k / len(tasks) if tasks else 0.0
    pass_at_k = task_any_k / len(tasks) if tasks else 0.0

    manifest = {
        "env": ENV_LABEL,
        "harness": harness_label or HARNESS_LABEL,
        "model": model_label or MODEL_LABEL,
        "leak_oracle": leak_oracle,
    }
    result = {
        **manifest,
        "manifest": manifest,
        "pass_rate": pass_rate,
        "n": len(tasks),
        "seed": seed,
        "k": k,
        "family": family,
        "situation": situation,
        "split": str(split_path) if split_path is not None else None,
        "workers": workers,
        "leak_oracle": leak_oracle,
        "details": details,
    }
    if k > 1:
        result["pass_at_k"] = pass_at_k
        result["pass_k"] = pass_k
    return result


def _harness_view(task, leak_oracle: bool):
    if leak_oracle:
        return task
    return HarnessView(
        id=task.id,
        family=task.family,
        persona=task.persona,
        situations=tuple(task.situations or ()),
        query=task.query,
    )


def _eval_task(
    task,
    harness: Harness,
    scorer: Scorer,
    max_steps: int,
    k: int,
    fresh: bool,
    leak_oracle: bool = False,
) -> dict:
    k_hits = 0
    last_tag = None
    last_ops: list[str] = []
    last_steps = 0
    view = _harness_view(task, leak_oracle)
    task_max_steps = (
        max_steps
        if max_steps != DEFAULT_MAX_STEPS
        else FAMILY_MAX_STEPS.get(task.family, DEFAULT_MAX_STEPS)
    )
    for _ in range(k):
        policy = harness.clone() if fresh else harness
        reset = getattr(policy, "reset", None)
        if callable(reset):
            reset(view)
        passed, tag, ops = _run_episode(task, policy, scorer, task_max_steps)
        last_tag = tag
        last_ops = ops
        last_steps = len(ops)
        if passed:
            k_hits += 1
    return {
        "id": task.id,
        "family": task.family,
        "persona": task.persona,
        "passed": k_hits == k,
        "passed_any": k_hits >= 1,
        "k_hits": k_hits,
        "tag": last_tag,
        "n_steps": last_steps,
        "ops": last_ops,
    }


def _log_task(row: dict, k: int) -> None:
    mark = "PASS" if row["passed"] else ("PASS@" if row["k_hits"] else "FAIL")
    print(
        f"{mark} {row['id']} {row['k_hits']}/{k} family={row['family']} "
        f"persona={row['persona']} tag={row['tag']} steps={row['n_steps']} "
        f"ops={row['ops']}",
        file=sys.stderr,
        flush=True,
    )


def _run_episode(
    task, harness: Harness, scorer: Scorer, max_steps: int
) -> tuple[bool, str, list[str]]:
    env = NutriEnv()
    observation = env.reset(task.s0)
    history: list[dict] = []
    wrote = False
    idle_reads = 0
    for _ in range(max_steps):
        action = harness.act(observation, task.query, history)
        op = action.get("op") if isinstance(action, dict) else None
        if op in FINISH_OPS:
            history.append(
                {
                    "action": action,
                    "result": {
                        "ok": True,
                        "observation": {"op": "finish"},
                        "done": True,
                    },
                }
            )
            break
        result = env.step(action)
        history.append({"action": action, "result": result})
        if result.get("ok") and isinstance(result.get("observation"), dict):
            observation = result["observation"]
        else:
            observation = {"error": result.get("error")}
            idle_reads = 0
            continue
        if op in WRITE_OPS:
            wrote = True
            idle_reads = 0
            if op == "submit_plan":
                break
        elif op in READ_OPS:
            if wrote:
                idle_reads += 1
                if idle_reads >= IDLE_READS_AFTER_WRITE:
                    break
        else:
            idle_reads = 0
    score = scorer.score(env.state(), task.oracle)
    ops = [
        str(event["action"].get("op"))
        for event in history
        if isinstance(event.get("action"), dict)
    ]
    return bool(score["passed"]), str(score["tag"]), ops
