"""OpenAI-compatible chat completions over urllib. No SDK."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http.client import IncompleteRead
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
]

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/v1/chat/completions"
DASHSCOPE_CHAT_URL = (
    "https://llm-dhaosul25kqjxu10.cn-beijing.maas.aliyuncs.com"
    "/compatible-mode/v1/chat/completions"
)
# opencode-go gateway: the operator configures base URL / key in env
# (OPENCODE_BASE_URL / OPENCODE_API_KEY). There is no built-in default URL;
# an unset base URL makes the opencode route unavailable, fail-closed.
OPENCODE_DEFAULT_URL = ""

# ReAct retries only network-class failures. Judge retries any Exception
# (including JSON/shape errors). Do not merge the two sets.
REACT_RETRY_ON: tuple[type[BaseException], ...] = (
    IncompleteRead,
    urllib.error.URLError,
    TimeoutError,
    OSError,
)
JUDGE_RETRY_ON: tuple[type[BaseException], ...] = (Exception,)


def post_chat_completion(
    url: str,
    payload: dict,
    api_key: str,
    timeout: float,
    retries: int = 3,
    retry_on: tuple[type[BaseException], ...] = REACT_RETRY_ON,
    error_prefix: str = "request failed",
) -> str:
    """POST one chat completion and return ``choices[0].message.content``."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # Some OpenAI-compatible gateways (e.g. opencode.ai/zen) sit behind
            # Cloudflare and reject urllib's default python UA (403/1010).
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return _message_text(body)
        except retry_on as exc:
            last_error = exc
            time.sleep(2 ** attempt)
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


def _dashscope(model_id: str, *, disabled: bool = False) -> ChatModel:
    return ChatModel(
        model_id=model_id,
        url=DASHSCOPE_CHAT_URL,
        api_key_env="DASHSCOPE_API_KEY",
        disabled=disabled,
    )


def _deepseek_via_dashscope(model_id: str, *, disabled: bool = False) -> ChatModel:
    """DeepSeek snapshot ids are hosted on DashScope. No api.deepseek.com path."""
    return _dashscope(model_id, disabled=disabled)


# Roadmap expander pool. All ids, including DeepSeek snapshots, are 百炼/DashScope.
EXPANDER_MODELS: dict[str, ChatModel] = {
    "qwen3.8-2.4t-a95b": _dashscope("qwen3.8-2.4t-a95b"),
    "qwen3.8-max": _dashscope("qwen3.8-max"),
    "deepseek-v4-pro-0813": _deepseek_via_dashscope("deepseek-v4-pro-0813"),
    "deepseek-v4-flash-0731": _deepseek_via_dashscope("deepseek-v4-flash-0731"),
    "glm-5.2": _dashscope("glm-5.2"),
    "kimi-k2.7-code": _dashscope("kimi-k2.7-code"),
}


def lookup_chat_model(model_id: str) -> ChatModel:
    """Registry hit, else the configured opencode gateway, else heuristics.

    The opencode-go gateway is configured only through environment: when both
    OPENCODE_BASE_URL and OPENCODE_API_KEY are set, any unlisted model id
    routes there verbatim (the operator owns that catalog). Without both, the
    route is unavailable and unknown ids fall back to the DashScope/DeepSeek
    heuristics as before.
    """
    known = EXPANDER_MODELS.get(model_id)
    if known is not None:
        return known
    lowered = model_id.lower()
    if any(tag in lowered for tag in _DASHSCOPE_HINTS):
        # DashScope-flavoured ids keep their historical route even when an
        # opencode gateway is configured, so qwen/glm/kimi resolution is
        # stable across environments. Use an opencode-specific id (e.g.
        # minimax-m3) to reach the opencode gateway.
        return _dashscope(model_id)
    if _opencode_route() is not None:
        url, key_env = _opencode_route()
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
    last_error: Exception | None = None
    for url, mid, key_env in attempts:
        api_key = os.environ.get(key_env)
        if not api_key:
            last_error = RuntimeError(f"{key_env} is not set")
            continue
        payload = {
            "model": mid,
            "messages": [dict(item) for item in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if any(h in url for h in ("dashscope", "aliyuncs")):
            payload["extra_body"] = {"enable_thinking": False}
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
