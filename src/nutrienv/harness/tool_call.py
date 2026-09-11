"""Native Tool Calling Harness: clean OpenAI/Anthropic/DeepSeek function calling loop."""

from __future__ import annotations

import json
import time
from typing import Any

from nutrienv.env import NutriEnv
from nutrienv.bench.scorer import Scorer
from nutrienv.harness.runner import FAMILY_MAX_STEPS, DEFAULT_MAX_STEPS, FINISH_OPS
from nutrienv.harness.tools_schema import NUTRIENV_TOOLS, TOOL_SYSTEM_PROMPT
from nutrienv.io.chat import post_chat_completion_raw, REACT_RETRY_ON


class ToolCallInfraError(RuntimeError):
    """Raised on unrecoverable network/infrastructure failure."""
    pass


def run_episode_tool_call(
    task,
    harness_spec: dict[str, Any],
    catalog: Any,
    step_telemetry_cls: Any,
    task_telemetry_cls: Any,
) -> Any:
    """Execute one episode using native tool calling."""
    env = NutriEnv()
    observation = env.reset(task.s0)
    scorer = Scorer()

    max_steps = FAMILY_MAX_STEPS.get(task.family, DEFAULT_MAX_STEPS)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": TOOL_SYSTEM_PROMPT},
        {"role": "user", "content": f"Task:\n{task.query}\nInitial observation:\n{json.dumps(observation, default=str)}"}
    ]

    steps = []
    tool_counts: dict[str, int] = {}
    invalid_tool_count = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reasoning_tokens = 0
    total_tokens = 0

    t_start = time.time()
    for step_i in range(max_steps):
        t0 = time.time()
        payload: dict[str, Any] = {
            "model": harness_spec["model"],
            "messages": messages,
            "tools": NUTRIENV_TOOLS,
            "temperature": 0.0,
            "parallel_tool_calls": harness_spec.get("parallel_tool_calls", False),
        }
        if "extra_body" in harness_spec:
            payload.update(harness_spec["extra_body"])

        body = {}
        err = None
        try:
            body = post_chat_completion_raw(
                harness_spec["url"],
                payload,
                harness_spec["api_key"],
                timeout=harness_spec.get("timeout", 90.0),
                retries=harness_spec.get("retries", 4),
                retry_on=REACT_RETRY_ON,
                error_prefix=f"{harness_spec['model']} native tool call failed",
            )
        except Exception as exc:
            err = str(exc)
            raise ToolCallInfraError(f"Step {step_i+1} tool call API failure: {err}") from exc

        step_latency = time.time() - t0

        choice = body.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = body.get("usage", {})

        p_tok = usage.get("prompt_tokens", len(json.dumps(messages)) // 4)
        c_tok = usage.get("completion_tokens", 0)
        r_tok = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)

        total_prompt_tokens += p_tok
        total_completion_tokens += c_tok
        total_reasoning_tokens += r_tok
        total_tokens += (p_tok + c_tok)

        tool_calls = message.get("tool_calls") or []

        # If model chose to respond with plain text instead of calling tools:
        if not tool_calls:
            # Model didn't call any tool; record and break if finished
            content_str = message.get("content") or ""
            step_telemetry = step_telemetry_cls(
                step_index=step_i + 1,
                action={"op": "text_response", "content": content_str[:200]},
                observation_snippet=str(observation)[:200],
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                reasoning_tokens=r_tok,
                total_tokens=p_tok + c_tok,
                latency_seconds=step_latency,
                is_valid_tool=False,
                error=err
            )
            steps.append(step_telemetry)
            messages.append({"role": "assistant", "content": content_str})
            messages.append({"role": "user", "content": "Please call an available tool to proceed or finish the task."})
            continue

        allow_parallel = harness_spec.get("parallel_tool_calls", False)
        # If parallel tool calls are disabled by harness, take only the first tool call
        calls_to_process = tool_calls if allow_parallel else tool_calls[:1]

        # In OpenAI API, if assistant message contained multiple tool calls, we must reply to all of them,
        # or we only record the executed one in assistant message if parallel is disabled.
        if not allow_parallel and len(tool_calls) > 1:
            # Replace message tool_calls with just the first call to keep conversation valid
            message = dict(message)
            message["tool_calls"] = calls_to_process

        messages.append(message)

        # Process all tool calls returned in this turn
        terminated = False
        step_index = step_i + 1
        for tc in calls_to_process:
            func = tc.get("function", {})
            func_name = func.get("name", "unknown")
            call_id = tc.get("id", f"call_{step_i}_{len(steps)}")

            args = {}
            try:
                args = json.loads(func.get("arguments", "{}"))
                if not isinstance(args, dict):
                    args = {}
            except Exception:
                args = {}

            action = {"op": func_name, **args}

            is_valid = func_name in (
                "search_foods", "get_food", "get_profile", "get_ledger", "get_dri",
                "log_meal", "submit_plan", "update_profile", "update_plan", "amend_meal",
                "finish"
            )
            if not is_valid:
                invalid_tool_count += 1
                op_label = "invalid_format_fallback"
            else:
                op_label = func_name

            tool_counts[op_label] = tool_counts.get(op_label, 0) + 1

            if func_name in FINISH_OPS:
                obs = {"op": "finish", "done": True}
                terminated = True
            else:
                result = env.step(action)
                if result.get("ok") and isinstance(result.get("observation"), dict):
                    obs = result["observation"]
                else:
                    obs = {"error": result.get("error")}

            step_telemetry = step_telemetry_cls(
                step_index=step_index,
                action=action,
                observation_snippet=str(obs)[:200],
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                reasoning_tokens=r_tok,
                total_tokens=p_tok + c_tok,
                latency_seconds=step_latency,
                is_valid_tool=is_valid,
                error=err
            )
            steps.append(step_telemetry)

            # Feed observation back as a tool message
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(obs, default=str)[:6000]
            })

            if func_name == "submit_plan":
                terminated = True
                break
            if terminated:
                break

        if terminated:
            break

    wall_time = time.time() - t_start
    score = scorer.score(env.state(), task.oracle)
    passed = bool(score.get("passed", False))
    score_tag = str(score.get("tag", "UNKNOWN"))
    allergen_violated = score_tag in ("allergy", "FatalAllergyClash")

    return task_telemetry_cls(
        task_id=task.id,
        family=task.family,
        query=task.query,
        persona=task.persona,
        passed=passed,
        score_tag=score_tag,
        n_steps=step_i + 1,
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
