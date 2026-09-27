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
from nutrienv.harness.react import context_messages


def _windowed_messages(
    messages: list[dict[str, Any]], limit: int | None
) -> list[dict[str, Any]]:
    """Slide the same window the text harness uses, then restore FC pairing.

    ``context_messages`` keeps the pinned head plus a raw tail, which is fine for a
    text transcript but breaks native FC in two ways: a ``role: "tool"`` reply can
    lose the assistant ``tool_calls`` message that owns it, and an assistant with
    ``tool_calls`` can lose its replies. Providers reject both. So after the slide,
    keep only complete, correctly ordered call/reply pairs.
    """
    windowed = context_messages(messages, limit=limit)
    if limit is None:
        return windowed

    # Forward pass: a tool reply is kept only when it answers the assistant turn
    # that directly precedes it (and only once).
    ordered: list[dict[str, Any]] = []
    pending: set[Any] = set()
    for message in windowed:
        role = message.get("role")
        if role == "assistant":
            pending = {call.get("id") for call in (message.get("tool_calls") or [])}
            ordered.append(message)
        elif role == "tool":
            if message.get("tool_call_id") in pending:
                pending.discard(message.get("tool_call_id"))
                ordered.append(message)
        else:
            pending = set()
            ordered.append(message)

    # Backward pass: drop tool_calls that never got an answer.
    answered = {m.get("tool_call_id") for m in ordered if m.get("role") == "tool"}
    repaired: list[dict[str, Any]] = []
    for message in ordered:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            remaining = [c for c in message["tool_calls"] if c.get("id") in answered]
            if not remaining:
                message = {k: v for k, v in message.items() if k != "tool_calls"}
                if not message.get("content"):
                    continue
            else:
                message = {**message, "tool_calls": remaining}
        repaired.append(message)
    return repaired


class ToolCallInfraError(RuntimeError):
    """Raised on unrecoverable network/infrastructure failure."""
    pass


# The native-tools counterparts of react.PARSE_ERROR_FEEDBACK / PARSE_ERROR_RESAMPLE: the same
# information, phrased for a turn that failed to call a tool rather than to emit a JSON object.
TOOL_ERROR_FEEDBACK = (
    "Your previous message was not a legal action and nothing was executed; the world is "
    "unchanged. Call exactly one of the provided tools, with JSON-object arguments. "
    "Your message began: %(echo)r"
)
TOOL_ERROR_RESAMPLE = "Continue. Call one tool."

# `done`/`stop` are legal finish names in the text arm too, though only `finish` is offered.
_TOOL_NAMES = frozenset(tool["function"]["name"] for tool in NUTRIENV_TOOLS) | FINISH_OPS


def _usage_counts(body: dict, messages: list, text: str) -> tuple[int, int, int, bool]:
    """(prompt, completion, reasoning, measured) with the text loop's fallbacks.

    `or`, not a `.get` default: a provider that sends a key with a null value must fall back too.
    """
    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    prompt = usage.get("prompt_tokens") or len(json.dumps(messages, default=str)) // 4
    completion = usage.get("completion_tokens") or len(text) // 4
    reasoning = details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0
    return int(prompt), int(completion), int(reasoning), bool(usage)


def _observation_turn(remaining: int, observation: Any) -> str:
    """The text loop's per-step observation message, byte for byte."""
    return (
        f"Step budget: {remaining} action(s) remaining.\n"
        f"Observation:\n{json.dumps(observation, default=str)[:6000]}"
    )


def _resolve_call(call: dict) -> tuple[dict | None, str | None]:
    """The native-tools analogue of react.resolve_action: (action, None) or (parsed, why)."""
    func = call.get("function") or {}
    name = func.get("name")
    raw = func.get("arguments")
    if isinstance(raw, dict):  # some gateways send the object already decoded
        args = raw
    else:
        try:
            args = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return None, "no_action"
    if not isinstance(args, dict):
        return None, "no_action"
    action = {"op": name, **args}
    if name not in _TOOL_NAMES:
        return action, "unknown_op"
    return action, None


