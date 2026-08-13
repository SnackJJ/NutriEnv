"""Minimal ReAct loop: model text in, one Env action out. No scoring here."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

from .protocol import Harness

__all__ = ["ReActHarness", "load_dotenv_keys"]

_OPS = (
    "search_foods",
    "get_food",
    "get_profile",
    "get_ledger",
    "get_dri",
    "log_meal",
    "submit_plan",
    "update_profile",
    "update_plan",
)

_SYSTEM = """You are a nutrition agent in NutriEnv.
Each turn emit exactly one JSON object, no markdown, no extra keys at the top:
{"op": "<one of the ops>", ...args}

Ops:
- search_foods {q}
- get_food {food_id}
- get_profile
- get_ledger
- get_dri
- log_meal {food_id, grams, eaten_at?}
- submit_plan {items: [{food_id, grams}, ...]}
- update_profile {patch}
- update_plan {patch}

Numbers for nutrients must come from tool observations, not your head.
food_id must be a catalog id you have seen. Illegal ids are rejected.
When the user task is done, still emit a legal action (get_profile is fine if nothing left).
"""


def load_dotenv_keys(*paths: Path) -> None:
    """Load KEY=value from files into os.environ if the key is unset."""
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


class ReActHarness(Harness):
    """OpenAI-compatible Chat Completions (DeepSeek default)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com/v1/chat/completions",
        model: str = "deepseek-chat",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.messages: list[dict] = [{"role": "system", "content": _SYSTEM}]

    def act(self, observation: dict, query: str, history: list) -> dict:
        if len(self.messages) == 1:
            self.messages.append({"role": "user", "content": f"Task:\n{query}"})
        self.messages.append(
            {
                "role": "user",
                "content": "Observation:\n" + json.dumps(observation, default=str)[:6000],
            }
        )
        text = self._complete()
        self.messages.append({"role": "assistant", "content": text})
        action = _parse_action(text)
        if action.get("op") not in _OPS:
            return {"op": "get_profile"}
        return action

    def _complete(self) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": self.messages[-12:],
                "temperature": 0.0,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]


def _parse_action(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            text = match.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"op": "get_profile"}
    return data if isinstance(data, dict) else {"op": "get_profile"}
