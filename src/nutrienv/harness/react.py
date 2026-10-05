"""Minimal ReAct loop: model text in, one Env action out. No scoring here."""

from __future__ import annotations

import json
import os
import re

from nutrienv.actions.schemas import OPS
from nutrienv.io.chat import (
    REACT_RETRY_ON,
    _message_text,
    lookup_chat_model,
    post_chat_completion_raw,
)
from nutrienv.io.dotenv import load_dotenv_keys

from .protocol import Harness
from .runner import DEFAULT_MAX_STEPS, FINISH_OPS

__all__ = [
    "ABLATION_CONTEXT_LIMIT",
    "REACT_VERSIONS",
    "ReActHarness",
    "ReActInfraError",
    "context_messages",
    "load_dotenv_keys",
    "oracle_hint",
    "react_manual",
]

_OPS = frozenset(OPS) | FINISH_OPS

# The 12-message slide is an ablation control, never a default: a caller that forgets to pass
# `limit` used to get a truncated trajectory silently, which is indistinguishable in the result
# from a model that never had the context.
ABLATION_CONTEXT_LIMIT = 12


class ReActInfraError(RuntimeError):
    """A completion that failed after its request retries: infrastructure, not the model.

    The ablation driver retries the whole episode on this, and only on this, the way the exam
    loop retries on `EpisodeInfraError`; any other exception is a bug and must surface.
    """


