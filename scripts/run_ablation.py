#!/usr/bin/env python3
"""Buddy-harness ablation on a frozen NutriEnv split.

Env / Oracle / Scorer are unchanged. Arms only wrap ReActHarness.act().

    .venv/bin/python scripts/run_ablation.py --scaffold check --limit 8
    .venv/bin/python scripts/run_ablation.py --scaffold all --model commandcode/inclusionai/ling-3.0-flash-sante:free
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.bench import SCORER_VERSION, Scorer, load_split  # noqa: E402
from nutrienv.env import NutriEnv  # noqa: E402
from nutrienv.harness.buddy import (  # noqa: E402
    BASELINE_SCAFFOLD,
    SCAFFOLDS,
    build_scaffold,
)
from nutrienv.harness.prompt_freeze import PROMPT_VERSION, assert_frozen  # noqa: E402
from nutrienv.harness.protocol import Harness  # noqa: E402
from nutrienv.harness.react import ReActInfraError  # noqa: E402
from nutrienv.harness.runner import (  # noqa: E402
    DEFAULT_MAX_STEPS,
    FINISH_OPS,
    LOOP_VERSION,
    task_step_budget,
)
from nutrienv.io.dotenv import load_dotenv_keys  # noqa: E402

# Resolved once at import rather than per summary. `_summarize` is called on every checkpoint,
# so recomputing the hash there would stamp tasks already produced under the previous prompts
# with the new generation -- the exact straddle prompt_freeze exists to prevent, and the same
# fix eval_benchmark_suite.py carries. assert_frozen() also fails loudly on real prompt drift.
_PROMPT_FINGERPRINT = assert_frozen()

DEFAULT_MODEL = "commandcode/inclusionai/ling-3.0-flash-sante:free"
DEFAULT_SPLIT = _ROOT / "data/splits/nutrienv-v1.1.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--scaffold",
        default="all",
        help="none | pin | calc | gate | check | pin-gate | pin-calc | resample | full | all",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--interleave",
        action="store_true",
        help="with a comma list in --scaffold: run each task's scaffolds back to back",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", default=None)
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="pin every task to this bound (default: each task family's budget)",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out-dir", type=Path, default=_ROOT / "reports")
    parser.add_argument(
        "--food-catalog",
        type=Path,
        default=None,
        help="catalog sqlite used to resolve foods the model never fetched (gate only); "
        "defaults to the lab snapshot, pass --no-food-catalog to disable",
    )
    parser.add_argument(
        "--per-task-timeout",
        type=float,
        default=None,
        help="wall-clock limit per episode (parallel runs only); a slower task is recorded as an "
        "infra VOID. Off by default: the exam has no such limit, so a limit voids tasks the "
        "exam would have scored",
    )
    parser.add_argument(
        "--no-food-catalog",
        action="store_true",
        help="disable the catalog lookup: the gate then only sees foods the model fetched",
    )
    return parser


def _catalog_for(args):
    """This run's catalog: ``--food-catalog`` if given, else the committed lab snapshot.

    Nothing is probed and no size floor is applied. `load_catalog` raises when the snapshot is
    missing rather than substituting the 15-food fixture, which is the failure the floor was
    standing in for after the 2026-09-08 ablation turned out to have been scored in a toy world.
    """
    from nutrienv.world.catalog_store import GOLD_CATALOG_PATH, load_catalog

    explicit = getattr(args, "food_catalog", None)
    path = Path(explicit) if explicit is not None else GOLD_CATALOG_PATH
    return path, load_catalog(path)


def _resolve_catalog(args):
    """The real catalog for this split, never the demo fixture."""
    return _catalog_for(args)[1]


def _build_food_lookup(args):
    """food_id -> catalog entry, or None when the lookup is disabled/unavailable."""
    if getattr(args, "no_food_catalog", False):
        return None
    path, catalog = _catalog_for(args)

    def lookup(food_id: str, _catalog=catalog):
        entry = _catalog.get(food_id)
        if entry is None:
            return None
        if "nutrients" in entry or "allergen_tags" in entry:
            return dict(entry)
        return None

    print(f"food lookup: {path.name} ({len(catalog)} foods)")
    return lookup


def _write_summary(args, scaffold: str, model_tag: str, summary: dict) -> None:
    """Persist a partial or final summary under the canonical name for this scaffold."""
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"ablation_{model_tag}_{scaffold}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")


def _scaffolds(name: str) -> list[str]:
    if name == "all":
        # Derive from SCAFFOLDS: a hard-coded list silently skipped newly added scaffolds
        # (pin / gate / full) when running `--scaffold all`.
        return [BASELINE_SCAFFOLD, *[s for s in SCAFFOLDS if s != BASELINE_SCAFFOLD]]
    if name not in SCAFFOLDS:
        raise SystemExit(f"unknown scaffold {name!r}; choose from {sorted(SCAFFOLDS)} or all")
    return [name]


def _run_episode(task, harness: Harness, max_steps: int) -> dict:
    reset = getattr(harness, "reset", None)
    if callable(reset):
        reset(
            type("View", (), {"id": task.id, "family": task.family, "query": task.query})()
        )
    env = NutriEnv()
    observation = env.reset(task.s0)
    history: list[dict] = []
    steps: list[dict] = []
    usage = _usage_log(harness)
    t0 = time.time()
    # Stop like the published suite: finish, submit_plan, or family step budget.
    # Do not treat post-write reads as a hand-in. Idle spinning is a policy
    # problem (prompt nudge), not a runner kill switch.
    for _ in range(max_steps):
        used_before = len(usage)
        action = harness.act(observation, task.query, history)
        op = action.get("op") if isinstance(action, dict) else None
        # The exam's per-step record, plus how many completions this step spent (a verify
        # bounce adds revise completions to the same env step).
        step = {
            "step_index": len(steps) + 1,
            "action": action,
            # What the model was shown before acting, as the exam records it.
            "observation_snippet": str(observation)[:200],
            "completions": len(usage) - used_before,
            **_sum_usage(usage[used_before:]),
        }
        steps.append(step)
        if op in FINISH_OPS:
            history.append({"action": action, "result": {"ok": True, "done": True}})
            break
        result = env.step(action)
        history.append({"action": action, "result": result})
        step["refused"] = not result.get("ok")
        if result.get("ok") and isinstance(result.get("observation"), dict):
            observation = result["observation"]
        else:
            observation = {"error": result.get("error")}
        # A hand-in ends the episode only when Env accepted it (runner.LOOP_VERSION l2): a
        # refused submit_plan leaves the world untouched and the error is the next observation.
        if op == "submit_plan" and result.get("ok"):
            break
    score = Scorer().score(env.state(), task.oracle)
    ops = [
        str(event["action"].get("op"))
        for event in history
        if isinstance(event.get("action"), dict)
    ]
    regen_fired = getattr(harness, "regen_fired", 0) or 0
    gate_exhausted = getattr(harness, "gate_exhausted", 0) or 0
    regen_used = getattr(harness, "regen_used", 0) or 0
    passed = bool(score["passed"])
    return {
        "id": task.id,
        "family": task.family,
        "persona": task.persona,
        "query": task.query,
        "passed": passed,
        "tag": score["tag"],
        "n_steps": len(ops),
        "ops": ops,
        "regen_fired": regen_fired,
        "regen_used": regen_used,
        "gate_exhausted": gate_exhausted,
        # The gate's own tally by Verdict.status (not_applicable / approved / skipped /
        # violation). Without it a scaffold cannot tell a gate that checked and found nothing from
        # one that could not check at all -- and the not_applicable paths are the majority of
        # checks, since every non-submit_plan action lands there.
        "gate_status": dict(getattr(harness, "gate_status", {}) or {}),
        # Refusals by hand-in shape (`submit_plan:verdict` vs `submit_plan`). Status alone cannot
        # separate a bounce on a recommendation, where the model can emit another plan, from a
        # bounce on an evaluate submit, which is scored against an exact candidate.
        "gate_fired_shapes": dict(getattr(harness, "gate_fired_shapes", {}) or {}),
        # Named for what it measures. It is NOT a measure of the gate's value: it only says the
        # gate fired at least once and the task passed. Whether the bounce rescued the task, or
        # the task would have passed anyway, needs the paired baseline -- the harness never
        # reads the Oracle, so it cannot know. The old name `regen_saved` read like a value.
        "gate_fired_and_passed": bool(regen_fired and passed),
        "wall_time_seconds": time.time() - t0,
        # A composite's first failing child hides later ones; the mechanism metric needs all.
        "sub_tags": list(score.get("sub_tags") or []),
        "verify_status": dict(getattr(harness, "verify_status", {}) or {}),
        "verify_events": list(getattr(harness, "verify_events", []) or []),
        "verify_drift": int(getattr(harness, "verify_drift", 0) or 0),
        "completions": len(usage),
        **_sum_usage(usage),
        "steps": steps,
    }


def _usage_log(harness) -> list:
    """The ReAct loop's per-completion usage list, through a Buddy wrapper if there is one."""
    inner = getattr(harness, "inner", harness)
    log = getattr(inner, "usage_log", None)
    return log if isinstance(log, list) else []


