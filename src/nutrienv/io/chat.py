"""OpenAI-compatible chat completions over urllib. No SDK."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPException, IncompleteRead
from pathlib import Path

from .dotenv import load_dotenv_keys

__all__ = [
    "DEEPSEEK_CHAT_URL",
    "DASHSCOPE_CHAT_URL",
    "OPENCODE_DEFAULT_URL",
    "REACT_RETRY_ON",
    "JUDGE_RETRY_ON",
    "ChatModel",
    "EXPANDER_MODELS",
    "complete_chat",
    "lookup_chat_model",
    "post_chat_completion",
    "post_chat_completion_raw",
]

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/v1/chat/completions"
DASHSCOPE_CHAT_URL = (
    "https://llm-dhaosul25kqjxu10.cn-beijing.maas.aliyuncs.com"
    "/compatible-mode/v1/chat/completions"
)
# Command Code provider API (GOAT/Go plans). OpenAI-compatible surface; the plan
# reaches snapshot ids that the vendors' own APIs have already retired (e.g.
# deepseek-v4.1-flash). Override with COMMANDCODE_BASE_URL when the route moves.
COMMANDCODE_CHAT_URL = "https://api.commandcode.ai/provider/v1/chat/completions"

# Providers this tree used and no longer has. Kept as an explicit table so a stale model id
# names its own cause instead of resolving to a different provider's endpoint.
REMOVED_ROUTES = {
    "ark/": "the ARK plan endpoint, removed 2026-09-21 when its quota ran out; use "
            "commandcode/<vendor>/<model> (see https://api.commandcode.ai/provider/v1/models)",
    "volc/": "the ARK plan endpoint, removed 2026-09-21; use commandcode/<vendor>/<model>",
    "volcengine/": "the ARK plan endpoint, removed 2026-09-21; use commandcode/<vendor>/<model>",
}
# opencode-go gateway: the operator configures base URL / key in env
# (OPENCODE_BASE_URL / OPENCODE_API_KEY). There is no built-in default URL;
# an unset base URL makes the opencode route unavailable, fail-closed.
OPENCODE_DEFAULT_URL = ""

# ReAct retries only network-class failures. Judge retries any Exception
# (including JSON/shape errors). Do not merge the two sets.
REACT_RETRY_ON: tuple[type[BaseException], ...] = (
    IncompleteRead,
    HTTPException,
    urllib.error.URLError,
    TimeoutError,
    OSError,
)
JUDGE_RETRY_ON: tuple[type[BaseException], ...] = (Exception,)


def _open_http(request: urllib.request.Request, *, timeout: float):
    """The one place this module opens a URL, scheme-checked first.

    These URLs come from the environment (`COMMANDCODE_BASE_URL`, `OPENCODE_BASE_URL`,
    `DASHSCOPE_BASE_URL`), and `urlopen` also speaks `file:` -- so a mistyped base URL would read
    a local file instead of calling a provider.
    """
    scheme = urllib.parse.urlsplit(request.full_url).scheme
    if scheme not in ("http", "https"):
        raise ValueError(f"refusing to open a non-http(s) URL: {request.full_url!r}")
    return urllib.request.urlopen(request, timeout=timeout)


def _chat_request(url: str, body: dict, api_key: str, accept: str | None = None):
    """One request builder, so the streaming and non-streaming paths cannot drift."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
    }
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )


def _should_retry_without_usage(exc: BaseException, stream: bool, include_usage: bool) -> bool:
    """True when a 400 is plausibly the provider rejecting ``stream_options``.

    ``stream_options`` is optional in the OpenAI-compatible surface but not universally
    implemented, and it is now sent on every streaming call. A provider that answers 400 to
    it would otherwise burn the whole retry budget and void the step. The usage block is a
    nicety, so drop it and try once more instead.
    """
    return (
        stream and include_usage and isinstance(exc, urllib.error.HTTPError) and exc.code == 400
    )


