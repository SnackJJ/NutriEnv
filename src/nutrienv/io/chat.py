"""OpenAI-compatible chat completions over urllib. No SDK."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from http.client import IncompleteRead

__all__ = [
    "DEEPSEEK_CHAT_URL",
    "DASHSCOPE_CHAT_URL",
    "REACT_RETRY_ON",
    "JUDGE_RETRY_ON",
    "post_chat_completion",
]

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/v1/chat/completions"
DASHSCOPE_CHAT_URL = (
    "https://llm-dhaosul25kqjxu10.cn-beijing.maas.aliyuncs.com"
    "/compatible-mode/v1/chat/completions"
)

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
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except retry_on as exc:
            last_error = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{error_prefix}: {last_error}") from last_error