def _sum_usage(entries: list) -> dict:
    prompt = sum(e.get("prompt_tokens", 0) for e in entries)
    completion = sum(e.get("completion_tokens", 0) for e in entries)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": sum(e.get("reasoning_tokens", 0) for e in entries),
        "total_tokens": prompt + completion,
        # False if any completion fell back to the 4-chars/token estimate.
        "tokens_measured": all(e.get("tokens_measured", False) for e in entries),
    }


EPISODE_RETRIES = 2  # the exam's evaluate_task_with_episode_retry(max_retries=2)


def _void_row(task, reason: str) -> dict:
    return {
        "id": task.id,
        "family": task.family,
        "persona": task.persona,
        "query": task.query,
        "passed": False,
        "tag": "VOID_INFRA_ERROR",
        "n_steps": 0,
        "ops": [],
        "regen_fired": 0,
        "gate_fired_and_passed": False,
        "gate_status": {},
        "gate_fired_shapes": {},
        "wall_time_seconds": 0.0,
        "void": True,
        "void_reason": reason,
        "total_tokens": 0,
    }


def _episode_with_retry(template: Harness, task, max_steps: int | None) -> dict:
    """One episode, rerun from scratch on an infrastructure failure, as the exam does.

    Only `ReActInfraError` (a completion that failed after its request retries) is retried and,
    once retries run out, voided. Any other exception is a bug and propagates: voiding it would
    give this loop a different void set from the exam's. A failed attempt's tokens are dropped
    with the attempt, so a void row costs 0 tokens and a success counts only its last attempt.
    """
    # The loop bound and the harness prompt read the same helper, so the model can never be
    # told a budget the episode will not actually run with.
    task_max = task_step_budget(task, max_steps)
    last: str = ""
    for attempt in range(EPISODE_RETRIES + 1):
        policy = template.clone()
        policy.set_step_budget(task_max)
        try:
            return _run_episode(task, policy, task_max)
        except ReActInfraError as exc:
            last = str(exc)
            if attempt < EPISODE_RETRIES:
                time.sleep(2.0 * (attempt + 1))
    return _void_row(task, last)