def _usage(body: dict, messages: list, text: str) -> dict:
    """One completion's token counts, with the exam loop's 4-chars/token fallback."""
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details")
    details = details if isinstance(details, dict) else {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or len(json.dumps(messages)) // 4),
        "completion_tokens": int(usage.get("completion_tokens") or len(text) // 4),
        "reasoning_tokens": int(
            details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0
        ),
        "tokens_measured": bool(usage),
    }


def _checked_max_steps(max_steps: int) -> int:
    """Validate once: the prompt renders this number, so a bad one must not reach an episode."""
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("max_steps must be an int >= 1")
    return max_steps


_SYSTEM_V1_TAIL = """
- Spoken household measures and dining quantities must be grounded against get_food observations: the portions dictionary maps measure keys to grams for one unit of that food. Convert the spoken quantity from that table ("one-and-a-half" is 1.5, same as "one and a half"). Calculate grams = portion_unit_grams * multiplier. Do not invent grams from prior knowledge without table grounding.
- Keys you may encounter: cup, tbsp (tablespoon), tsp (teaspoon), slice, piece (also "each"), can, fl_oz (fluid ounce), serving.
- Dining servings ("a serving", "a portion", "a bowl", "a plate", "a glass", "an order", "a sandwich") use portions.qns. Explicit packet/pouch/bar and other count units use their own keys. Missing keys require clarification, not another unit.
- Food-specific count units, when the food's portions table carries that key: wing ("two chicken wings" reads portions.wing), drummette, scoop, patty, pat ("a pat of butter"), packet, pouch, bar, stick. Each is grams for one unit multiplied by the spoken count.
- A bare food noun with no explicit unit ("one apple", "a banana", "two eggs") uses portions.qns times its count, not portions.piece. Only explicit piece/slice uses those keys.
- "thick", "thin" and "regular" pick a different default serving of the same food: read portions.thick / portions.thin / portions.regular.
- An ounce is always 28.35 g, whatever the table says. Grams ("150 g") are already grams.
- Other portion keys you may see (oz_yield, cubic_inch) are reference data, not measures a user speaks. Do not convert with them.
- Recommend "eat along with X for dinner": X is spoken context, not part of your plan -- submit_plan your own safe meal that fits the windows.
- "I am now allergic to Y, so no more Z": update_profile adds the catalog allergen tag for Y; never log_meal or submit_plan Z afterwards.
"""

_SYSTEM_V2 = """You are an agent in NutriEnv, a steppable nutrition world.
Each turn emit exactly one JSON object, no markdown, no extra top-level keys:
{"op": "<one of the ops>", ...args}

Ops, with their arguments:
- search_foods {q}                  BM25 search over the local USDA catalog; returns food_id and name
- get_food {food_id}                portions, nutrients and allergen tags for one food
- get_profile                       allergies, daily target nutrient windows and published plan mass limits
- get_ledger                        meals logged so far today, with cumulative nutrients
- get_dri                           FDA daily reference values
- log_meal {food_id, grams, eaten_at?}   record a consumed item; eaten_at e.g. today-lunch
- amend_meal {index, grams, food_id?, eaten_at?}   index is 0-based into the current ledger
- submit_plan {items: [{food_id, grams}], verdict?, reasons?}   hand in a plan; verdict and reasons belong to evaluation tasks, and a reject carries no items
- update_profile {patch}            patch is a dict of profile fields, e.g. {"allergies": ["peanut"], "activity": "light"}
- update_plan {patch}
- finish                            hand in the episode
"""
REACT_VERSIONS = ("v0", "v1", "v2")


def react_manual(version: str) -> str:
    """Return the frozen ReAct system manual for a harness version."""
    from nutrienv.harness.prompt_freeze import SHARED_TASK_SPEC

    if version not in REACT_VERSIONS:
        raise ValueError(f"unknown react harness version: {version!r}")
    # v0 is an explicit compatibility alias of current v2, not a historical baseline.
    return _SYSTEM_V2 + SHARED_TASK_SPEC + (_SYSTEM_V1_TAIL if version == "v1" else "")


def context_messages(
    messages: list[dict], *, limit: int | None = None
) -> list[dict]:
    """Keep the system manual and the Task line when the window slides.

    A raw ``messages[-N:]`` drop drops both after a few steps, so the model
    forgets the ops and the query. Pin those two; slide only the trajectory.
    ``limit=None`` -- the default -- sends the full log, which is what the published ReAct
    runs do. The 12-message slide is an ablation control and has to be asked for explicitly
    (``ABLATION_CONTEXT_LIMIT``).
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
    if (
        rest
        and rest[0].get("role") == "user"
        and str(rest[0].get("content", "")).startswith("Pinned constraints:")
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
        temperature: float = 0.0,
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
        self.api_model = spec.model_id
        self.timeout = timeout
        self.leak_oracle = leak_oracle
        self.max_steps = _checked_max_steps(max_steps)
        self.temperature = temperature
        self.extra_body = dict(extra_body or {})
        self.version = version
        self.context_limit = context_limit
        self.messages: list[dict] = [{"role": "system", "content": react_manual(version)}]
        # One entry per completion (act and revise alike), for the ablation's token accounting.
        self.usage_log: list[dict] = []

    @property
    def label(self) -> str:
        return f"react-{self.version}"

    def clone(self) -> ReActHarness:
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
            temperature=self.temperature,
        )

    def set_step_budget(self, max_steps: int) -> None:
        """Store the loop bound the Runner will use, so the prompt cannot promise another one."""
        self.max_steps = _checked_max_steps(max_steps)

    def reset(self, task: object | None = None) -> None:
        """Drop episode history so the next Task cannot see the last one."""
        system = react_manual(self.version)
        oracle = getattr(task, "oracle", None) if task is not None else None
        if self.leak_oracle and oracle is not None:
            system = system + "\n\n" + oracle_hint(oracle)
        self.messages = [{"role": "system", "content": system}]
        self.usage_log = []

    def ensure_task(self, query: str) -> None:
        """Pin the Task line before the first observation. Idempotent."""
        if len(self.messages) == 1:
            self.messages.append({"role": "user", "content": f"Task:\n{query}"})

    def act(self, observation: dict, query: str, history: list) -> dict:
        self.ensure_task(query)
        remaining = max(0, self.max_steps - len(history))
        self.messages.append(
            {
                "role": "user",
                "content": (
                    f"Step budget: {remaining} action(s) remaining.\n"
                    "Observation:\n"
                    + json.dumps(observation, default=str)[:6000]
                ),
            }
        )
        return self._emit()

    def revise(self, feedback: str) -> dict:
        """Re-complete after a harness-side check bounce. Env never saw the rejected action."""
        self.messages.append({"role": "user", "content": feedback})
        return self._emit()

    def _emit(self) -> dict:
        text = self._complete()
        self.messages.append({"role": "assistant", "content": text})
        # An object with an unknown op goes to Env as-is and is refused there, as in the exam
        # loop; only a turn with no JSON object falls back to get_profile.
        return _parse_action(text)

    def _complete(self) -> str:
        payload = {
            "model": self.api_model,
            "messages": context_messages(self.messages, limit=self.context_limit),
            "temperature": self.temperature,
            **self.extra_body,
        }
        try:
            # Raw body and 5 request retries, as the exam loop's spec: the usage block is the
            # cost axis, and `_message_text` keeps the reasoning_content fallback.
            body = post_chat_completion_raw(
                self.base_url,
                payload,
                self.api_key,
                timeout=self.timeout,
                retries=5,
                retry_on=REACT_RETRY_ON,
                error_prefix=f"{self.model} request failed",
            )
        except Exception as exc:
            raise ReActInfraError(str(exc)) from exc
        if not isinstance(body, dict):
            body = {}
        text = _message_text(body)
        self.usage_log.append(_usage(body, payload["messages"], text))
        return text


def _choose_action(text: str) -> dict | None:
    """Return the JSON object the text carries, or None. Tolerates CoT prose and code fences."""
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    candidates = [fenced.group(1), stripped] if fenced else [stripped]
    decoder = json.JSONDecoder()
    valid_actions: list[dict] = []
    other_dicts: list[dict] = []

    for candidate in candidates:
        first = len(candidate) - len(candidate.lstrip())
        if first < len(candidate) and candidate[first] == "{":
            try:
                data, _ = decoder.raw_decode(candidate, first)
                if isinstance(data, dict):
                    if data.get("op") in _OPS:
                        valid_actions.append(data)
                    else:
                        other_dicts.append(data)
            except json.JSONDecodeError:
                pass
        elif first < len(candidate) and candidate[first] == "[":
            # A top-level JSON array is not a valid action dict
            pass
        else:
            for start in (match.start() for match in re.finditer(r"\{", candidate)):
                try:
                    data, _ = decoder.raw_decode(candidate, start)
                    if isinstance(data, dict):
                        if data.get("op") in _OPS:
                            valid_actions.append(data)
                        else:
                            other_dicts.append(data)
                except json.JSONDecodeError:
                    pass

    # Take the first valid action to prevent accepting hallucinated multi-turn rollouts
    return valid_actions[0] if valid_actions else (other_dicts[0] if other_dicts else None)


def _sanitize_submit_plan(chosen: dict) -> dict:
    """Keep only keys the Action carries, and coerce item grams to float."""
    if chosen.get("op") == "submit_plan":
        if chosen.get("verdict") == "accept" or "verdict" not in chosen:
            chosen.pop("reasons", None)
        valid_keys = {"op", "items", "verdict", "reasons"}
        chosen = {k: v for k, v in chosen.items() if k in valid_keys}
        if isinstance(chosen.get("items"), list):
            # A model-written item is a boundary, and this function must not raise on one: it
            # runs inside the episode loop, where a `ValueError` from coercing `grams` would end
            # the whole run rather than the turn. An unusable item is dropped, which leaves the
            # plan the Scorer judges and the action in the transcript -- both visible -- instead
            # of an infrastructure failure that hides what the model wrote.
            items: list[dict] = []
            for item in chosen["items"]:
                if not isinstance(item, dict) or "food_id" not in item:
                    continue
                grams = item.get("grams", 0.0)
                if isinstance(grams, bool) or not isinstance(grams, (int, float)):
                    continue
                items.append({"food_id": str(item["food_id"]), "grams": grams})
            chosen["items"] = items
    return chosen


# What a loop may do when a model turn is not a legal Action. These names are the vocabulary of
# the measurement, not of the model: a run records which one it used, and two runs that used
# different ones are not comparable on their pass rates.
PARSE_ERROR_POLICIES = ("silent", "feedback", "resample")

# `feedback`: tell the model its turn was not an Action, that nothing was executed, and what form
# is expected. Nothing else is interpolated -- no numbers, no hints about the answer. The point
# is that a failed attempt becomes information the model can act on, instead of a silent
# substitution that it cannot distinguish from success.
# `%`-interpolated, not `str.format`: the message quotes the JSON form, and braces in a format
# template are field syntax.
PARSE_ERROR_FEEDBACK = (
    "Your previous message was not a legal action and nothing was executed; the world is "
    'unchanged. Reply with exactly one JSON object of the form {"op": "<op>", ...args} and no '
    "other text. Your message began: %(echo)r"
)

# `resample`: the control for `feedback`. It spends the same extra completion and diagnoses
# nothing, so "telling the model what went wrong" is separable from "spending another call".
PARSE_ERROR_RESAMPLE = "Continue. Reply with one JSON action."


def violation_feedback(policy: str, text: str) -> str:
    """The user turn a violated attempt earns under ``policy``.

    `silent` never asks (it executes the fallback instead), so it is not accepted here: a caller
    that wants no message should not be calling this at all.
    """
    if policy == "feedback":
        return PARSE_ERROR_FEEDBACK % {"echo": text[:200]}
    if policy == "resample":
        return PARSE_ERROR_RESAMPLE
    raise ValueError(f"no feedback for policy {policy!r}")


def resolve_action(text: str) -> tuple[dict | None, str | None]:
    """Return ``(action, None)`` for the Action in ``text``, else ``(None, why)``.

    ``why`` is ``"no_action"`` when no JSON object was found at all, or ``"unknown_op"`` when the
    object's ``op`` is not in the catalogue. A loop that wants to *count* protocol violations has
    to call this rather than ``_parse_action``: the latter hides both behind a ``get_profile``
    fallback, which in a transcript is indistinguishable from a model that asked to re-read the
    profile.
    """
    chosen = _choose_action(text)
    if chosen is None:
        return None, "no_action"
    if chosen.get("op") not in _OPS:
        return chosen, "unknown_op"
    return _sanitize_submit_plan(chosen), None


def _parse_action(text: str) -> dict:
    """Return the intended JSON Action object, tolerating CoT prose or code fences.

    Anything unparseable becomes ``{"op": "get_profile"}``. That substitution is what the text
    harness has always done and published reports depend on it, so it stays here; call
    :func:`resolve_action` to see the violation itself.
    """
    action, _ = resolve_action(text)
    if action is None:
        return {"op": "get_profile"}
    return action