def _merge_tool_name(current: str, incoming: str, declared: set[str]) -> str:
    """Fold one ``function.name`` fragment into the name accumulated so far.

    Gateways disagree about how to stream a tool name, and every shape has to land on the
    same string:

    * sent once, then absent -- keep it
    * repeated verbatim in every delta -- ignore the repeat
    * split into fragments (``search``, ``_foods``) -- append
    * re-sent cumulatively (``sea``, ``search_``, ``search_foods``) -- replace

    A plain ``+=`` corrupts the repeat shape, and an ``endswith`` guard corrupts a fragment
    that happens to be a suffix of what precedes it (``asses`` + ``s``). ``declared`` is the
    set of tool names the request actually offered, which is what makes cumulative and
    fragment shapes distinguishable.
    """
    if not current:
        return incoming
    if incoming == current:
        return current
    if current in declared:
        return current
    if incoming in declared or incoming.startswith(current):
        return incoming
    return current + incoming


def _absorb_tool_call(call: dict, slots: dict, declared: set[str], current: int) -> int:
    """Merge one ``tool_calls`` fragment into ``slots``; returns the slot fragments default to."""
    index = call.get("index")
    if index is None:
        # A gateway that omits `index` on parallel calls would otherwise merge every call into
        # slot 0 and hand back one concatenated name. A fresh `id` is the only new-call signal
        # available there; a fragment without one belongs to the call already in progress.
        cid = call.get("id")
        if cid:
            index = next((i for i, s in slots.items() if s.get("id") == cid), None)
            if index is None:
                index = max(slots) + 1 if slots else 0
        else:
            index = current
    slot = slots.setdefault(
        index, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}
    )
    if call.get("id"):
        slot["id"] = call["id"]
    fn = call.get("function") or {}
    if fn.get("name"):
        slot["function"]["name"] = _merge_tool_name(slot["function"]["name"], fn["name"], declared)
    if fn.get("arguments"):
        slot["function"]["arguments"] += fn["arguments"]
    return index


class StreamTruncated(IncompleteRead):
    """An SSE stream that never terminated, or carried nothing usable.

    Subclasses :class:`IncompleteRead` so the existing retry sets already own it, but keeps a
    readable message: ``IncompleteRead.__str__`` is its ``__repr__``, which drops any
    explanation and leaves only a byte count, and that byte count is what would otherwise
    reach the report as the VOID reason.
    """

    def __init__(self, message: str):
        super().__init__(b"", 0)
        self.message = message

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return self.message


def _assemble_stream(
    url: str,
    payload: dict,
    api_key: str,
    timeout: float,
    error_prefix: str,
    include_usage: bool = True,
) -> dict:
    """POST with ``stream=True`` and return an OpenAI-shaped response body.

    Non-streaming requests are the reason long agent steps looked like hangs: a reasoning
    model can think for minutes before emitting anything, and with no bytes on the socket the
    client's read timeout fires, drops the connection and resends from scratch, losing all
    the work already done server-side. Streaming keeps bytes flowing (measured max gap
    ~0.3 s), so a 300 s step completes in one call instead of 180+180+180+138.

    An unterminated stream is a truncated response, not a short answer. The non-streaming
    path raised on one (``json.loads`` over a cut body); accepting it would grade a
    half-written action as the model's answer, which is the acceptance bug ADR 0028 §2.1
    deleted the ``{"op": "finish"}`` forgery for. ``IncompleteRead`` is in ``REACT_RETRY_ON``,
    so the retry loop and the VOID path own it.
    """
    body = dict(payload)
    body["stream"] = True
    # Ask for the usage block in the final chunk; some gateways only send it this way.
    if include_usage:
        body.setdefault("stream_options", {"include_usage": True})

    declared = {
        tool["function"]["name"]
        for tool in (payload.get("tools") or [])
        if isinstance(tool, dict)
        and isinstance(tool.get("function"), dict)
        and tool["function"].get("name")
    }

    content: list[str] = []
    reasoning: list[str] = []
    tool_slots: dict[int, dict] = {}
    usage: dict = {}
    finish: str | None = None
    saw_frame = False
    saw_done = False
    current_slot = 0

    with _open_http(
        _chat_request(url, body, api_key, accept="text/event-stream"), timeout=timeout
    ) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                saw_done = True
                continue
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            saw_frame = True
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                # Some gateways answer a `stream: true` request with whole messages rather than
                # deltas; assembling only `delta` returned an empty reply with no error.
                whole = choice.get("message")
                if isinstance(whole, dict):
                    if isinstance(whole.get("content"), str):
                        content.append(whole["content"])
                    if isinstance(whole.get("reasoning_content"), str):
                        reasoning.append(whole["reasoning_content"])
                    for call in whole.get("tool_calls") or []:
                        if isinstance(call, dict):
                            current_slot = _absorb_tool_call(
                                call, tool_slots, declared, current_slot
                            )
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    if isinstance(delta.get("content"), str):
                        content.append(delta["content"])
                    if isinstance(delta.get("reasoning_content"), str):
                        reasoning.append(delta["reasoning_content"])
                    for call in delta.get("tool_calls") or []:
                        if isinstance(call, dict):
                            current_slot = _absorb_tool_call(
                                call, tool_slots, declared, current_slot
                            )
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]

    content_text = "".join(content)
    reasoning_text = "".join(reasoning)
    # A lone `[DONE]` is a terminated-but-empty stream, not a provider that ignored
    # `stream: true`, so the "not streaming at all" case needs both signals absent.
    if not saw_frame and not saw_done:
        raise StreamTruncated("no SSE frame arrived (provider may not honour stream:true)")
    if not saw_done and finish is None:
        raise StreamTruncated(
            "stream ended without [DONE] or finish_reason; "
            f"partial={content_text[:60]!r}"
        )
    if not content_text.strip() and not reasoning_text.strip() and not tool_slots:
        raise StreamTruncated("stream carried no content, reasoning or tool calls")

    message: dict = {"role": "assistant", "content": content_text}
    if reasoning_text:
        message["reasoning_content"] = reasoning_text
    if tool_slots:
        message["tool_calls"] = [tool_slots[k] for k in sorted(tool_slots)]
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": usage}