def _tally(rows: list[dict], key: str) -> dict[str, int]:
    """Sum a dict-valued counter across rows (used for `gate_status`)."""
    out: dict[str, int] = {}
    for row in rows:
        for name, count in (row.get(key) or {}).items():
            out[name] = out.get(name, 0) + count
    return out


def _summarize(
    rows: list[dict], *, scaffold: str, model: str, split: str, config: dict | None = None
) -> dict:
    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    voids = [row for row in rows if row.get("void")]
    # Steps are only meaningful for episodes that ran: a void row records 0, so averaging over
    # every row drags the scaffold's average toward zero in proportion to how much of it failed to run
    # -- which is exactly the direction an infrastructure failure should not be able to push a
    # reported number.
    executed = [row for row in rows if not row.get("void")]
    # ADR 0028: an infrastructure void never enters the scoring denominator. `pass_rate` is the
    # clean rate for that reason, and `raw_pass_rate` keeps the void-inclusive figure so the
    # exclusion stays auditable instead of being invisible.
    clean = total - len(voids)
    # ADR 0028 excludes voids from the denominator, which is right for pairing but gameable in
    # the aggregate: a scaffold slow enough to void the tasks it would have failed raises its clean
    # rate. So the clean rate is bracketed by both extremes rather than reported alone.
    voids_pass = passed + len(voids)
    families: dict[str, dict] = {}
    tags: dict[str, int] = {}
    for row in rows:
        fam = families.setdefault(
            row["family"],
            {
                "total": 0,
                "void": 0,
                "passed": 0,
                "regen_fired": 0,
                "regen_used": 0,
                "gate_exhausted": 0,
                "gate_fired_and_passed": 0,
            },
        )
        fam["total"] += 1
        if row.get("void"):
            fam["void"] += 1
        fam["passed"] += row["passed"]
        fam["regen_fired"] += row["regen_fired"]
        fam["regen_used"] += row.get("regen_used", 0)
        fam["gate_exhausted"] += row.get("gate_exhausted", 0)
        fam["gate_fired_and_passed"] += row["gate_fired_and_passed"]
        tags[str(row["tag"])] = tags.get(str(row["tag"]), 0) + 1
        if fam["total"] - fam["void"]:
            fam["pass_rate"] = fam["passed"] / (fam["total"] - fam["void"])
    return {
        "scaffold": scaffold,
        "prompt_version": PROMPT_VERSION,
        "prompt_fingerprint": _PROMPT_FINGERPRINT,
        "scorer_version": SCORER_VERSION,
        "loop_version": LOOP_VERSION,
        "model": model,
        "split": split,
        "n": total,
        "passed": passed,
        "void_count": len(voids),
        "void_ids": [row["id"] for row in voids],
        "clean_n": clean,
        "void_rate": len(voids) / total if total else 0.0,
        "pass_rate": passed / clean if clean else 0.0,          # voids excluded (primary)
        "raw_pass_rate": passed / total if total else 0.0,        # voids as failures (lower bound)
        "pass_rate_voids_pass": voids_pass / total if total else 0.0,  # voids as passes (upper)
        "gate_status": _tally(rows, "gate_status"),
        "gate_fired_shapes": _tally(rows, "gate_fired_shapes"),
        "verify_status": _tally(rows, "verify_status"),
        "verify_bounced_tasks": sum(1 for row in rows if row.get("verify_events")),
        "verify_bounces": sum(len(row.get("verify_events") or []) for row in rows),
        "verify_drift": sum(row.get("verify_drift", 0) for row in rows),
        "total_tokens": sum(row.get("total_tokens", 0) for row in executed),
        "completions": sum(row.get("completions", 0) for row in executed),
        "config": config or {},
        "regen_fired": sum(row["regen_fired"] for row in rows),
        "regen_used": sum(row.get("regen_used", 0) for row in rows),
        "gate_exhausted": sum(row.get("gate_exhausted", 0) for row in rows),
        "gate_fired_and_passed": sum(row["gate_fired_and_passed"] for row in rows),
        "avg_steps": (sum(row["n_steps"] for row in executed) / len(executed)) if executed else 0.0,
        "tags": tags,
        "family": families,
        "tasks": rows,
    }


