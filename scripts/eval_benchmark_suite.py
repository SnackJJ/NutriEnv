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
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nutrienv.bench import SCORER_VERSION, Scorer, load_split
from nutrienv.env import NutriEnv
from nutrienv.harness.prompt_freeze import (
    PROMPT_VERSION,
    assert_frozen,
    prompt_fingerprint,
)
from nutrienv.harness.react import (
    PARSE_ERROR_POLICIES,
    context_messages,
    react_manual,
    resolve_action,
    violation_feedback,
)
from nutrienv.harness.runner import (
    LOOP_VERSION,
    DEFAULT_MAX_STEPS,
    FAMILY_MAX_STEPS,
    FINISH_OPS,
)
from nutrienv.harness.tool_call import ToolCallInfraError, run_episode_tool_call
from nutrienv.io.chat import (
    REACT_RETRY_ON,
    _message_text,
    lookup_chat_model,
    post_chat_completion_raw,
)
from nutrienv.io.dotenv import load_dotenv_keys


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
    # False when the provider reported no usage block and the counts are the 4-chars/token
    # estimate. Reported so a reader can tell a measured column from a guessed one.
    tokens_measured: bool = False
    # Whether this turn obeyed the output contract. `action` below is what the loop *did*,
    # which under the `silent` policy is not what the model asked for; without these three
    # fields the substitution leaves no trace in the report.
    protocol_violation: bool = False
    violation_reason: str | None = None
    raw_text: str | None = None
    error: str | None = None
    # Env refused the action (an Illegal Action: a known op whose arguments break its schema).
    # The world is untouched and the turn is spent; `is_valid_tool` only says the op is known.
    refused: bool = False


class EpisodeInfraError(RuntimeError):
    """Raised when an episode encounters an unrecoverable network/infrastructure failure."""


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
    # Turns whose text was not a legal Action, and what the loop did about each one. The count
    # is the protocol-compliance measurement; the log keeps enough to read what the model sent.
    protocol_violations: int = 0
    violation_log: list[dict] = field(default_factory=list)
    steps: list[StepTelemetry] = field(default_factory=list)
    is_void: bool = False
    void_reason: str | None = None


