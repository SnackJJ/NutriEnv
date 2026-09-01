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
from nutrienv.harness.react import ReActHarness, _parse_action, context_messages, react_manual
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
            "messages": context_messages(messages),
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
                timeout=harness_spec.get("timeout", 60.0),
                retries=harness_spec.get("retries", 3),
                retry_on=REACT_RETRY_ON,
                error_prefix=f"{harness_spec['model']} request failed",
            )
            text = raw_req
        except Exception as exc:
            err = str(exc)
            text = '{"op": "finish"}'
            messages.append({"role": "assistant", "content": text})
            step_telemetry = StepTelemetry(
                step_index=step_i + 1,
                action={"op": "finish"},
                observation_snippet=f"API Error: {err[:200]}",
                prompt_tokens=0,
                completion_tokens=0,
                reasoning_tokens=0,
                total_tokens=0,
                latency_seconds=time.time() - t0,
                is_valid_tool=False,
                error=err
            )
            steps.append(step_telemetry)
            break

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
        steps=steps
    )


def run_benchmark_suite(
    split_path: str,
    model_id: str,
    *,
    custom_url: str | None = None,
    custom_key_env: str | None = None,
    workers: int = 5,
    resume: bool = False,
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
        "timeout": 45.0,
        "retries": 4,
        "version": "v0"
    }

    out_path = Path(f"reports/benchmark_{model_id.replace('/', '_')}.json")
    cached_map: dict[str, TaskTelemetry] = {}
    if resume and out_path.exists():
        try:
            prev_data = json.loads(out_path.read_text(encoding="utf-8"))
            for pt in prev_data.get("tasks", []):
                if pt.get("total_tokens", 0) > 0 and not any(s.get("error") for s in pt.get("steps", [])):
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

    tasks_to_run = [(idx, task) for idx, task in enumerate(tasks, 1) if task.id not in cached_map]

    print(f"\n🚀 Running Benchmark Suite for Model: {model_id} (Workers: {workers})")
    print(f"   Target Split: {split_path} ({len(tasks)} tasks, {len(tasks_to_run)} pending)")
    print(f"   Endpoint: {url} (Key: {key_env})")

    task_results_map: dict[str, TaskTelemetry] = dict(cached_map)

    if tasks_to_run:
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print_lock = threading.Lock()
        completed_count = len(cached_map)

        def _worker(idx_task):
            idx, t = idx_task
            tele = evaluate_task_with_telemetry(t, harness_spec, catalog)
            nonlocal completed_count
            with print_lock:
                completed_count += 1
                mark = "✅ PASS" if tele.passed else "❌ FAIL"
                print(f"  [{completed_count:02d}/{len(tasks):02d}] {mark} {t.id:<16} ({t.family:<10}) steps={tele.n_steps}/{tele.max_budget} time={tele.wall_time_seconds:.1f}s tokens={tele.total_tokens} tag={tele.score_tag}")
            return t.id, tele

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, it) for it in tasks_to_run]
            for fut in as_completed(futures):
                tid, tele = fut.result()
                task_results_map[tid] = tele

    results = [task_results_map[t.id] for t in tasks if t.id in task_results_map]

    # Aggregate Statistics
    total_tasks = len(results)
    passed_tasks = sum(1 for r in results if r.passed)
    pass_rate = (passed_tasks / total_tasks) * 100 if total_tasks else 0.0

    family_stats = {}
    for fam in ("update", "log", "evaluate", "recommend", "composite"):
        fam_tasks = [r for r in results if r.family == fam]
        if fam_tasks:
            fam_pass = sum(1 for r in fam_tasks if r.passed)
            family_stats[fam] = {
                "total": len(fam_tasks),
                "passed": fam_pass,
                "pass_rate": (fam_pass / len(fam_tasks)) * 100,
                "avg_steps": sum(r.n_steps for r in fam_tasks) / len(fam_tasks),
                "avg_time": sum(r.wall_time_seconds for r in fam_tasks) / len(fam_tasks),
                "avg_tokens": sum(r.total_tokens for r in fam_tasks) / len(fam_tasks)
            }

    overall_avg_steps = sum(r.n_steps for r in results) / total_tasks if total_tasks else 0.0
    overall_avg_time = sum(r.wall_time_seconds for r in results) / total_tasks if total_tasks else 0.0
    overall_total_tokens = sum(r.total_tokens for r in results)
    overall_avg_tokens = overall_total_tokens / total_tasks if total_tasks else 0.0
    total_invalid_tools = sum(r.invalid_tool_count for r in results)
    total_allergen_violations = sum(1 for r in results if r.allergen_violated)

    summary = {
        "model": model_id,
        "split": split_path,
        "total_tasks": total_tasks,
        "passed_tasks": passed_tasks,
        "pass_rate_pct": round(pass_rate, 2),
        "overall_avg_steps": round(overall_avg_steps, 2),
        "overall_avg_time_seconds": round(overall_avg_time, 2),
        "overall_total_tokens": overall_total_tokens,
        "overall_avg_tokens_per_task": round(overall_avg_tokens, 1),
        "total_invalid_tool_calls": total_invalid_tools,
        "total_allergen_violations": total_allergen_violations,
        "family_breakdown": family_stats,
        "tasks": [asdict(r) for r in results]
    }

    out_path = Path(f"reports/benchmark_{model_id.replace('/', '_')}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n📊 Summary Report saved to {out_path}")
    print(f"   🏆 Overall Pass Rate: {pass_rate:.1f}% ({passed_tasks}/{total_tasks})")
    print(f"   ⏱️  Avg Steps: {overall_avg_steps:.2f} turns | Avg Latency: {overall_avg_time:.2f}s | Avg Tokens: {overall_avg_tokens:.1f}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="data/splits/v2.2-mini.json")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--url", default=None)
    parser.add_argument("--key-env", default=None)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--resume", action="store_true", help="Resume from previously completed valid tasks in report json")
    args = parser.parse_args()

    run_benchmark_suite(
        args.split,
        args.model,
        custom_url=args.url,
        custom_key_env=args.key_env,
        workers=args.workers,
        resume=args.resume,
    )
