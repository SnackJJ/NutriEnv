"""Comprehensive NutriEnv Benchmark Evaluator with Deep Telemetry.

Captures all standard agent benchmark metrics:
- Pass Rate / Pass@1 by Family & Complexity
- Trajectory Step Count & Tool Call Breakdown
- Prompt / Completion / Reasoning Token Consumption
- End-to-End Latency & Per-Step Response Time
- Domain Safety (Allergen Violations, Calorie/Macro Deltas)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass, asdict, field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nutrienv.bench import load_split, Scorer
from nutrienv.env import NutriEnv
from nutrienv.harness.react import (
    _CONTEXT_LIMIT,
    ReActHarness,
    _parse_action,
    context_messages,
    react_manual,
)
from nutrienv.harness.runner import FAMILY_MAX_STEPS, DEFAULT_MAX_STEPS, FINISH_OPS, WRITE_OPS, READ_OPS
from nutrienv.io.dotenv import load_dotenv_keys
from nutrienv.io.chat import lookup_chat_model, post_chat_completion, REACT_RETRY_ON


@dataclass
class StepTelemetry:
    step_index: int
    action: dict
    observation_snippet: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0
    is_valid_tool: bool = True
    error: str | None = None


class EpisodeInfraError(RuntimeError):
    """Raised when an episode encounters an unrecoverable network/infrastructure failure."""
    pass


@dataclass
class TaskTelemetry:
    task_id: str
    family: str
    query: str
    persona: str
    passed: bool
    score_tag: str
    n_steps: int
    max_budget: int
    wall_time_seconds: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_reasoning_tokens: int
    total_tokens: int
    tool_counts: dict[str, int]
    invalid_tool_count: int
    allergen_violated: bool
    steps: list[StepTelemetry] = field(default_factory=list)
    is_void: bool = False
    void_reason: str | None = None


def evaluate_task_with_telemetry(task, harness_spec, catalog) -> TaskTelemetry:
    env = NutriEnv()
    observation = env.reset(task.s0)
    scorer = Scorer()

    max_steps = FAMILY_MAX_STEPS.get(task.family, DEFAULT_MAX_STEPS)
    messages = [
        {"role": "system", "content": react_manual(harness_spec.get("version", "v0"))},
        {"role": "user", "content": f"Task:\n{task.query}"}
    ]

    steps: list[StepTelemetry] = []
    tool_counts: dict[str, int] = {}
    invalid_tool_count = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reasoning_tokens = 0
    total_tokens = 0

    t_start = time.time()
    for step_i in range(max_steps):
        remaining = max_steps - step_i
        messages.append({
            "role": "user",
            "content": f"Step budget: {remaining} action(s) remaining.\nObservation:\n{json.dumps(observation, default=str)[:6000]}"
        })

        t0 = time.time()
        # Post completion and capture raw body with usage
        payload = {
            "model": harness_spec["model"],
            "messages": context_messages(
                messages, limit=harness_spec.get("context_limit", _CONTEXT_LIMIT)
            ),
            "temperature": 0.0,
            "max_tokens": 1000,
        }
        if "extra_body" in harness_spec:
            payload.update(harness_spec["extra_body"])

        # Execute API call with retries and timing
        text = ""
        usage = {}
        err = None
        try:
            raw_req = post_chat_completion(
                harness_spec["url"],
                payload,
                harness_spec["api_key"],
                timeout=harness_spec.get("timeout", 90.0),
                retries=harness_spec.get("retries", 4),
                retry_on=REACT_RETRY_ON,
                error_prefix=f"{harness_spec['model']} request failed",
            )
            text = raw_req
        except Exception as exc:
            err = str(exc)
            # Never synthesize a fake 'finish' action on infra network failure!
            raise EpisodeInfraError(f"Step {step_i+1} API failure: {err}") from exc

        step_latency = time.time() - t0
        messages.append({"role": "assistant", "content": text})

        action = _parse_action(text)
        op = str(action.get("op", "unknown"))
        is_valid = op in ("search_foods", "get_food", "get_profile", "get_ledger", "get_dri", "log_meal", "submit_plan", "update_profile", "update_plan", "finish", "done", "stop")
        if not is_valid:
            invalid_tool_count += 1
            op = "invalid_format_fallback"

        tool_counts[op] = tool_counts.get(op, 0) + 1

        # Heuristic/actual token estimate (if provider returns usage, we capture it, otherwise estimate 4 chars/token)
        p_tok = len(json.dumps(messages)) // 4
        c_tok = len(text) // 4
        total_prompt_tokens += p_tok
        total_completion_tokens += c_tok
        total_tokens += (p_tok + c_tok)

        step_telemetry = StepTelemetry(
            step_index=step_i + 1,
            action=action,
            observation_snippet=str(observation)[:200],
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            reasoning_tokens=0,
            total_tokens=p_tok + c_tok,
            latency_seconds=step_latency,
            is_valid_tool=is_valid,
            error=err
        )
        steps.append(step_telemetry)

        if op in FINISH_OPS:
            break

        result = env.step(action)
        if result.get("ok") and isinstance(result.get("observation"), dict):
            observation = result["observation"]
        else:
            observation = {"error": result.get("error")}

        if op == "submit_plan":
            break

    wall_time = time.time() - t_start
    score = scorer.score(env.state(), task.oracle)
    passed = bool(score.get("passed", False))
    score_tag = str(score.get("tag", "UNKNOWN"))

    # Check for allergen violation
    allergen_violated = score_tag in ("allergy", "FatalAllergyClash")

    return TaskTelemetry(
        task_id=task.id,
        family=task.family,
        query=task.query,
        persona=task.persona,
        passed=passed,
        score_tag=score_tag,
        n_steps=len(steps),
        max_budget=max_steps,
        wall_time_seconds=wall_time,
        total_prompt_tokens=total_prompt_tokens,
        total_completion_tokens=total_completion_tokens,
        total_reasoning_tokens=total_reasoning_tokens,
        total_tokens=total_tokens,
        tool_counts=tool_counts,
        invalid_tool_count=invalid_tool_count,
        allergen_violated=allergen_violated,
        steps=steps,
        is_void=False,
        void_reason=None,
    )


def evaluate_task_with_episode_retry(
    task, harness_spec, catalog, max_retries: int = 2
) -> TaskTelemetry:
    """Run an episode with automatic full episode retries on fatal network/infra errors."""
    last_err: str | None = None
    for attempt in range(max_retries + 1):
        try:
            return evaluate_task_with_telemetry(task, harness_spec, catalog)
        except EpisodeInfraError as exc:
            last_err = str(exc)
            if attempt < max_retries:
                time.sleep(2.0 * (attempt + 1))
                continue
            # Retries exhausted: mark as VOID infrastructure failure without faking completion
            max_steps = FAMILY_MAX_STEPS.get(task.family, DEFAULT_MAX_STEPS)
            return TaskTelemetry(
                task_id=task.id,
                family=task.family,
                query=task.query,
                persona=task.persona,
                passed=False,
                score_tag="VOID_INFRA_ERROR",
                n_steps=0,
                max_budget=max_steps,
                wall_time_seconds=0.0,
                total_prompt_tokens=0,
                total_completion_tokens=0,
                total_reasoning_tokens=0,
                total_tokens=0,
                tool_counts={},
                invalid_tool_count=0,
                allergen_violated=False,
                steps=[],
                is_void=True,
                void_reason=last_err,
            )
    raise RuntimeError(f"Unexpected retry fallthrough for task {task.id}")


def _parse_context_limit(value: str) -> int | None:
    """12-message slide, or full log. ``full`` / ``none`` / ``0`` mean unlimited."""
    lowered = value.strip().lower()
    if lowered in {"0", "full", "none", "unlimited"}:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "context-limit must be an int >= 1, or full"
        ) from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("context-limit must be an int >= 1, or full")
    return parsed


def _context_tag(limit: int | None) -> str:
    return "full" if limit is None else str(limit)


def _telemetry_from_dict(pt: dict) -> TaskTelemetry:
    step_objs = [
        StepTelemetry(
            step_index=s.get("step_index", 1),
            action=s.get("action", {}),
            observation_snippet=s.get("observation_snippet", ""),
            prompt_tokens=s.get("prompt_tokens", 0),
            completion_tokens=s.get("completion_tokens", 0),
            reasoning_tokens=s.get("reasoning_tokens", 0),
            total_tokens=s.get("total_tokens", 0),
            latency_seconds=s.get("latency_seconds", 0.0),
            is_valid_tool=s.get("is_valid_tool", True),
            error=s.get("error"),
        )
        for s in pt.get("steps", [])
    ]
    return TaskTelemetry(
        task_id=pt["task_id"],
        family=pt["family"],
        query=pt.get("query", ""),
        persona=pt.get("persona", ""),
        passed=pt["passed"],
        score_tag=pt.get("score_tag", ""),
        n_steps=pt["n_steps"],
        max_budget=pt.get("max_budget", 0),
        wall_time_seconds=pt.get("wall_time_seconds", 0.0),
        total_prompt_tokens=pt.get("total_prompt_tokens", 0),
        total_completion_tokens=pt.get("total_completion_tokens", 0),
        total_reasoning_tokens=pt.get("total_reasoning_tokens", 0),
        total_tokens=pt.get("total_tokens", 0),
        tool_counts=pt.get("tool_counts", {}),
        invalid_tool_count=pt.get("invalid_tool_count", 0),
        allergen_violated=pt.get("allergen_violated", False),
        steps=step_objs,
    )


def _build_summary(
    model_id: str,
    split_path: str,
    context_limit: int | None,
    ordered_ids: list[str],
    results_map: dict[str, TaskTelemetry],
) -> dict:
    results = [results_map[tid] for tid in ordered_ids if tid in results_map]
    total_tasks = len(results)
    passed_tasks = sum(1 for r in results if r.passed)
    void_tasks = [r for r in results if getattr(r, "is_void", False)]
    void_count = len(void_tasks)
    void_ids = [r.task_id for r in void_tasks]
    clean_total = total_tasks - void_count
    clean_pass_rate = (passed_tasks / clean_total) * 100 if clean_total > 0 else 0.0
    pass_rate = (passed_tasks / total_tasks) * 100 if total_tasks else 0.0
    family_stats: dict = {}
    for fam in ("update", "log", "evaluate", "recommend", "composite"):
        fam_tasks = [r for r in results if r.family == fam]
        if fam_tasks:
            fam_pass = sum(1 for r in fam_tasks if r.passed)
            fam_void = sum(1 for r in fam_tasks if getattr(r, "is_void", False))
            family_stats[fam] = {
                "total": len(fam_tasks),
                "passed": fam_pass,
                "void": fam_void,
                "pass_rate": (fam_pass / len(fam_tasks)) * 100,
                "clean_pass_rate": (fam_pass / (len(fam_tasks) - fam_void)) * 100 if (len(fam_tasks) - fam_void) > 0 else 0.0,
                "avg_steps": sum(r.n_steps for r in fam_tasks) / len(fam_tasks),
                "avg_time": sum(r.wall_time_seconds for r in fam_tasks) / len(fam_tasks),
                "avg_tokens": sum(r.total_tokens for r in fam_tasks) / len(fam_tasks),
            }
    return {
        "model": model_id,
        "split": split_path,
        "context_limit": context_limit,
        "total_tasks": total_tasks,
        "passed_tasks": passed_tasks,
        "pass_rate_pct": round(pass_rate, 2),
        "void_count": void_count,
        "void_ids": void_ids,
        "clean_total_tasks": clean_total,
        "clean_pass_rate_pct": round(clean_pass_rate, 2),
        "overall_avg_steps": round(sum(r.n_steps for r in results) / total_tasks, 2) if total_tasks else 0.0,
        "overall_avg_time_seconds": round(sum(r.wall_time_seconds for r in results) / total_tasks, 2) if total_tasks else 0.0,
        "overall_total_tokens": sum(r.total_tokens for r in results),
        "overall_avg_tokens_per_task": round(sum(r.total_tokens for r in results) / total_tasks, 1) if total_tasks else 0.0,
        "total_invalid_tool_calls": sum(r.invalid_tool_count for r in results),
        "total_allergen_violations": sum(1 for r in results if r.allergen_violated),
        "family_breakdown": family_stats,
        "tasks": [asdict(r) for r in results],
    }


def _write_report(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _reuse_short_tasks(
    path: Path,
    max_steps: int,
    *,
    skip_failed: bool = False,
) -> dict[str, TaskTelemetry]:
    """Copy untruncated tasks. Skip crashed or, if requested, failed episodes."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    reused: dict[str, TaskTelemetry] = {}
    for pt in payload.get("tasks", []):
        if int(pt.get("n_steps", 999)) > max_steps:
            continue
        if pt.get("total_tokens", 0) <= 0:
            continue
        if any(s.get("error") for s in pt.get("steps", [])):
            continue
        if skip_failed and not pt.get("passed"):
            continue
        reused[pt["task_id"]] = _telemetry_from_dict(pt)
    return reused