def post_chat_completion(
    url: str,
    payload: dict,
    api_key: str,
    timeout: float,
    retries: int = 3,
    retry_on: tuple[type[BaseException], ...] = REACT_RETRY_ON,
    error_prefix: str = "request failed",
    stream: bool = True,
    include_usage: bool = True,
) -> str:
    """POST one chat completion and return ``choices[0].message.content``."""
    import socket
    socket.setdefaulttimeout(timeout)
    # `retry_on` is a tuple of BaseException classes, so what it catches is not
    # necessarily an Exception; the annotation has to match the except clause.
    last_error: BaseException | None = None
    for attempt in range(retries):
        try:
            if stream:
                return _message_text(
                    _assemble_stream(
                        url, payload, api_key, timeout, error_prefix, include_usage=include_usage
                    )
                )
            with _open_http(
                _chat_request(url, payload, api_key), timeout=timeout
            ) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return _message_text(body)
        except retry_on as exc:
            if _should_retry_without_usage(exc, stream, include_usage):
                include_usage = False
                last_error = exc
                continue
            last_error = exc
            sleep_time = float(2 ** attempt)
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                sleep_time = max(sleep_time, 4.0 * (attempt + 1))
            time.sleep(sleep_time)
    raise RuntimeError(f"{error_prefix}: {last_error}") from last_error


