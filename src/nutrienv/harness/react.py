"""Minimal ReAct loop: model text in, one Env action out. No scoring here."""

from __future__ import annotations

import json
import os
import re

from nutrienv.actions.schemas import OPS
from nutrienv.io.chat import (
    DASHSCOPE_CHAT_URL,
    DEEPSEEK_CHAT_URL,
    REACT_RETRY_ON,
    post_chat_completion,
)
from nutrienv.io.dotenv import load_dotenv_keys

from .protocol import Harness
from .runner import DEFAULT_MAX_STEPS, FINISH_OPS

__all__ = [
    "ReActHarness",
    "REACT_VERSIONS",
    "load_dotenv_keys",
    "context_messages",
    "oracle_hint",
    "react_manual",
]

_OPS = frozenset(OPS) | FINISH_OPS

_CONTEXT_LIMIT = 12

_SYSTEM = """You are an agent in NutriEnv, a steppable nutrition world.
Each turn emit exactly one JSON object, no markdown, no extra top-level keys:
{"op": "<one of the ops>", ...args}

Available ops:
- search_foods {q}   (BM25 over the local USDA catalog; do not use q="*")
- get_food {food_id}
- get_profile
- get_ledger
- get_dri
- log_meal {food_id, grams, eaten_at?}
- submit_plan {items: [{food_id, grams}, ...]}
- update_profile {patch}
- update_plan {patch}
- finish  (hand-in: stop the episode; the current world is scored)

How an episode is graded:
- Writes apply immediately. The runner scores the end state when you finish, after a few idle reads, or when the step budget is gone.
- Text is not a hand-in. Recommend/evaluate tasks only Pass if you submit_plan. Log tasks only Pass if you log_meal the named foods.
- Fields the user did not ask to change must stay as the opening profile/ledger.
- food_id is a USDA fdc_id from search/get_food (staple slugs such as milk_whole also resolve). Unknown ids are rejected and change nothing.
- Nutrient numbers must come from observations, not prior knowledge. Catalog energy is per 100 g.
- log_meal without eaten_at is stamped "now". If the query names a meal, copy the ledger's token style (today-breakfast, today-lunch, …).
- A leftover / already-ate question: daily windows on get_profile are not the meal budget. Ledger rows may include nutrients; use them when present, otherwise use get_food. Subtract eaten nutrients from the daily windows, then submit_plan for the remainder.
- After the required writes, emit finish. submit_plan is a hand-in: do not update_plan afterwards.
- Profile allergies are catalog allergen_tags (shellfish, peanut), not food names. If last_plan already violates the windows, submit_plan {"items": []}.
"""

_SYSTEM_V1_TAIL = """
- Spoken household measures appear on get_food as portions: each key is one measure, the value is grams for one of that measure of that food. Convert the spoken quantity from that table. Do not invent grams from prior knowledge.
- Keys you may be asked for by name: cup, tbsp (tablespoon), tsp (teaspoon), slice, piece (also "each"), can, fl_oz (fluid ounce).
- "a serving / a portion / a bowl / a plate / an order of X", and a dish named as its own unit ("a sandwich", "two burritos"), all mean one default serving: read portions.qns; if the food has no qns, fall back to piece, then slice, then cup.
- A bare food noun with no unit ("one apple", "a banana", "two eggs") means that many pieces of the food: read portions.piece. A cut with no portion key ("a chicken breast") has no default; ask for grams.
- "thick", "thin" and "regular" pick a different default serving of the same food: read portions.thick / portions.thin / portions.regular. They are not slice sizes -- "a thick slice" is not portions.thick, and a food without that key has no thick/thin/regular serving.
- An ounce is always 28.35 g, whatever the table says. Grams ("150 g") are already grams.
- Other portion keys you may see (oz, oz_yield, cubic_inch) are reference data, not measures a user speaks. Do not convert with them.
"""

REACT_VERSIONS = ("v0", "v1")
_MANUALS = {
    "v0": _SYSTEM,
    "v1": _SYSTEM + _SYSTEM_V1_TAIL,
}


def react_manual(version: str) -> str:
    """Return the frozen ReAct system manual for a harness version."""
    if version not in _MANUALS:
        raise ValueError(f"unknown react harness version: {version!r}")
    return _MANUALS[version]