def run_scaffold(
    scaffold: str,
    tasks: list,
    *,
    model: str,
    workers: int,
    max_steps: int | None,
    timeout: float,
    food_lookup=None,
    per_task_timeout: float | None = None,
    on_progress=None,
) -> dict:
    # The gate may consult the food database so that a plan naming an unfetched food is
    # still judged; without this the gate silently degrades to "what the model happened
    # to look up", which makes its effect model-dependent rather than harness-caused.
    template = build_scaffold(
        scaffold,
        model=model,
        timeout=timeout,
        version="v2",
        food_lookup=food_lookup,
    )
    rows: list[dict] = []
    run_config = {
        "workers": workers,
        # eval_one uses the per-family budget unless --max-steps pinned one.
        "budget": "per_family" if max_steps is None else f"fixed({max_steps})",
        # Which loop produced this. This module's `_run_episode` deliberately does not cut an
        # episode after `IDLE_READS_AFTER_WRITE` post-write reads the way `runner._run_episode`
        # does, so one scaffold is comparable to another and not to an exam pass rate.
        # 2026-09-25: the step text, unknown-op handling, request/episode retries and void set
        # were aligned with the exam text loop (DESIGN_v2 §3-A); tests pin the message parity.
        "loop": "ablation-exam-aligned",
        "request_timeout": timeout,
        "per_task_timeout": per_task_timeout,
        "food_lookup": food_lookup is not None,
    }
    # When each task actually began running. The per-task budget applies to execution, not to
    # time spent queued behind other tasks: stamping every future at submission turned the
    # budget into a since-launch deadline, so with more tasks than workers the tail was voided
    # without ever having been given its 900s. That is how the first mini-harness run voided
    # 10 of 23 tasks and scored them as failures.
    started_at: dict[str, float] = {}
    started_lock = threading.Lock()

    def eval_one(task) -> dict:
        with started_lock:
            started_at[task.id] = time.time()
        return _episode_with_retry(template, task, max_steps)

    if workers <= 1:
        for task in tasks:
            row = eval_one(task)
            rows.append(row)
            _log_row(scaffold, row)
    else:
        log_lock = threading.Lock()
        slotted: list[dict | None] = [None] * len(tasks)

        def checkpoint() -> None:
            """Persist what is done so far.

            A watchdog kill used to lose the entire scaffold because the summary was written
            only at the end; now a hung or killed run keeps every finished task.
            """
            done = [row for row in slotted if row is not None]
            if not done or not on_progress:
                return
            with log_lock:
                on_progress(_summarize(done, scaffold=scaffold, model=model, split="", config=run_config))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(eval_one, task): index for index, task in enumerate(tasks)}
            pending = dict(futures)
            while pending:
                done, _ = wait(list(pending), timeout=5, return_when=FIRST_COMPLETED)
                for future in done:
                    index = pending.pop(future)
                    row = future.result()
                    slotted[index] = row
                    with log_lock:
                        _log_row(scaffold, row)
                    checkpoint()
                # A single episode can run for many minutes (a 30-step task on a slow model
                # has been measured at 7-27 min). Without this bound one such task stalls the
                # whole scaffold past any watchdog, so it is recorded as an infra void instead.
                now = time.time()
                for future, index in list(futures.items()):
                    if future not in pending:
                        continue
                    task = tasks[index]
                    began = started_at.get(task.id)
                    # `began is None` means no worker has picked this task up yet. Waiting is a
                    # throughput fact, not a task failure, so it is left alone.
                    if per_task_timeout is None or began is None or now - began <= per_task_timeout:
                        continue
                    pending.pop(future)
                    task_max = task_step_budget(task, max_steps)
                    timeout_row = {
                        "id": task.id,
                        "family": task.family,
                        "persona": task.persona,
                        "query": task.query,
                        "passed": False,
                        "tag": "VOID_INFRA_ERROR",
                        "n_steps": 0,
                        "ops": [],
                        "regen_fired": 0,
                        "gate_fired_and_passed": False,
                        "gate_status": {},
                        "gate_fired_shapes": {},
                        "wall_time_seconds": round(now - began, 1),
                        "void": True,
                        "void_reason": f"per-task timeout after {per_task_timeout:.0f}s",
                        "max_budget": task_max,
                        "total_tokens": 0,
                    }
                    slotted[index] = timeout_row
                    with log_lock:
                        _log_row(scaffold, timeout_row)
                        print(f"    VOID {task.id}: ran {now - began:.0f}s > {per_task_timeout:.0f}s budget", flush=True)
                    checkpoint()
        rows = [row for row in slotted if row is not None]
    return _summarize(rows, scaffold=scaffold, model=model, split="", config=run_config)


