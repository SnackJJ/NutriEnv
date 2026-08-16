"""Whitelist-first plausibility gate for generated gram values.

Table amounts (each food's portion rows × {0.5, 1, 1.5, 2}, plus the
fixed 2 oz = 56.7 g) are accepted without an LLM. Only off-table amounts
go to the judge. Shared judge call/parse lives here so gray_zone_probe
and the gate do not each own a copy.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from nutrienv.harness.react import DEEPSEEK_CHAT_URL, load_dotenv_keys
from nutrienv.world.portions import OUNCE_GRAMS

__all__ = [
    "plausibility_gate",
    "JUDGE_SYSTEM",
    "parse_verdict",
    "call_judge",
    "judge_once",
    "MODEL",
    "TEMPERATURE",
    "MAX_TOKENS",
    "DEFAULT_K",
    "DEFAULT_THRESHOLD",
]

_ROOT = Path(__file__).resolve().parents[3]

MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.7
MAX_TOKENS = 512
DEFAULT_K = 5
DEFAULT_THRESHOLD = 0.6

#: Same prompt as scripts/portion_judge_probe.py. Duplicated here because
#: that script is not a library and is outside this change's file list.
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


def _matches_portion_table(food_id: str, grams: float, catalog) -> bool:
    """Same candidate set as ``validator._matches_portion_table``.

    Source: ``src/nutrienv/bench/validator.py``. Copied so this module does
    not import the draft factory.
    """
    entry = catalog.get(food_id)
    if not isinstance(entry, dict):
        return False
    portions = entry.get("portions") or {}
    candidates = {round(2.0 * OUNCE_GRAMS, 2)}
    for one in portions.values():
        if isinstance(one, (int, float)) and not isinstance(one, bool):
            for quantity in (0.5, 1.0, 1.5, 2.0):
                candidates.add(round(quantity * float(one), 2))
    return round(float(grams), 2) in candidates


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


def call_judge(food: str, grams: float) -> str:
    """One DeepSeek chat completion. Network noise is retried three times."""
    load_dotenv_keys(_ROOT / ".env.local")
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f'Diary entry: "I ate {grams:g} g of {food}."'},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    req = urllib.request.Request(
        DEEPSEEK_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
        },
        method="POST",
    )
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - retry network noise
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed: {last}")


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
    if _matches_portion_table(food_id, grams, catalog):
        return True, "table"

    if judge is None:
        label = _food_label(food_id, catalog)
        sample: JudgeFn | None = None
    else:
        label = food_id
        sample = judge

    verdicts: list[str] = []
    for _ in range(k):
        verdict, _raw = judge_once(label, grams, judge=sample, parse_retries=1)
        verdicts.append("parse_fail" if verdict is None else verdict)

    n_valid = sum(item != "parse_fail" for item in verdicts)
    ok_frac = (verdicts.count("ok") / n_valid) if n_valid else 0.0
    return (n_valid > 0 and ok_frac >= threshold), "judge"