def context_messages(messages: list[dict], *, limit: int = _CONTEXT_LIMIT) -> list[dict]:
    """Keep the system manual and the Task line when the window slides.

    A raw ``messages[-N:]`` drop drops both after a few steps, so the model
    forgets the ops and the query. Pin those two; slide only the trajectory.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if len(messages) <= limit:
        return list(messages)
    pinned: list[dict] = []
    rest = list(messages)
    if rest and rest[0].get("role") == "system":
        pinned.append(rest.pop(0))
    if (
        rest
        and rest[0].get("role") == "user"
        and str(rest[0].get("content", "")).startswith("Task:")
    ):
        pinned.append(rest.pop(0))
    room = limit - len(pinned)
    if room <= 0:
        return pinned[:limit]
    return pinned + rest[-room:]


def oracle_hint(oracle: object) -> str:
    """Serialize one Task Oracle for a diagnostic leak. Not a published prompt."""
    payload: dict = {}
    profile = getattr(oracle, "profile", None)
    if profile is not None:
        payload["profile"] = {
            "allergies": list(profile.allergies),
            "medications": list(profile.medications),
            "windows": {key: list(bounds) for key, bounds in profile.windows.items()},
            "plan_preset": dict(profile.plan_preset),
            "version": profile.version,
        }
    tail = getattr(oracle, "ledger_tail", None)
    if tail is not None:
        payload["ledger_tail"] = [
            {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at}
            for row in tail
        ]
    ledger = getattr(oracle, "ledger", None)
    if ledger is not None:
        payload["ledger"] = [
            {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at}
            for row in ledger
        ]
    last_plan = getattr(oracle, "last_plan", None)
    if last_plan is not None:
        payload["last_plan"] = last_plan
        if last_plan == []:
            payload["last_plan_note"] = (
                "empty list means submit any non-empty allergen-safe plan "
                "that fits the judged windows"
            )
    plan_windows = getattr(oracle, "plan_windows", None)
    if plan_windows is not None:
        payload["plan_windows"] = {
            key: list(bounds) for key, bounds in plan_windows.items()
        }
    payload["plan_must_be_safe"] = bool(getattr(oracle, "plan_must_be_safe", False))
    payload["plan_must_fit_windows"] = bool(
        getattr(oracle, "plan_must_fit_windows", False)
    )
    payload["allow_empty_plan"] = bool(getattr(oracle, "allow_empty_plan", False))
    return (
        "DIAGNOSTIC LEAK — expected end state for this episode. "
        "Issue the matching Env writes. Do not change unmentioned fields.\n"
        + json.dumps(payload, default=str)
    )


def _looks_like_qwen(model: str, base_url: str) -> bool:
    lowered = f"{model} {base_url}".lower()
    return "qwen" in lowered or "dashscope" in lowered or "aliyuncs.com" in lowered


class ReActHarness(Harness):
    """OpenAI-compatible Chat Completions (DeepSeek default)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-chat",
        timeout: float = 60.0,
        leak_oracle: bool = False,
        max_steps: int = DEFAULT_MAX_STEPS,
        extra_body: dict | None = None,
        version: str = "v0",
    ) -> None:
        if version not in REACT_VERSIONS:
            raise ValueError(f"unknown react harness version: {version!r}")
        qwen = _looks_like_qwen(model, base_url or "")
        self.base_url = base_url or (DASHSCOPE_CHAT_URL if qwen else DEEPSEEK_CHAT_URL)
        self.api_key = api_key or (
            os.environ.get("DASHSCOPE_API_KEY") if qwen else os.environ.get("DEEPSEEK_API_KEY")
        )
        if not self.api_key:
            needed = "DASHSCOPE_API_KEY" if qwen else "DEEPSEEK_API_KEY"
            raise RuntimeError(f"{needed} is not set")
        self.model = model
        self.timeout = timeout
        self.leak_oracle = leak_oracle
        self.max_steps = max_steps
        self.extra_body = dict(extra_body or {})
        self.version = version
        self.messages: list[dict] = [{"role": "system", "content": react_manual(version)}]

    @property
    def label(self) -> str:
        return f"react-{self.version}"

    def clone(self) -> "ReActHarness":
        """Fresh message log, same endpoint settings."""
        return ReActHarness(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            timeout=self.timeout,
            leak_oracle=self.leak_oracle,
            max_steps=self.max_steps,
            extra_body=self.extra_body,
            version=self.version,
        )

    def reset(self, task: object | None = None) -> None:
        """Drop episode history so the next Task cannot see the last one."""
        system = react_manual(self.version)
        oracle = getattr(task, "oracle", None) if task is not None else None
        if self.leak_oracle and oracle is not None:
            system = system + "\n\n" + oracle_hint(oracle)
        self.messages = [{"role": "system", "content": system}]

    def act(self, observation: dict, query: str, history: list) -> dict:
        if len(self.messages) == 1:
            self.messages.append({"role": "user", "content": f"Task:\n{query}"})
        remaining = max(0, self.max_steps - len(history))
        self.messages.append(
            {
                "role": "user",
                "content": (
                    f"Step budget: {remaining} action(s) remaining, including this turn.\n"
                    "Observation:\n"
                    + json.dumps(observation, default=str)[:6000]
                ),
            }
        )
        text = self._complete()
        self.messages.append({"role": "assistant", "content": text})
        action = _parse_action(text)
        if action.get("op") not in _OPS:
            return {"op": "get_profile"}
        return action

    def _complete(self) -> str:
        payload = {
            "model": self.model,
            "messages": context_messages(self.messages),
            "temperature": 0.0,
            **self.extra_body,
        }
        return post_chat_completion(
            self.base_url,
            payload,
            self.api_key,
            timeout=self.timeout,
            retries=3,
            retry_on=REACT_RETRY_ON,
            error_prefix="DeepSeek request failed after retries",
        )


def _parse_action(text: str) -> dict:
    """Return the first complete JSON object, tolerating prose or a code fence."""
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.S | re.I)
    candidates = [fenced.group(1), stripped] if fenced else [stripped]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        first = len(candidate) - len(candidate.lstrip())
        if first < len(candidate) and candidate[first] in "[{":
            try:
                data, _ = decoder.raw_decode(candidate, first)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
            continue
        for start in (match.start() for match in re.finditer(r"\{", candidate)):
            try:
                data, _ = decoder.raw_decode(candidate, start)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {"op": "get_profile"}