def run_episode_tool_call(
    task,
    harness_spec: dict[str, Any],
    catalog: Any,
    step_telemetry_cls: Any,
    task_telemetry_cls: Any,
) -> Any:
    """Execute one episode using native tool calling.

    Turn handling mirrors the text loop in scripts/eval_benchmark_suite.py: the same opening
    messages and per-step observation text, the same parse-error policies (a turn with no tool
    call, or arguments that are not a JSON object, is `no_action`; an unknown tool is
    `unknown_op`), the same refused-hand-in rule and the same telemetry. Only how an action is
    expressed differs.
    """
    env = NutriEnv()
    observation = env.reset(task.s0)
    scorer = Scorer()
    policy = harness_spec.get("parse_error_policy", "silent")

    max_steps = FAMILY_MAX_STEPS.get(task.family, DEFAULT_MAX_STEPS)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": TOOL_SYSTEM_PROMPT},
        {"role": "user", "content": f"Task:\n{task.query}"},
        {"role": "user", "content": _observation_turn(max_steps, observation)},
    ]

    steps = []
    tool_counts: dict[str, int] = {}
    invalid_tool_count = 0
    protocol_violations = 0
    violation_log: list[dict] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reasoning_tokens = 0
    total_tokens = 0

    t_start = time.time()
    terminated = False
    for step_i in range(max_steps):
        t0 = time.time()
        payload: dict[str, Any] = {
            "model": harness_spec["model"],
            "messages": _windowed_messages(messages, harness_spec.get("context_limit")),
            "tools": NUTRIENV_TOOLS,
            "temperature": harness_spec.get("temperature", 0.0),
            "parallel_tool_calls": harness_spec.get("parallel_tool_calls", False),
        }
        if "extra_body" in harness_spec:
            payload.update(harness_spec["extra_body"])

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
            raise ToolCallInfraError(f"Step {step_i+1} tool call API failure: {exc}") from exc

        step_latency = time.time() - t0
        if not isinstance(body, dict):  # shared with the text loop's guard below
            body = {}
        choices = body.get("choices") or [{}]
        if not isinstance(choices, list):
            choices = [{}]
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):  # a malformed body is the model's no_action
            tool_calls = []
        p_tok, c_tok, r_tok, measured = _usage_counts(body, messages, content)
        total_prompt_tokens += p_tok
        total_completion_tokens += c_tok
        total_reasoning_tokens += r_tok
        total_tokens += p_tok + c_tok
        remaining = max(0, max_steps - step_i - 1)

        def count(action) -> bool:
            """The text loop's accounting: an unknown op is an invalid tool, keyed apart."""
            nonlocal invalid_tool_count
            op = str(action.get("op"))
            valid = op in _TOOL_NAMES
            if not valid:
                invalid_tool_count += 1
                op = "invalid_format_fallback"
            tool_counts[op] = tool_counts.get(op, 0) + 1
            return valid

        def record(action, why, obs, *, refused=False, raw=None):
            nonlocal protocol_violations
            if why:
                protocol_violations += 1
                violation_log.append(
                    {"step_index": step_i + 1, "reason": why, "policy": policy,
                     "text": (raw or "")[:1200]}
                )
            steps.append(
                step_telemetry_cls(
                    step_index=step_i + 1,
                    action=action,
                    observation_snippet=str(obs)[:200],
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    reasoning_tokens=r_tok,
                    total_tokens=p_tok + c_tok,
                    latency_seconds=step_latency,
                    is_valid_tool=str(action.get("op")) in _TOOL_NAMES,
                    tokens_measured=measured,
                    protocol_violation=bool(why),
                    violation_reason=why,
                    raw_text=(raw or "")[:1200] if why else None,
                    refused=refused,
                )
            )

        def execute(action):
            nonlocal observation
            result = env.step(action)
            if result.get("ok") and isinstance(result.get("observation"), dict):
                observation = result["observation"]
            else:
                observation = {"error": result.get("error")}
            return not result.get("ok")

        if not tool_calls:
            # A turn with no tool call is the text loop's `no_action`, recorded as its fallback.
            messages.append({"role": "assistant", "content": content})
            action = {"op": "get_profile"}
            count(action)
            if policy == "silent":
                refused = execute(action)
                record(action, "no_action", observation, refused=refused, raw=content)
            else:
                record(action, "no_action", observation, raw=content)
                messages.append({"role": "user", "content": _tool_feedback(policy, content)})
            messages.append({"role": "user", "content": _observation_turn(remaining, observation)})
            continue

        allow_parallel = harness_spec.get("parallel_tool_calls", False)
        calls = tool_calls if allow_parallel else tool_calls[:1]
        # Every call in the assistant turn needs a reply under the same id, so keep only the
        # calls executed and give an id-less one the id its reply will carry.
        calls = [
            call if isinstance(call, dict) and call.get("id")
            else {**(call if isinstance(call, dict) else {}), "id": f"call_{step_i}_{index}"}
            for index, call in enumerate(calls)
        ]
        message = {**message, "tool_calls": calls}
        messages.append(message)

        for call in calls:
            call_id = call["id"]
            func = call.get("function") or {}
            # What the model called, for the log, even when its arguments fell back.
            called = f"{func.get('name')}({func.get('arguments') or ''})"
            parsed, why = _resolve_call(call)
            action = parsed if parsed is not None else {"op": "get_profile"}
            op = str(action.get("op"))
            count(action)
            if why and policy != "silent":
                record(action, why, observation, raw=called)
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": _tool_feedback(policy, called)})
                messages.append({"role": "user", "content": _observation_turn(remaining, observation)})
                continue
            if op in FINISH_OPS:
                record(action, why, {"op": "finish", "done": True}, raw=called)
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": json.dumps({"op": "finish", "done": True})})
                terminated = True
                break
            refused = execute(action)
            record(action, why, observation, refused=refused, raw=called)
            messages.append({"role": "tool", "tool_call_id": call_id,
                             "content": _observation_turn(remaining, observation)})
            # A hand-in ends the episode only when Env accepted it (runner.LOOP_VERSION l2).
            if op == "submit_plan" and not refused:
                terminated = True
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


def _tool_feedback(policy: str, text: str) -> str:
    if policy == "feedback":
        return TOOL_ERROR_FEEDBACK % {"echo": text[:200]}
    if policy == "resample":
        return TOOL_ERROR_RESAMPLE
    raise ValueError(f"no feedback for policy {policy!r}")