def _usage_int(value: object, field: str) -> int:
    """A provider token count, or a loud error naming the field.

    The usage block is JSON, so an int is what the provider sent unless something is wrong; the
    point of checking here is that a wrong one names its field instead of surfacing as
    `invalid literal for int()` from inside a retry loop.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return round(value)
    raise ValueError(f"provider reported a non-integer {field}: {value!r}")


# How an Action is expressed and handed back. Two values, one axis; a report records which one
# it used, and a pass figure from one is not comparable with the other.
CONTRACTS = ("text-json", "native-tools")


def _reasoning_tokens(usage: dict) -> int:
    """Thinking tokens, from whichever field the provider filled in."""
    detail = usage.get("completion_tokens_details")
    if isinstance(detail, dict) and detail.get("reasoning_tokens") is not None:
        return _usage_int(
            detail["reasoning_tokens"], "completion_tokens_details.reasoning_tokens"
        )
    if usage.get("reasoning_tokens") is not None:
        return _usage_int(usage["reasoning_tokens"], "reasoning_tokens")
    return 0


def evaluate_task_with_telemetry(task, harness_spec, catalog) -> TaskTelemetry:
    env = NutriEnv()
    observation = env.reset(task.s0)
    scorer = Scorer()

    max_steps = FAMILY_MAX_STEPS.get(task.family, DEFAULT_MAX_STEPS)
    messages = [
        {"role": "system", "content": react_manual(harness_spec.get("version", "v0"))},
        {"role": "user", "content": f"Task:\n{task.query}"}
    ]

    parse_error_policy = harness_spec["parse_error_policy"]
    steps: list[StepTelemetry] = []
    tool_counts: dict[str, int] = {}
    invalid_tool_count = 0
    protocol_violations = 0
    violation_log: list[dict] = []
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
            # The spec always carries `context_limit` (this module builds it from
            # --context-limit, default full). Index instead of `.get`: a spec that omits it used
            # to fall back to the 12-message slide, which is the truncation nobody asked for.
            "messages": context_messages(messages, limit=harness_spec["context_limit"]),
            "temperature": harness_spec.get("temperature", 0.0),
        }
        if "max_tokens" in harness_spec:
            payload["max_tokens"] = harness_spec["max_tokens"]
        if "extra_body" in harness_spec:
            payload.update(harness_spec["extra_body"])

        # Execute API call with retries and timing
        text = ""
        usage = {}
        err = None
        try:
            # Raw body (not just the text): the usage block carries reasoning_tokens, and
            # without it a long thinking step is invisible in the telemetry. The helper
            # streams, which is what keeps a multi-minute reasoning step from tripping the
            # socket read timeout and being resent from scratch.
            raw_body = post_chat_completion_raw(
                harness_spec["url"],
                payload,
                harness_spec["api_key"],
                timeout=harness_spec.get("timeout", 90.0),
                retries=harness_spec.get("retries", 4),
                retry_on=REACT_RETRY_ON,
                error_prefix=f"{harness_spec['model']} request failed",
            )
            # `_message_text`, not the bare `content`: reasoner models sometimes leave
            # `content` empty and put the answer in `reasoning_content`, and the raw form
            # turned that into a scored parse_error.
            text = _message_text(raw_body)
            usage = raw_body.get("usage") or {}
        except Exception as exc:
            err = str(exc)
            # Never synthesize a fake 'finish' action on infra network failure!
            raise EpisodeInfraError(f"Step {step_i+1} API failure: {err}") from exc

        step_latency = time.time() - t0
        messages.append({"role": "assistant", "content": text})

        # Did the model obey the output contract, and what is the loop going to do about it?
        # `resolve_action` answers the first without the `get_profile` substitution that makes
        # a violation indistinguishable from a successful read; `action` is the second.
        parsed, violation = resolve_action(text)
        action = parsed if parsed is not None else {"op": "get_profile"}
        op = str(action.get("op", "unknown"))
        is_valid = op in (
            "search_foods", "get_food", "get_profile", "get_ledger", "get_dri",
            "log_meal", "submit_plan", "update_profile", "update_plan", "amend_meal",
            "finish", "done", "stop"
        )
        if not is_valid:
            invalid_tool_count += 1
            op = "invalid_format_fallback"

        tool_counts[op] = tool_counts.get(op, 0) + 1

        # Real usage when the provider reports it, else 4 chars/token. The reasoning count is
        # the point of reading `usage` at all: it dominates the wall time of a thinking model
        # and is invisible in the returned text, so an all-zero column hides where the time
        # went. `or` rather than a `0` default, so a missing field still falls back.
        measured = bool(usage)
        p_tok = usage.get("prompt_tokens") or len(json.dumps(messages)) // 4
        c_tok = usage.get("completion_tokens") or len(text) // 4
        r_tok = _reasoning_tokens(usage)
        total_prompt_tokens += p_tok
        total_completion_tokens += c_tok
        total_reasoning_tokens += r_tok
        total_tokens += (p_tok + c_tok)

        if violation:
            protocol_violations += 1
            violation_log.append(
                {
                    "step_index": step_i + 1,
                    "reason": violation,
                    "policy": parse_error_policy,
                    "text": text[:1200],
                }
            )

        step_telemetry = StepTelemetry(
            step_index=step_i + 1,
            action=action,
            observation_snippet=str(observation)[:200],
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            reasoning_tokens=r_tok,
            total_tokens=p_tok + c_tok,
            latency_seconds=step_latency,
            is_valid_tool=is_valid,
            tokens_measured=measured,
            protocol_violation=bool(violation),
            violation_reason=violation,
            raw_text=text[:1200] if violation else None,
            error=err
        )
        steps.append(step_telemetry)

        if violation and parse_error_policy != "silent":
            # The turn is spent either way, which is the point: a retry is not free. What
            # differs between the two non-silent policies is only whether the model is told
            # what went wrong, so the extra completion is held equal between them.
            messages.append({"role": "user", "content": violation_feedback(parse_error_policy, text)})
            continue

        if op in FINISH_OPS:
            break

        result = env.step(action)
        if result.get("ok") and isinstance(result.get("observation"), dict):
            observation = result["observation"]
        else:
            observation = {"error": result.get("error")}
        step_telemetry.refused = not result.get("ok")

        # A hand-in ends the episode only when Env accepted it. An Illegal Action leaves the
        # world untouched and reports the error; breaking here scored that untouched world as
        # the model's answer -- a reject missing the schema's required `items` arrived as
        # `last_plan=None` and failed `None != []` in the Scorer. `harness.runner._run_episode`
        # continues on a refused action; this loop had drifted from it.
        if op == "submit_plan" and result.get("ok"):
            break

        # Circuit breaker: stop if stuck in 3 consecutive parse errors
        if len(steps) >= 3 and all(s.action.get("op") == "parse_error" for s in steps[-3:]):
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
        protocol_violations=protocol_violations,
        violation_log=violation_log,
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
            if harness_spec.get("contract") == "native-tools":
                return run_episode_tool_call(
                    task, harness_spec, catalog, StepTelemetry, TaskTelemetry
                )
            return evaluate_task_with_telemetry(task, harness_spec, catalog)
        except (EpisodeInfraError, ToolCallInfraError) as exc:
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
            refused=s.get("refused", False),
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
        protocol_violations=pt.get("protocol_violations", 0),
        violation_log=pt.get("violation_log", []),
        steps=step_objs,
    )


def _build_summary(
    model_id: str,
    split_path: str,
    context_limit: int | None,
    ordered_ids: list[str],
    results_map: dict[str, TaskTelemetry],
    contract: str = "native-tools",
    parse_error_policy: str = "silent",
    endpoint: str | None = None,
    temperature: float | None = None,
    prompt_fp: str | None = None,
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
        # Protocol compliance, which `total_invalid_tool_calls` cannot report: it counts only
        # "parsed, but the op is unknown", while the dominant violation is "no Action at all".
        "parse_error_policy": parse_error_policy,
        "total_protocol_violations": sum(r.protocol_violations for r in results),
        "protocol_violation_rate": round(
            sum(r.protocol_violations for r in results) / max(1, sum(r.n_steps for r in results)), 4
        ),
        # Turns Env refused: a known op with illegal arguments. Neither column above sees them,
        # since the op parses and is known; the turn is spent and the world is unchanged.
        "total_refused_actions": sum(s.refused for r in results for s in r.steps),
        "refused_action_rate": round(
            sum(s.refused for r in results for s in r.steps)
            / max(1, sum(r.n_steps for r in results)),
            4,
        ),
        "total_allergen_violations": sum(1 for r in results if r.allergen_violated),
        "contract": contract,
        # Provenance: the same model id can be a different snapshot per gateway, and
        # the same model at a different temperature is a different measurement.
        "endpoint": endpoint,
        "temperature": temperature,
        # Which prompt generation produced this file (see harness/prompt_freeze.py).
        "prompt_version": PROMPT_VERSION,
        "prompt_fingerprint": prompt_fp or prompt_fingerprint(),
        # Which scoring ruler judged it (see bench/scorer.py), and which episode loop ran it
        # (see harness/runner.py).
        "scorer_version": SCORER_VERSION,
        "loop_version": LOOP_VERSION,
        "family_breakdown": family_stats,
        "tasks": [asdict(r) for r in results],
    }


def _write_report(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _require_same_ruler(prior: dict, source: Path) -> None:
    """Refuse to reuse cached tasks judged by another scorer or run by another loop.

    Cached tasks carry their stored pass/tag, and the summary stamps the current versions, so
    reusing them across a version change would label old judgements with the new ruler.
    """
    for key, current in (("scorer_version", SCORER_VERSION), ("loop_version", LOOP_VERSION)):
        recorded = prior.get(key)
        if recorded != current:
            raise SystemExit(
                f"{source} was produced under {key}={recorded or 'unrecorded'}, this run uses "
                f"{current}; its cached tasks cannot be reused. Run without --resume / "
                "--rerun-failed / --reuse-from, or re-score its trajectories."
            )


def _reuse_short_tasks(
    path: Path,
    max_steps: int,
    *,
    contract: str,
    skip_failed: bool = False,
) -> dict[str, TaskTelemetry]:
    """Copy untruncated tasks. Skip crashed or, if requested, failed episodes."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read the reuse report {path}: {exc}") from exc
    _require_same_ruler(payload, path)
    # Same generation and transport, as --resume requires: a reused tag is a stored judgement.
    assert_frozen(payload)
    recorded_contract = payload.get("contract") or payload.get("harness_mode")
    if recorded_contract != contract:
        raise SystemExit(
            f"{path} was run with contract={recorded_contract or 'unrecorded'}, this run uses "
            f"{contract}; its cached tasks cannot be reused."
        )
    reused: dict[str, TaskTelemetry] = {}
    for pt in payload.get("tasks", []):
        n_steps = pt.get("n_steps", 999)
        if not isinstance(n_steps, int) or isinstance(n_steps, bool):
            raise SystemExit(
                f"reuse report task {pt.get('task_id')!r} has a non-integer n_steps: {n_steps!r}"
            )
        if n_steps > max_steps:
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
    split_path: str = "data/splits/nutrienv-mini.json",
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
    contract: str = "native-tools",
    temperature: float = 0.0,
    parse_error_policy: str = "silent",
) -> dict:
    if contract not in CONTRACTS:
        raise ValueError(f"unknown contract {contract!r}; choose from {CONTRACTS}")
    if parse_error_policy not in PARSE_ERROR_POLICIES:
        raise ValueError(
            f"unknown parse_error_policy {parse_error_policy!r}; "
            f"choose from {PARSE_ERROR_POLICIES}"
        )
    load_dotenv_keys(Path(".env.local"))
    from nutrienv.world.catalog_store import load_catalog

    # The split names the catalog it was authored against, so take it from there. Hard-coding a
    # path here meant the report's `split` field and the world the tasks actually ran in could
    # disagree, and load_catalog used to substitute a 15-food fixture when a path went missing.
    try:
        split_payload = json.loads(Path(split_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read the split {split_path}: {exc}") from exc
    catalog_field = split_payload.get("catalog") if isinstance(split_payload, dict) else None
    if not catalog_field:
        raise RuntimeError(f"{split_path} records no `catalog` path; refusing to guess one")
    catalog = load_catalog(Path(catalog_field))
    tasks = load_split(split_path, catalog=catalog)

    spec = lookup_chat_model(model_id)
    url = custom_url or spec.url
    key_env = custom_key_env or spec.api_key_env
    api_key = os.environ.get(key_env)

    if not api_key:
        raise RuntimeError(f"API key environment variable '{key_env}' is not set.")

    # Resolved once rather than per checkpoint: recomputing it mid-run would relabel tasks
    # already produced under the old prompts, which is the straddle prompt_freeze exists to
    # make impossible.
    prompt_fp = assert_frozen()

    harness_spec = {
        "model": spec.model_id,
        "url": url,
        "api_key": api_key,
        "timeout": 180.0,
        "retries": 5,
        "version": "v2",
        "context_limit": context_limit,
        "temperature": temperature,
        "contract": contract,
        "parse_error_policy": parse_error_policy,
    }

    split_stem = Path(split_path).stem
    out_path = Path(out) if out else Path(
        f"reports/ablation_ctx_{split_stem}_{model_id.replace('/', '_')}"
        f"_limit{_context_tag(context_limit)}.json"
    )
    cached_map: dict[str, TaskTelemetry] = {}
    if (resume or rerun_failed) and out_path.exists():
        # Fatal, not a warning: `--resume` means "do not pay for these tasks again", so a cache
        # that cannot be read has to stop the run rather than quietly start over.
        try:
            prev_data: dict = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise SystemExit(f"cannot read the resume cache {out_path}: {e}") from e
        if prev_data:
            # Refuse to mix generations: a report written under a different prompt generation
            # must not silently lend its cached tasks to this run.
            assert_frozen(prev_data)
            _require_same_ruler(prev_data, out_path)
        try:
            # Legacy key: reports written before the axis was named `contract`.
            prev_contract = prev_data.get("contract") or prev_data.get("harness_mode")
            if prev_contract and prev_contract != contract:
                print(f"⚠️ Warning: prior report has contract '{prev_contract}', but current run is '{contract}'. Resume aborted.")
                prev_data = {}
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
                            tokens_measured=s.get("tokens_measured", False),
                            protocol_violation=s.get("protocol_violation", False),
                            violation_reason=s.get("violation_reason"),
                            raw_text=s.get("raw_text"),
                            error=s.get("error"),
                            refused=s.get("refused", False),
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
                        protocol_violations=pt.get("protocol_violations", 0),
                        violation_log=pt.get("violation_log", []),
                        steps=step_objs
                    )
            print(f"🔄 Resuming benchmark: Loaded {len(cached_map)} valid completed tasks from {out_path}")
        except (KeyError, TypeError, ValueError) as e:
            raise SystemExit(f"resume cache {out_path} is not a report this code can read: {e}") from e

    if reuse_from:
        live_query = {task.id: task.query for task in tasks}
        reused = _reuse_short_tasks(
            Path(reuse_from),
            reuse_max_steps,
            skip_failed=rerun_failed,
            contract=contract,
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
            model_id, split_path, context_limit, ordered_ids, task_results_map,
            contract=contract, parse_error_policy=parse_error_policy,
            endpoint=url, temperature=temperature, prompt_fp=prompt_fp,
        )
        _write_report(out_path, summary)
        return summary

    if tasks_to_run:
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print_lock = threading.Lock()
        completed_count = len(cached_map)

        def _worker(idx_task):
            _idx, t = idx_task
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


def build_parser() -> argparse.ArgumentParser:
    """CLI surface, kept as a function so tests can assert the harness contract."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="data/splits/nutrienv-mini.json")
    parser.add_argument("--model", default="commandcode/inclusionai/ling-3.0-flash-sante:free")
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
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="sampling temperature (0.0 = published protocol; >0 for the noise floor)",
    )
    parser.add_argument(
        "--contract",
        default="native-tools",
        choices=list(CONTRACTS),
        help=(
            "how an Action is expressed and handed back: native-tools (the default, "
            "OpenAI-style function calling) or text-json (the ReAct loop, one JSON object "
            "per turn)"
        ),
    )
    parser.add_argument(
        "--parse-error-policy",
        default="silent",
        choices=list(PARSE_ERROR_POLICIES),
        help=(
            "what the react loop does when a turn is not a legal Action: silent (execute a "
            "get_profile fallback, the published behaviour), feedback (say so and re-ask), "
            "resample (re-ask without saying so -- the control for feedback)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
        contract=args.contract,
        temperature=args.temperature,
        parse_error_policy=args.parse_error_policy,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