def post_chat_completion_raw(
    url: str,
    payload: dict,
    api_key: str,
    timeout: float,
    retries: int = 3,
    retry_on: tuple[type[BaseException], ...] = REACT_RETRY_ON,
    error_prefix: str = "request failed",
    stream: bool = True,
    include_usage: bool = True,
) -> dict:
    """POST one chat completion and return the full parsed body dict."""
    import socket
    socket.setdefaulttimeout(timeout)
    # `retry_on` is a tuple of BaseException classes, so what it catches is not
    # necessarily an Exception; the annotation has to match the except clause.
    last_error: BaseException | None = None
    for attempt in range(retries):
        try:
            if stream:
                return _assemble_stream(
                    url, payload, api_key, timeout, error_prefix, include_usage=include_usage
                )
            with _open_http(
                _chat_request(url, payload, api_key), timeout=timeout
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except retry_on as exc:
            if _should_retry_without_usage(exc, stream, include_usage):
                include_usage = False
                last_error = exc
                continue
            last_error = exc
            sleep_time = float(2 ** attempt)
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                sleep_time = max(sleep_time, 4.0 * (attempt + 1))
            time.sleep(sleep_time)
    raise RuntimeError(f"{error_prefix}: {last_error}") from last_error



_ROOT = Path(__file__).resolve().parents[3]
_DASHSCOPE_HINTS = ("qwen", "glm", "kimi", "dashscope", "aliyuncs")


def _message_text(body: Mapping) -> str:
    """Prefer ``content``; reasoner models sometimes leave it empty."""
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(message, Mapping):
        return ""
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    return content if isinstance(content, str) else ""


@dataclass(frozen=True)
class ChatModel:
    """One chat-completions identity plus optional fallback provider."""

    model_id: str
    url: str
    api_key_env: str
    fallback_url: str | None = None
    fallback_model_id: str | None = None
    fallback_api_key_env: str | None = None
    disabled: bool = False


DEEPSEEK_CHAT_URL = "https://api.deepseek.com/v1/chat/completions"
NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def _deepseek_direct(model_id: str, *, disabled: bool = False) -> ChatModel:
    return ChatModel(
        model_id=model_id,
        url=DEEPSEEK_CHAT_URL,
        api_key_env="DEEPSEEK_API_KEY",
        disabled=disabled,
    )


def _dashscope(model_id: str, *, disabled: bool = False) -> ChatModel:
    return ChatModel(
        model_id=model_id,
        url=DASHSCOPE_CHAT_URL,
        api_key_env="DASHSCOPE_API_KEY",
        disabled=disabled,
    )


def _nvidia(model_id: str, *, disabled: bool = False) -> ChatModel:
    return ChatModel(
        model_id=model_id,
        url=NVIDIA_CHAT_URL,
        api_key_env="NVIDIA_API_KEY",
        disabled=disabled,
    )


def _deepseek_via_dashscope(model_id: str, *, disabled: bool = False) -> ChatModel:
    """DeepSeek snapshot ids are hosted on DashScope. No api.deepseek.com path."""
    return _dashscope(model_id, disabled=disabled)


# Roadmap expander pool.
EXPANDER_MODELS: dict[str, ChatModel] = {
    "deepseek-chat": _deepseek_direct("deepseek-chat"),
    "deepseek-reasoner": _deepseek_direct("deepseek-reasoner"),
    "qwen3.8-flash": _dashscope("qwen3.8-flash"),
    "qwen3.8-2.4t-a95b": _dashscope("qwen3.8-2.4t-a95b"),
    "qwen3.8-max": _dashscope("qwen3.8-max"),
    "deepseek-v4-pro-0813": _deepseek_via_dashscope("deepseek-v4-pro-0813"),
    "deepseek-v4-flash-0731": _deepseek_via_dashscope("deepseek-v4-flash-0731"),
    "glm-5.2": _dashscope("glm-5.2"),
    "kimi-k3": _dashscope("kimi-k3"),
    "moonshotai/kimi-k3": _dashscope("kimi-k3"),
}


def lookup_chat_model(model_id: str) -> ChatModel:
    """Registry hit, explicit provider prefix, else opencode gateway, else heuristics."""
    load_dotenv_keys(_ROOT / ".env", _ROOT / ".env.local")
    for prefix, why in REMOVED_ROUTES.items():
        if model_id.startswith(prefix):
            # Falls through to the heuristics otherwise: `ark/glm-5.3` contains "glm", so it
            # would be sent to DashScope and fail somewhere unrelated to the real cause.
            raise ValueError(f"{model_id!r} routes to {why}")
    if model_id.startswith(("opencode/", "opencode-go/")):
        real_id = model_id.split("/", 1)[1]
        route = _opencode_route()
        if route is not None:
            url, key_env = route
            return ChatModel(model_id=real_id, url=url, api_key_env=key_env)
    if model_id.startswith(("commandcode/", "cc/")):
        real_id = model_id.split("/", 1)[1]
        url = os.environ.get("COMMANDCODE_BASE_URL", COMMANDCODE_CHAT_URL)
        return ChatModel(model_id=real_id, url=url, api_key_env="COMMANDCODE_API_KEY")
    if model_id.startswith("nvidia/"):
        real_id = model_id.split("/", 1)[1]
        return _nvidia(real_id)
    if model_id.startswith("dashscope/"):
        real_id = model_id.split("/", 1)[1]
        return _dashscope(real_id)
    if model_id.startswith("deepseek/"):
        real_id = model_id.split("/", 1)[1]
        return _deepseek_direct(real_id)

    known = EXPANDER_MODELS.get(model_id)
    if known is not None:
        return known
    lowered = model_id.lower()
    if any(tag in lowered for tag in _DASHSCOPE_HINTS):
        # DashScope-flavoured ids keep their historical route even when an
        # opencode gateway is configured, so qwen/glm/kimi resolution is
        # stable across environments. Use an opencode prefix (e.g.
        # opencode-go/glm-5.3) to force opencode gateway routing.
        return _dashscope(model_id)
    opencode = _opencode_route()
    if opencode is not None:
        url, key_env = opencode
        return ChatModel(model_id=model_id, url=url, api_key_env=key_env)
    return ChatModel(
        model_id=model_id,
        url=DEEPSEEK_CHAT_URL,
        api_key_env="DEEPSEEK_API_KEY",
    )


def _opencode_route() -> tuple[str, str] | None:
    """(base_url, api_key_env) from OPENCODE_* env, or None when unavailable."""
    base_url = os.environ.get("OPENCODE_BASE_URL", OPENCODE_DEFAULT_URL).strip()
    if not base_url:
        return None
    key_env = "OPENCODE_API_KEY"
    return base_url, key_env


def complete_chat(
    model_id: str,
    messages: Sequence[Mapping[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 768,
    timeout: float = 60.0,
    retries: int = 3,
    retry_on: tuple[type[BaseException], ...] = REACT_RETRY_ON,
    allow_fallback: bool = True,
    attempt: str = "auto",
) -> str:
    """POST one completion for ``model_id``. Network-class errors are retried.

    Registered expander ids (including DeepSeek snapshots) use DashScope only.
    Missing API keys and exhausted retries raise; they are not swallowed.
    ``attempt`` is ``auto`` (primary then optional ChatModel fallback),
    ``primary``, or ``fallback``.
    """
    load_dotenv_keys(_ROOT / ".env", _ROOT / ".env.local")
    spec = lookup_chat_model(model_id)
    if spec.disabled:
        raise RuntimeError(f"expander model disabled: {model_id}")
    primary = (spec.url, spec.model_id, spec.api_key_env)
    fallback = None
    if spec.fallback_url and spec.fallback_api_key_env:
        fallback = (
            spec.fallback_url,
            spec.fallback_model_id or spec.model_id,
            spec.fallback_api_key_env,
        )
    if attempt == "primary" or (attempt == "auto" and not allow_fallback):
        attempts = [primary]
    elif attempt == "fallback":
        if fallback is None:
            raise RuntimeError(f"{model_id} has no fallback provider")
        attempts = [fallback]
    elif attempt == "auto":
        attempts = [primary] + ([fallback] if allow_fallback and fallback else [])
    else:
        raise ValueError(f"unknown complete_chat attempt {attempt!r}")
    # `retry_on` is a tuple of BaseException classes, so what it catches is not
    # necessarily an Exception; the annotation has to match the except clause.
    last_error: BaseException | None = None
    for url, mid, key_env in attempts:
        api_key = os.environ.get(key_env)
        if not api_key:
            last_error = RuntimeError(f"{key_env} is not set")
            continue
        payload = {
            "model": mid,
            "messages": [dict(item) for item in messages],
            "max_tokens": max_tokens,
        }
        if "kimi-k3" not in mid.lower():
            payload["temperature"] = temperature
        try:
            text = post_chat_completion(
                url,
                payload,
                api_key,
                timeout=timeout,
                retries=retries,
                retry_on=retry_on,
                error_prefix=f"{mid} request failed",
            )
        except RuntimeError as exc:
            last_error = exc
            continue
        return text or ""
    raise RuntimeError(f"{model_id} request failed: {last_error}") from last_error
