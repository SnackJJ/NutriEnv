#!/usr/bin/env python3
"""Probe: can an LLM judge whether a stated portion (grams) is plausible?

Measures discrimination between known-good and known-bad amounts, using FNDDS
Quantity-Not-Specified (QNS) values as the anchor for the good set. Each case
is judged K times; the fraction of "ok" verdicts decides acceptance.

Run:  .venv/bin/python scripts/portion_judge_probe.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nutrienv.harness.react import DEEPSEEK_CHAT_URL, load_dotenv_keys  # noqa: E402

load_dotenv_keys(ROOT / ".env.local")

MODEL = "deepseek-v4-flash"
K = 5                 # judge calls per case
TEMPERATURE = 0.7
THRESHOLD = 0.6       # fraction of "ok" needed to accept a gram value

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

# (case_id, food, grams, expected_ok, note)  — expected from FNDDS QNS + sanity.
CASES = [
    ("steak-030",  "steak (beef)", 30.0,  False, "FNDDS: 1 slice=30g, QNS=160, thick=240"),
    ("steak-120",  "steak (beef)", 120.0, True,  "FNDDS: 1 thin=120g"),
    ("steak-160",  "steak (beef)", 160.0, True,  "FNDDS: QNS=160g"),
    ("steak-240",  "steak (beef)", 240.0, True,  "FNDDS: 1 thick=240g"),
    ("steak-500",  "steak (beef)", 500.0, False, "~2 thick steaks in one sitting"),
    ("egg-055",    "fried egg",    55.0,  True,  "FNDDS: piece/QNS=55g"),
    ("egg-005",    "fried egg",    5.0,   False, "a tenth of an egg"),
    ("banana-126", "banana",       126.0, True,  "FNDDS: QNS=126g"),
    ("banana-010", "banana",       10.0,  False, "a sliver of banana"),
    ("milk-122",   "whole milk",   122.0, True,  "half a cup"),
    ("milk-1500",  "whole milk",   1500.0, False, "~6 cups of milk in one sitting"),
    ("oil-014",    "olive oil",    14.0,  True,  "one tablespoon"),
    ("oil-100",    "olive oil",    100.0, False, "~7 tablespoons of oil"),
    ("rice-300",   "cooked white rice", 300.0, True, "~2 cups of rice"),
    ("rice-2000",  "cooked white rice", 2000.0, False, "~12 cups of rice"),
]


def call_judge(food: str, grams: float) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f'Diary entry: "I ate {grams:g} g of {food}."'},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": 120,
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


def parse_verdict(text: str) -> str | None:
    m = re.search(r'"verdict"\s*:\s*"(ok|suspect)"', text, re.I)
    return m.group(1).lower() if m else None


def main() -> None:
    print(f"model={MODEL}  K={K}  threshold={THRESHOLD}\n")
    rows = []
    for case_id, food, grams, expected, note in CASES:
        verdicts: list[str] = []
        reasons: list[str] = []
        for _ in range(K):
            text = call_judge(food, grams)
            v = parse_verdict(text)
            if v is None:
                verdicts.append("parse_fail")
            else:
                verdicts.append(v)
                m = re.search(r'"reason"\s*:\s*"([^"]*)"', text)
                if m:
                    reasons.append(m.group(1))
            time.sleep(0.15)
        ok_frac = verdicts.count("ok") / len(verdicts)
        accepted = ok_frac >= THRESHOLD
        match = (accepted == expected)
        rows.append((case_id, food, grams, expected, ok_frac, accepted, match,
                     verdicts, reasons))
        print(
            f"{case_id:14} {grams:7g} g {food:22} expected={'ok' if expected else 'BAD'}"
            f"  ok_frac={ok_frac:.2f}  accepted={'YES' if accepted else 'no '}"
            f"  match={'OK' if match else 'XX'}"
        )

    print("\n--- sample reasons ---")
    for case_id, food, grams, expected, ok_frac, accepted, match, verdicts, reasons in rows:
        sample = reasons[0] if reasons else "(none)"
        print(f"{case_id:14} {sample[:90]}")

    good = [r for r in rows if r[3]]
    bad = [r for r in rows if not r[3]]
    g_pass = sum(1 for r in good if r[5])
    b_rej = sum(1 for r in bad if not r[5])
    print(f"\nknown-good accepted: {g_pass}/{len(good)}"
          f"   known-bad rejected: {b_rej}/{len(bad)}"
          f"   total match: {sum(1 for r in rows if r[6])}/{len(rows)}")
    # The decisive pair from the user's design:
    steak30 = next(r for r in rows if r[0] == "steak-030")
    steak160 = next(r for r in rows if r[0] == "steak-160")
    if steak30[5] and steak160[5]:
        print("VERDICT: path FAILS — 30g steak was accepted (no discrimination)")
    elif not steak30[5] and steak160[5]:
        print("VERDICT: path VIABLE — 30g rejected, 160g accepted")
    else:
        print(f"VERDICT: mixed — 30g accepted={steak30[5]}, 160g accepted={steak160[5]}")


if __name__ == "__main__":
    main()
