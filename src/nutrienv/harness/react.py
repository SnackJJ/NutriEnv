"""Minimal ReAct loop: model text in, one Env action out. No scoring here."""

from __future__ import annotations

import json
import os
import re

from nutrienv.actions.schemas import OPS
from nutrienv.io.chat import (
    REACT_RETRY_ON,
    lookup_chat_model,
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
- search_foods {q}   (BM25 over local USDA catalog; do not use q="*")
- get_food {food_id}
- get_profile
- get_ledger
- get_dri
- log_meal {food_id, grams, eaten_at?}
- submit_plan {items: [{food_id, grams}, ...], verdict?, reasons?}
- update_profile {patch}
- update_plan {patch}
- finish  (hand-in: stop the episode; the current world is scored)

How an episode is graded:
- Writes apply immediately; the end state is scored on finish or step limit.
- Multi-step queries need every step's write: ate then "what to eat next" is log_meal (past eaten meal) then submit_plan (future meal plan; never log_meal future recommendations); allergy change then dinner ask is update_profile then submit_plan; ate then "is this okay?" is log_meal then verdict=accept.
- Fields unmentioned by the user stay as the opening profile/ledger.
- food_id comes from search/get_food (slugs like milk_whole also resolve); unknown ids change nothing.
- Nutrient numbers come from observations, not prior knowledge. Catalog energy is per 100 g.
- log_meal without eaten_at is stamped "now". If query names a meal, copy ledger style (today-breakfast, today-lunch, …).
- Leftover questions: daily windows on get_profile are not meal budget. Subtract ledger nutrients and submit_plan for remainder.
- After writes, emit finish. submit_plan is a hand-in: do not update_plan afterwards.
- Profile allergies are catalog allergen_tags (shellfish, peanut), not food names.
- Evaluate: submit_plan with verdict=accept and exact named meal, or verdict=reject, empty items, and reason codes that fire (allergy alone suffices for allergen meals; else {kcal,protein_g,carb_g,fat_g,fiber_g,sodium_mg}_hi/_lo). If the query also asks what to eat instead: a single submit_plan with verdict=reject, those reason codes, and items for the replacement. A second submit_plan without verdict drops the reject. Doing nothing fails.
- Recommend: submit_plan a safe meal that fits windows; omit verdict.
- Single meal planning targets meal energy share: breakfast 25-30%, lunch 30-40%, dinner 30-40% of daily energy. Snack has none.
- Spoken cutting, a tiring deficit, or building muscle with no number: patch phase, or move daily energy below maintain, up toward maintain, or protein above 0.8 g/kg. There is no published step size. Unmentioned allergies and other window keys stay.
- Body facts ("I weigh 70 kg now"): update_profile it; windows re-derive automatically. "Stop the cut" means phase maintain.
"""

_SYSTEM_V1_TAIL = """
- Spoken household measures and dining quantities must be grounded against get_food observations: the portions dictionary maps measure keys to grams for one unit of that food. Convert the spoken quantity from that table ("one-and-a-half" is 1.5, same as "one and a half"). Calculate grams = portion_unit_grams * multiplier. Do not invent grams from prior knowledge without table grounding.
- Keys you may encounter: cup, tbsp (tablespoon), tsp (teaspoon), slice, piece (also "each"), can, fl_oz (fluid ounce), serving.
- Common dining servings and packaged containers ("a pack", "a packet", "a package", "a pouch", "a bag", "a serving", "a portion", "a bowl", "a plate", "an order", or a dish named as its own unit like "a sandwich", "two burritos") represent standard single servings: read portions.qns (or piece, slice, cup fallback).
- Food-specific count units, when the food's portions table carries that key: wing ("two chicken wings" reads portions.wing), drummette, scoop, patty, pat ("a pat of butter"), packet, pouch, bar, stick. Each is grams for one unit multiplied by the spoken count.
- A bare food noun with no unit ("one apple", "a banana", "two eggs") means that many pieces (portions.piece). A cut noun ("a chicken breast", "two drumsticks") means that many pieces only when the food's own name contains that cut and portions.piece exists; otherwise do not log it, finish without logging that food.
- "thick", "thin" and "regular" pick a different default serving of the same food: read portions.thick / portions.thin / portions.regular.
- An ounce is always 28.35 g, whatever the table says. Grams ("150 g") are already grams.
- Other portion keys you may see (oz_yield, cubic_inch) are reference data, not measures a user speaks. Do not convert with them.
- Recommend "eat along with X for dinner": X is spoken context, not part of your plan -- submit_plan your own safe meal that fits the windows.
- "I am now allergic to Y, so no more Z": update_profile adds the catalog allergen tag for Y; never log_meal or submit_plan Z afterwards.
"""

_SYSTEM_V2 = """You are an agent in NutriEnv, a steppable nutrition world.
Each turn emit exactly one JSON object, no markdown, no extra top-level keys:
{"op": "<one of the ops>", ...args}

Available ops:
- search_foods {q}   (BM25 over local USDA catalog; do not use q="*")
- get_food {food_id}
- get_profile
- get_ledger
- get_dri
- log_meal {food_id, grams, eaten_at?}
- amend_meal {index, grams, food_id?, eaten_at?}   (overwrite ledger[index]; index is 0-based into the current ledger; grams > 0; omitted fields keep the existing row's value)
- submit_plan {items: [{food_id, grams}, ...], verdict?, reasons?}
- update_profile {patch}
- update_plan {patch}
- finish  (hand-in: stop the episode; the current world is scored)

How an episode is graded:
- Writes apply immediately; the end state is scored on finish or step limit.
- Multi-step queries need every step's write: allergy change then dinner ask is update_profile then submit_plan; never log_meal future recommendations.
- Fields unmentioned by the user stay as the opening profile/ledger.
- food_id comes from search/get_food (slugs like milk_whole also resolve); unknown ids change nothing.
- Nutrient numbers come from observations, not prior knowledge. Catalog energy is per 100 g.
- log_meal without eaten_at is stamped "now". If query names a meal, copy ledger style (today-breakfast, today-lunch, …).
- Leftover questions: daily windows on get_profile are not meal budget. Subtract ledger nutrients and submit_plan for remainder.
- After writes, emit finish. submit_plan is a hand-in: do not update_plan afterwards.
- Profile allergies are catalog allergen_tags (shellfish, peanut), not food names.
- Evaluate: submit_plan with verdict=accept and exact named meal, or verdict=reject, empty items, and reason codes that fire (allergy alone suffices for allergen meals; else {kcal,protein_g,carb_g,fat_g,fiber_g,sodium_mg}_hi/_lo). If the query also asks what to eat instead: a single submit_plan with verdict=reject, those reason codes, and items for the replacement. A second submit_plan without verdict drops the reject. Doing nothing fails.
- Recommend: submit_plan a safe meal that fits windows; omit verdict.
- Single meal planning targets meal energy share: breakfast 25-30%, lunch 30-40%, dinner 30-40% of daily energy. Snack has none.
- Spoken cutting, a tiring deficit, or building muscle with no number: patch phase, or move daily energy below maintain, up toward maintain, or protein above 0.8 g/kg. There is no published step size. Unmentioned allergies and other window keys stay.
- Body facts ("I weigh 70 kg now"): update_profile it; windows re-derive automatically. "Stop the cut" means phase maintain.
"""

REACT_VERSIONS = ("v0", "v1", "v2")
_MANUALS = {
    "v0": _SYSTEM,
    "v1": _SYSTEM + _SYSTEM_V1_TAIL,
    "v2": _SYSTEM_V2,
}


def react_manual(version: str) -> str:
    """Return the frozen ReAct system manual for a harness version."""
    if version not in _MANUALS:
        raise ValueError(f"unknown react harness version: {version!r}")
    return _MANUALS[version]


def context_messages(
    messages: list[dict], *, limit: int | None = _CONTEXT_LIMIT
) -> list[dict]:
    """Keep the system manual and the Task line when the window slides.

    A raw ``messages[-N:]`` drop drops both after a few steps, so the model
    forgets the ops and the query. Pin those two; slide only the trajectory.
    ``limit=None`` sends the full log (published ReAct; the 12-message slide
    is an ablation).
    """
    if limit is None:
        return list(messages)
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
        context_limit: int | None = None,
    ) -> None:
        if version not in REACT_VERSIONS:
            raise ValueError(f"unknown react harness version: {version!r}")
        if context_limit is not None and (
            isinstance(context_limit, bool) or context_limit < 1
        ):
            raise ValueError("context_limit must be None or an int >= 1")
        spec = lookup_chat_model(model)
        self.base_url = base_url or spec.url
        self.api_key = api_key or os.environ.get(spec.api_key_env)
        if not self.api_key:
            raise RuntimeError(f"{spec.api_key_env} is not set")
        self.model = model
        self.timeout = timeout
        self.leak_oracle = leak_oracle
        self.max_steps = max_steps
        self.extra_body = dict(extra_body or {})
        self.version = version
        self.context_limit = context_limit
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
            context_limit=self.context_limit,
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
            "messages": context_messages(self.messages, limit=self.context_limit),
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
                if data.get("op") == "submit_plan" and (data.get("verdict") == "accept" or "verdict" not in data):
                    data.pop("reasons", None)
                return data
            continue
        for start in (match.start() for match in re.finditer(r"\{", candidate)):
            try:
                data, _ = decoder.raw_decode(candidate, start)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                if data.get("op") == "submit_plan" and (data.get("verdict") == "accept" or "verdict" not in data):
                    data.pop("reasons", None)
                return data
    return {"op": "get_profile"}
