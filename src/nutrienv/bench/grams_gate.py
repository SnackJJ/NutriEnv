"""Whitelist-first plausibility gate for generated gram values.

Table amounts (each food's portion rows × {0.5, 1, 1.5, 2}, plus the
fixed 2 oz = 56.7 g) are accepted without an LLM. Only off-table amounts
go to the judge. Shared judge call/parse lives here so gray_zone_probe
and the gate do not each own a copy.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from nutrienv.io.chat import (
    DASHSCOPE_CHAT_URL,
    DEEPSEEK_CHAT_URL,
    JUDGE_RETRY_ON,
    post_chat_completion,
)
from nutrienv.io.dotenv import load_dotenv_keys

from .portion_table import matches_portion_table

__all__ = [
    "plausibility_gate",
    "JUDGE_SYSTEM",
    "parse_verdict",
    "call_judge",
    "judge_once",
    "sample_verdicts",
    "accept_from_verdicts",
    "judge_model",
    "MODEL",
    "TEMPERATURE",
    "MAX_TOKENS",
    "DEFAULT_K",
    "DEFAULT_THRESHOLD",
]

_ROOT = Path(__file__).resolve().parents[3]

MODEL = "deepseek-v4-flash-0731"
TEMPERATURE = 0.7
MAX_TOKENS = 512
DEFAULT_K = 5
DEFAULT_THRESHOLD = 0.6

# Official api.deepseek.com ids. Dated snapshot ids (…-0731) and Qwen live
# on DashScope; posting 0731 to DeepSeek returns invalid_request_error.
_DEEPSEEK_NATIVE_MODELS = frozenset(
    {"deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"}
)

#: Judge prompt shared with scripts/portion_judge_probe.py and
#: scripts/gray_zone_probe.py; both import it from here.
JUDGE_SYSTEM = """You are a nutritionist auditing a food diary for plausible
portion amounts. A user wrote the diary entry below. Judge whether the stated
amount in grams is a plausible portion of that food that a real person would
actually eat in one sitting or one meal. Use your knowledge of typical food
portions.

- "ok" = the amount is within a normal, believable range for that food.
- "suspect" = the amount looks implausibly small or implausibly large — more
  like a data-entry error, a unit mix-up (e.g. ounces written as grams), or a
  fraction of the food than a real portion.

Answer with a single JSON object and nothing else:
{"verdict": "ok" or "suspect", "reason": "<one short sentence>"}"""

JudgeFn = Callable[[str, float], str]


def parse_verdict(text: str) -> str | None:
    """Return ``ok`` / ``suspect`` from a judge reply, or ``None`` if empty."""
    if not text or not str(text).strip():
        return None
    match = re.search(r'"verdict"\s*:\s*"(ok|suspect)"', text, re.I)
    if match:
        return match.group(1).lower()
    stripped = str(text).strip().lower()
    if stripped in {"ok", "suspect"}:
        return stripped
    return None


def judge_model() -> str:
    """Active judge model. ``NUTRIENV_JUDGE_MODEL`` overrides the default."""
    override = os.environ.get("NUTRIENV_JUDGE_MODEL", "").strip()
    return override or MODEL


def call_judge(food: str, grams: float) -> str:
    """One chat completion. Network noise is retried three times."""
    load_dotenv_keys(_ROOT / ".env.local")
    model = judge_model()
    if model in _DEEPSEEK_NATIVE_MODELS:
        url, api_key = DEEPSEEK_CHAT_URL, os.environ["DEEPSEEK_API_KEY"]
    else:
        url, api_key = DASHSCOPE_CHAT_URL, os.environ["DASHSCOPE_API_KEY"]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f'Diary entry: "I ate {grams:g} g of {food}."'},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    return post_chat_completion(
        url,
        payload,
        api_key,
        timeout=60.0,
        retries=3,
        retry_on=JUDGE_RETRY_ON,
        error_prefix="request failed",
    )


def judge_once(
    food: str,
    grams: float,
    *,
    judge: JudgeFn | None = None,
    parse_retries: int = 1,
    retry_sleep: float = 0.0,
) -> tuple[str | None, str]:
    """Call ``judge`` (or the default API) until a verdict parses.

    Empty / unparseable replies retry ``parse_retries`` times. Returns
    ``(verdict or None, last raw text)``.
    """
    call = judge if judge is not None else call_judge
    text = ""
    for _attempt in range(1 + parse_retries):
        text = call(food, grams) or ""
        verdict = parse_verdict(text)
        if verdict is not None:
            return verdict, text
        if retry_sleep:
            time.sleep(retry_sleep)
    return None, text


def sample_verdicts(
    food: str,
    grams: float,
    *,
    judge: JudgeFn | None,
    k: int,
    parse_retries: int,
    retry_sleep: float = 0.0,
    raws: list[str] | None = None,
) -> list[str]:
    """Call the judge ``k`` times. Unparseable replies are ``parse_fail``."""
    verdicts: list[str] = []
    for _ in range(k):
        verdict, text = judge_once(
            food, grams, judge=judge, parse_retries=parse_retries, retry_sleep=retry_sleep
        )
        verdicts.append("parse_fail" if verdict is None else verdict)
        if raws is not None:
            raws.append(text)
    return verdicts


def accept_from_verdicts(verdicts: list[str], threshold: float) -> bool:
    """Accept when ok / valid-verdict ratio meets ``threshold``.

    ``parse_fail`` is excluded from the denominator. No valid verdicts
    means reject.
    """
    n_valid = sum(item != "parse_fail" for item in verdicts)
    ok_frac = (verdicts.count("ok") / n_valid) if n_valid else 0.0
    return n_valid > 0 and ok_frac >= threshold


def _food_label(food_id: str, catalog) -> str:
    entry = catalog.get(food_id)
    if isinstance(entry, dict):
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            return name
    return food_id


def plausibility_gate(
    food_id: str,
    grams: float,
    catalog,
    *,
    judge: JudgeFn | None = None,
    k: int = DEFAULT_K,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[bool, str]:
    """Accept a gram amount, or not. Returns ``(accepted, source)``.

    ``source`` is ``"table"`` when ``grams`` matches the portion whitelist,
    otherwise ``"judge"`` after K samples. Inject ``judge`` to stub the LLM.
    """
    if matches_portion_table(food_id, grams, catalog):
        return True, "table"

    if judge is None:
        label = _food_label(food_id, catalog)
        sample: JudgeFn | None = None
    else:
        label = food_id
        sample = judge

    verdicts = sample_verdicts(label, grams, judge=sample, k=k, parse_retries=1)
    return accept_from_verdicts(verdicts, threshold), "judge"