def run_interleaved(
    scaffolds: list[str],
    tasks: list,
    *,
    model: str,
    workers: int,
    max_steps: int | None,
    timeout: float,
    food_lookup=None,
    on_progress=None,
    split: str = "",
) -> dict[str, dict]:
    """Run every scaffold on a task back to back, in the same worker, before the next task.

    Scaffolds run one after another across hours drift apart with the endpoint (same-day repeats
    flip 27-32% of tasks); interleaving puts each task's arms minutes apart, so the drift is
    shared rather than confounded with the arm.
    """
    templates = {
        name: build_scaffold(
            name, model=model, timeout=timeout, version="v2", food_lookup=food_lookup
        )
        for name in scaffolds
    }
    window = time.strftime("%Y%m%dT%H%M%S")
    config = {
        "workers": workers,
        "budget": "per_family" if max_steps is None else f"fixed({max_steps})",
        "loop": "ablation-exam-aligned",
        "request_timeout": timeout,
        "per_task_timeout": None,
        "food_lookup": food_lookup is not None,
        "interleave": list(scaffolds),
        "run_window_id": window,
    }
    slotted: dict[str, list[dict | None]] = {name: [None] * len(tasks) for name in scaffolds}
    lock = threading.Lock()

    def eval_task(index: int, task) -> None:
        for name in scaffolds:
            began = time.time()
            row = _episode_with_retry(templates[name], task, max_steps)
            row["started_at"] = began
            row["run_window_id"] = window
            with lock:
                slotted[name][index] = row
                _log_row(name, row)
                if on_progress:
                    done = [r for r in slotted[name] if r is not None]
                    on_progress(
                        name,
                        _summarize(done, scaffold=name, model=model, split=split, config=config),
                    )

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for future in as_completed([pool.submit(eval_task, i, t) for i, t in enumerate(tasks)]):
            future.result()  # a non-infra exception is a bug: surface it
    return {
        name: _summarize(
            [r for r in slotted[name] if r is not None],
            scaffold=name, model=model, split=split, config=config,
        )
        for name in scaffolds
    }


