#!/usr/bin/env python3
"""Gray-zone probe: does the portion judge false-kill legal FNDDS values?

The 15/15 experiment in portion_judge_probe.py only tested extreme gaps
(5.3x-12.6x). Real generator mistakes sit at 1.2x-2.0x, and both sides of
those pairs are legal FNDDS portion keys (piece vs QNS), not errors.

This script:
  1. Confirms sandwich / lasagna / omelet piece and qns from catalog-v2.sqlite.
  2. Adds catalog-v2 staple first-wins anchors (chicken piece 105 / tuna can 75 /
     beef piece 65).
  3. Judges each legal value plus 5 extreme controls.
  4. Reports whether the judge is a safe absurdity filter at gray-zone scale.
  5. Exits non-zero if any ground-truth assertion fails (the gate).

Run:  .venv/bin/python scripts/gray_zone_probe.py
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nutrienv.bench.grams_gate import (  # noqa: E402
    MAX_TOKENS,
    TEMPERATURE,
    accept_from_verdicts,
    judge_model,
    sample_verdicts,
)
from nutrienv.io.dotenv import load_dotenv_keys  # noqa: E402
from nutrienv.world.catalog_store import load_catalog  # noqa: E402

load_dotenv_keys(ROOT / ".env.local")

CATALOG_V2_PATH = ROOT / "data" / "fdc" / "catalog-v2.sqlite"

# v4-flash spends completion tokens on reasoning first. The 15/15 script's
# max_tokens=120 is enough for extreme cases; gray-zone thinking overflows
# and returns empty content (finish_reason=length). 512 lives in grams_gate.
PARSE_RETRIES = 2
K = 5
THRESHOLD = 0.6

# Claude's measured triples; abort if catalog no longer matches.
EXPECTED_PORTIONS = {
    "2706880": {"piece": 175.0, "qns": 115.0},  # sandwich, 1.5x
    "2708750": {"piece": 206.0, "qns": 250.0},  # lasagna, 1.2x
    "2707198": {"piece": 55.0, "qns": 110.0},   # omelet, 2.0x
}

GRAY_FOODS = (
    ("sandwich", "2706880", "sandwich"),
    ("lasagna", "2708750", "lasagna"),
    ("omelet", "2707198", "omelet"),
)

# Opus condition 2: catalog-v2 staple first-wins anchors (not their QNS).
STAPLE_ANCHORS = (
    ("chicken", "chicken_breast", "chicken breast", "piece", 105.0),
    ("tuna", "tuna", "tuna", "can", 75.0),
    ("beef", "beef", "beef", "piece", 65.0),
)


@dataclass(frozen=True)
class Case:
    case_id: str
    food: str
    grams: float
    group: str          # gray | absurd | normal
    source: str
    expect_accept: bool


@dataclass
class Result:
    case: Case
    verdicts: list[str]
    reasons: list[str]
    ok_frac: float
    accepted: bool

    @property
    def match(self) -> bool:
        return self.accepted == self.case.expect_accept


def _ratio(a: float, b: float) -> str:
    hi, lo = (a, b) if a >= b else (b, a)
    return f"{hi / lo:.2f}x"


def confirm_catalog() -> dict[str, dict]:
    """Load catalog-v2 and require the documented gray triples + staple anchors."""
    catalog = load_catalog(CATALOG_V2_PATH)
    found: dict[str, dict] = {}
    for label, fdc_id, _diary in GRAY_FOODS:
        food = catalog[fdc_id]
        portions = food["portions"]
        piece = float(portions["piece"])
        qns = float(portions["qns"])
        expected = EXPECTED_PORTIONS[fdc_id]
        if piece != expected["piece"] or qns != expected["qns"]:
            raise SystemExit(
                f"catalog drift for {label} ({fdc_id}): "
                f"piece={piece} qns={qns}, expected {expected}"
            )
        found[fdc_id] = {
            "label": label,
            "name": food["name"],
            "piece": piece,
            "qns": qns,
            "ratio": _ratio(piece, qns),
        }
    for label, slug, diary, key, grams in STAPLE_ANCHORS:
        food = catalog[slug]
        got = float(food["portions"][key])
        if got != grams:
            raise SystemExit(
                f"catalog drift for staple {label} ({slug}): "
                f"{key}={got}, expected {grams}"
            )
        found[slug] = {
            "label": label,
            "name": food["name"],
            "key": key,
            "grams": got,
            "diary": diary,
        }
    return found


def build_cases(confirmed: dict[str, dict]) -> list[Case]:
    cases: list[Case] = []
    for label, fdc_id, diary in GRAY_FOODS:
        info = confirmed[fdc_id]
        for key in ("piece", "qns"):
            grams = info[key]
            cases.append(
                Case(
                    case_id=f"{label}-{key}-{grams:g}",
                    food=diary,
                    grams=grams,
                    group="gray",
                    source=f"FNDDS {key} (fdc {fdc_id}, {info['name']})",
                    expect_accept=True,
                )
            )
    for label, slug, diary, key, grams in STAPLE_ANCHORS:
        info = confirmed[slug]
        cases.append(
            Case(
                case_id=f"{label}-{key}-{grams:g}",
                food=str(info["diary"]),
                grams=float(info["grams"]),
                group="gray",
                source=f"FNDDS {key} staple first-wins ({slug}, {info['name']})",
                expect_accept=True,
            )
        )
    cases.extend(
        [
            Case("ctrl-steak-030", "steak (beef)", 30.0, "absurd",
                 "15/15 known-bad (FNDDS slice/piece=30; QNS=160)", False),
            Case("ctrl-banana-010", "banana", 10.0, "absurd",
                 "15/15 known-bad (FNDDS piece/QNS=126)", False),
            Case("ctrl-oil-100", "olive oil", 100.0, "absurd",
                 "15/15 known-bad (~7 tbsp)", False),
            Case("ctrl-steak-160", "steak (beef)", 160.0, "normal",
                 "15/15 known-good (FNDDS QNS=160)", True),
            Case("ctrl-banana-126", "banana", 126.0, "normal",
                 "15/15 known-good (FNDDS piece/QNS=126)", True),
        ]
    )
    return cases


def run_case(case: Case) -> Result:
    raws: list[str] = []
    verdicts = sample_verdicts(
        case.food,
        case.grams,
        judge=None,
        k=K,
        parse_retries=PARSE_RETRIES,
        retry_sleep=0.15,
        raws=raws,
    )
    reasons: list[str] = []
    for verdict, text in zip(verdicts, raws):
        if verdict != "parse_fail":
            match = re.search(r'"reason"\s*:\s*"([^"]*)"', text)
            if match:
                reasons.append(match.group(1))
        time.sleep(0.15)
    n_valid = sum(v != "parse_fail" for v in verdicts)
    ok_frac = (verdicts.count("ok") / n_valid) if n_valid else 0.0
    return Result(
        case=case,
        verdicts=verdicts,
        reasons=reasons,
        ok_frac=ok_frac,
        accepted=accept_from_verdicts(verdicts, THRESHOLD),
    )


def _print_row(result: Result) -> None:
    case = result.case
    expected = "ok" if case.expect_accept else "BAD"
    accepted = "YES" if result.accepted else "no "
    match = "OK" if result.match else "XX"
    print(
        f"{case.case_id:24} {case.grams:7g} g {case.food:16} "
        f"group={case.group:6} expected={expected:3}  "
        f"ok_frac={result.ok_frac:.2f}  accepted={accepted}  match={match}  "
        f"verdicts={result.verdicts}"
    )


def conclude(results: list[Result]) -> bool:
    gray = [r for r in results if r.case.group == "gray"]
    absurd = [r for r in results if r.case.group == "absurd"]
    normal = [r for r in results if r.case.group == "normal"]
    gray_ok = all(r.accepted for r in gray)
    absurd_rej = all(not r.accepted for r in absurd)
    normal_ok = all(r.accepted for r in normal)
    killed = [r for r in gray if not r.accepted]
    leaked = [r for r in absurd if r.accepted]
    missed = [r for r in normal if not r.accepted]

    print("\n--- sample reasons ---")
    for result in results:
        sample = result.reasons[0] if result.reasons else "(none)"
        print(f"{result.case.case_id:24} {sample[:90]}")

    print(
        f"\ngray accepted: {sum(r.accepted for r in gray)}/{len(gray)}"
        f"   absurd rejected: {sum(not r.accepted for r in absurd)}/{len(absurd)}"
        f"   normal accepted: {sum(r.accepted for r in normal)}/{len(normal)}"
    )
    if killed:
        print("false-kills: " + ", ".join(r.case.case_id for r in killed))
    if leaked:
        print("false-accepts: " + ", ".join(r.case.case_id for r in leaked))
    if missed:
        print("normal-misses: " + ", ".join(r.case.case_id for r in missed))

    passed = gray_ok and absurd_rej and normal_ok
    if passed:
        verdict = (
            f"VERDICT: GATE_SAFE — all {len(gray)} legal FNDDS values accepted, "
            "all absurd controls rejected, all normal controls accepted"
        )
    elif killed:
        verdict = (
            "VERDICT: GATE_NEEDS_ADJUSTMENT — legal FNDDS values false-killed: "
            + ", ".join(r.case.case_id for r in killed)
        )
    else:
        verdict = (
            "VERDICT: mixed — gray all accepted="
            f"{gray_ok}, absurd all rejected={absurd_rej}, "
            f"normal all accepted={normal_ok}"
        )
    print(verdict)
    return passed


def main() -> None:
    confirmed = confirm_catalog()
    print(
        f"model={judge_model()}  K={K}  threshold={THRESHOLD}  "
        f"temp={TEMPERATURE}  max_tokens={MAX_TOKENS}  "
        f"prompt=grams_gate.JUDGE_SYSTEM"
    )
    print(f"catalog={CATALOG_V2_PATH}\n")
    print("confirmed piece / qns:")
    for fdc_id, info in confirmed.items():
        if "piece" in info:
            print(
                f"  {info['label']:10} fdc {fdc_id}  "
                f"piece={info['piece']:g}  qns={info['qns']:g}  "
                f"ratio={info['ratio']}  ({info['name']})"
            )
        else:
            print(
                f"  {info['label']:10} {fdc_id}  "
                f"{info['key']}={info['grams']:g}  ({info['name']}, "
                f"staple first-wins)"
            )
    print()

    results = []
    for case in build_cases(confirmed):
        result = run_case(case)
        results.append(result)
        _print_row(result)
    if not conclude(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