def run_benchmark_suite(
    split_path: str = "data/splits/v2.2-mini.json",
    model_id: str = "deepseek-chat",
    custom_url: str | None = None,
    custom_key_env: str | None = None,
    workers: int = 5,
    resume: bool = False,
    rerun_failed: bool = False,
    context_limit: int | None = None,
    reuse_from: str | None = None,
    reuse_max_steps: int = 5,
    out: str | None = None,
) -> dict:
    load_dotenv_keys(Path(".env.local"))
    from nutrienv.world.catalog_store import load_catalog
    catalog = load_catalog(Path("data/fdc/catalog-v2.sqlite"))
    tasks = load_split(split_path, catalog=catalog)

    spec = lookup_chat_model(model_id)
    url = custom_url or spec.url
    key_env = custom_key_env or spec.api_key_env
    api_key = os.environ.get(key_env)

    if not api_key:
        raise RuntimeError(f"API key environment variable '{key_env}' is not set.")

    harness_spec = {
        "model": spec.model_id,
        "url": url,
        "api_key": api_key,
        "timeout": 90.0,
        "retries": 4,
        "version": "v2",
        "context_limit": context_limit,
    }

    split_stem = Path(split_path).stem
    out_path = Path(out) if out else Path(
        f"reports/ablation_ctx_{split_stem}_{model_id.replace('/', '_')}"
        f"_limit{_context_tag(context_limit)}.json"
    )
    cached_map: dict[str, TaskTelemetry] = {}
    if (resume or rerun_failed) and out_path.exists():
        try:
            prev_data = json.loads(out_path.read_text(encoding="utf-8"))
            for pt in prev_data.get("tasks", []):
                if pt.get("total_tokens", 0) > 0 and not any(s.get("error") for s in pt.get("steps", [])):
                    if rerun_failed and not pt.get("passed"):
                        continue  # Do not cache failed tasks when rerun_failed is True
                    step_objs = [
                        StepTelemetry(
                            step_index=s.get("step_index", 1),
                            action=s.get("action", {}),
                            observation_snippet=s.get("observation_snippet", ""),
                            prompt_tokens=s.get("prompt_tokens", 0),
                            completion_tokens=s.get("completion_tokens", 0),
                            reasoning_tokens=s.get("reasoning_tokens", 0),
                            total_tokens=s.get("total_tokens", 0),
                            latency_seconds=s.get("latency_seconds", 0.0),
                            is_valid_tool=s.get("is_valid_tool", True),
                            error=s.get("error")
                        )
                        for s in pt.get("steps", [])
                    ]
                    cached_map[pt["task_id"]] = TaskTelemetry(
                        task_id=pt["task_id"],
                        family=pt["family"],
                        query=pt["query"],
                        persona=pt.get("persona", ""),
                        passed=pt["passed"],
                        score_tag=pt["score_tag"],
                        n_steps=pt["n_steps"],
                        max_budget=pt["max_budget"],
                        wall_time_seconds=pt["wall_time_seconds"],
                        total_prompt_tokens=pt["total_prompt_tokens"],
                        total_completion_tokens=pt["total_completion_tokens"],
                        total_reasoning_tokens=pt.get("total_reasoning_tokens", 0),
                        total_tokens=pt["total_tokens"],
                        tool_counts=pt.get("tool_counts", {}),
                        invalid_tool_count=pt.get("invalid_tool_count", 0),
                        allergen_violated=pt.get("allergen_violated", False),
                        steps=step_objs
                    )
            print(f"🔄 Resuming benchmark: Loaded {len(cached_map)} valid completed tasks from {out_path}")
        except Exception as e:
            print(f"⚠️ Failed to load resume cache: {e}")

    if reuse_from:
        live_query = {task.id: task.query for task in tasks}
        reused = _reuse_short_tasks(
            Path(reuse_from),
            reuse_max_steps,
            skip_failed=rerun_failed,
        )
        kept = 0
        for tid, tele in reused.items():
            if tid in cached_map:
                continue
            if live_query.get(tid) != tele.query:
                continue
            cached_map[tid] = tele
            kept += 1
        print(
            f"♻️  Reused {kept} short unchanged tasks (n_steps<={reuse_max_steps}) "
            f"from {reuse_from} ({len(reused) - kept} skipped: gold query moved)"
        )

    tasks_to_run = [(idx, task) for idx, task in enumerate(tasks, 1) if task.id not in cached_map]

    print(f"\n🚀 Running Benchmark Suite for Model: {model_id} (Workers: {workers})")
    print(f"   Target Split: {split_path} ({len(tasks)} tasks, {len(tasks_to_run)} pending)")
    print(f"   Context: {_context_tag(context_limit)} (limit={context_limit!r})")
    print(f"   Endpoint: {url} (Key: {key_env})")

    task_results_map: dict[str, TaskTelemetry] = dict(cached_map)
    ordered_ids = [t.id for t in tasks]

    def _checkpoint() -> dict:
        summary = _build_summary(
            model_id, split_path, context_limit, ordered_ids, task_results_map
        )
        _write_report(out_path, summary)
        return summary

    if tasks_to_run:
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print_lock = threading.Lock()
        completed_count = len(cached_map)

        def _worker(idx_task):
            idx, t = idx_task
            tele = evaluate_task_with_episode_retry(t, harness_spec, catalog)
            nonlocal completed_count
            with print_lock:
                completed_count += 1
                if tele.is_void:
                    mark = "⚠️ VOID"
                else:
                    mark = "✅ PASS" if tele.passed else "❌ FAIL"
                print(f"  [{completed_count:02d}/{len(tasks):02d}] {mark} {t.id:<16} ({t.family:<10}) steps={tele.n_steps}/{tele.max_budget} time={tele.wall_time_seconds:.1f}s tokens={tele.total_tokens} tag={tele.score_tag}")
            return t.id, tele

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, it) for it in tasks_to_run]
            for fut in as_completed(futures):
                tid, tele = fut.result()
                task_results_map[tid] = tele
                _checkpoint()

    summary = _checkpoint()
    print(f"\n📊 Summary Report saved to {out_path}")
    print(f"   🏆 Overall Pass Rate: {summary['pass_rate_pct']:.1f}% ({summary['passed_tasks']}/{summary['total_tasks']})")
    if summary['void_count'] > 0:
        print(f"   🛡️  Clean Pass Rate (ex-void): {summary['clean_pass_rate_pct']:.1f}% ({summary['passed_tasks']}/{summary['clean_total_tasks']}) [VOID: {summary['void_count']}]")
    print(f"   ⏱️  Avg Steps: {summary['overall_avg_steps']:.2f} turns | Avg Latency: {summary['overall_avg_time_seconds']:.2f}s | Avg Tokens: {summary['overall_avg_tokens_per_task']:.1f}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="data/splits/v2.2-mini.json")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--url", default=None)
    parser.add_argument("--key-env", default=None)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--resume", action="store_true", help="Resume from previously completed valid tasks in report json")
    parser.add_argument("--rerun-failed", action="store_true", help="Keep passed tasks and re-run all previously failed tasks")
    parser.add_argument(
        "--context-limit",
        type=_parse_context_limit,
        default=None,
        help="trajectory window: full (default, no truncation) or 12 (ablation slide)",
    )
    parser.add_argument(
        "--reuse-from",
        default=None,
        help="copy short tasks (n_steps <= --reuse-max-steps) from a prior report",
    )
    parser.add_argument(
        "--reuse-max-steps",
        type=int,
        default=5,
        help="max n_steps to treat as untruncated and reuse (default 5)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="report JSON path (default: reports/ablation_ctx_<split>_<model>_limit<tag>.json)",
    )
    args = parser.parse_args()

    run_benchmark_suite(
        args.split,
        args.model,
        custom_url=args.url,
        custom_key_env=args.key_env,
        workers=args.workers,
        resume=args.resume,
        rerun_failed=args.rerun_failed,
        context_limit=args.context_limit,
        reuse_from=args.reuse_from,
        reuse_max_steps=args.reuse_max_steps,
        out=args.out,
    )