def _log_row(scaffold: str, row: dict) -> None:
    mark = "PASS" if row["passed"] else "FAIL"
    print(
        f"{scaffold} {mark} {row['id']} family={row['family']} tag={row['tag']} "
        f"steps={row['n_steps']} regen={row['regen_fired']}",
        file=sys.stderr,
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    extra = [
        Path(item)
        for item in (os.environ.get("NUTRIENV_DOTENV") or "").split(os.pathsep)
        if item
    ]
    load_dotenv_keys(_ROOT / ".env.local", *extra)

    # The catalog comes from the split's recorded path (or --food-catalog), and load_catalog
    # raises rather than substituting the 15-food fixture. The 2026-09-08 ablation was scored in
    # that toy world, which is why a size floor used to stand here.
    catalog = _resolve_catalog(args)
    tasks = load_split(args.split, catalog=catalog)
    print(f"catalog: {len(catalog)} foods (split {pathlib.Path(args.split).name})")
    if args.ids:
        wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
        tasks = [task for task in tasks if task.id in wanted]
        missing = wanted - {task.id for task in tasks}
        if missing:
            print(f"unknown task ids: {sorted(missing)}", file=sys.stderr)
            return 2
    elif args.limit is not None:
        if args.limit < 1:
            print("--limit must be >= 1", file=sys.stderr)
            return 2
        tasks = tasks[: args.limit]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    food_lookup = _build_food_lookup(args)
    model_tag = args.model.replace("/", "_")
    summaries: list[dict] = []
    if args.interleave:
        names = [name.strip() for name in args.scaffold.split(",") if name.strip()]
        for name in names:
            _scaffolds(name)  # validates
        print(f"\n=== interleaved {names} model={args.model} n={len(tasks)} ===", flush=True)
        results = run_interleaved(
            names,
            tasks,
            model=args.model,
            workers=args.workers,
            max_steps=args.max_steps,
            timeout=args.timeout,
            food_lookup=food_lookup,
            on_progress=lambda name, partial: _write_summary(args, name, model_tag, partial),
            split=str(args.split),
        )
        for name in names:
            summary = results[name]
            summary["split"] = str(args.split)
            _write_summary(args, name, model_tag, summary)
            summaries.append(summary)
    for scaffold in ([] if args.interleave else _scaffolds(args.scaffold)):
        print(f"\n=== scaffold={scaffold} model={args.model} n={len(tasks)} ===", flush=True)
        summary = run_scaffold(
            scaffold,
            tasks,
            model=args.model,
            workers=args.workers,
            max_steps=args.max_steps,
            timeout=args.timeout,
            food_lookup=food_lookup,
            per_task_timeout=args.per_task_timeout,
            on_progress=lambda partial, scaffold=scaffold: _write_summary(
                args, scaffold, model_tag, partial
            ),
        )
        summary["split"] = str(args.split)
        out_path = args.out_dir / f"ablation_{model_tag}_{scaffold}.json"
        out_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        summaries.append(summary)
        print(
            f"scaffold={scaffold} passed={summary['passed']}/{summary['n']} "
            f"pass_rate={summary['pass_rate']:.4f} regen_fired={summary['regen_fired']} "
            f"gate_fired_and_passed={summary['gate_fired_and_passed']} -> {out_path}",
            flush=True,
        )

    print("\n=== ablation table ===")
    print(
        f"{'scaffold':<16} {'pass':>9} {'rate':>8} {'void':>5} {'bracket':>17} "
        f"{'regen':>7} {'steps':>7}  gate status"
    )
    for summary in summaries:
        lo = summary["raw_pass_rate"] * 100
        hi = summary["pass_rate_voids_pass"] * 100
        gate = " ".join(f"{k}={v}" for k, v in sorted(summary.get("gate_status", {}).items()))
        fired = " ".join(
            f"{k}={v}" for k, v in sorted(summary.get("gate_fired_shapes", {}).items())
        )
        gate = f"{gate}  fired[{fired}]" if fired else gate
        print(
            f"{summary['scaffold']:<16} {summary['passed']:>4}/{summary['clean_n']:<4} "
            f"{summary['pass_rate']*100:>7.1f}% {summary['void_count']:>5} "
            f"{f'[{lo:.1f}, {hi:.1f}]':>17} {summary['regen_fired']:>7} "
            f"{summary['avg_steps']:>7.1f}  {gate}"
        )
    print(
        "  rate = passed / (n - void), per ADR 0028;  bracket = the same denominator with every "
        "void counted as a failure (left) and as a pass (right)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
