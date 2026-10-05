#!/usr/bin/env python3
"""Characterise scorer tolerance: does the ±15% band and multiset matching behave as claimed?

The published reports only tell us which end states were accepted. This probe asks the
complementary question — which *perturbations* of an accepted trajectory are still
accepted — so two failure modes become measurable instead of assumed:

* **false negative** — a semantically equivalent end state (reordered ledger, portion
  nudged inside the stated ±15% physical band) that the scorer rejects anyway.
* **false positive** — a perturbation outside the band (portion pushed past ±15%) that
  the scorer still accepts, which would mean the band is not actually enforced.

    .venv/bin/python scripts/scorer_robustness_probe.py --report reports/benchmark_ark_deepseek-v4-flash_v1.0.json
    .venv/bin/python scripts/scorer_robustness_probe.py --report ... --json reports/scorer_robustness.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.bench.realize import scored_oracles  # noqa: E402
from nutrienv.bench.scorer import Scorer  # noqa: E402
from nutrienv.bench.split import load_split  # noqa: E402
from nutrienv.env import NutriEnv  # noqa: E402
from nutrienv.world.catalog import canonical_food_id  # noqa: E402


def replay(task, actions: list[dict]) -> tuple[bool, str]:
    env = NutriEnv()
    env.reset(task.s0)
    for action in actions:
        env.step(action)
    result = Scorer().score(env.state(), task.oracle)
    return bool(result.passed), str(result.tag)


def gold_anchors(task) -> dict[str, float]:
    """Gold grams per food from the oracle's ledger tails: what a logged portion is judged against."""
    anchors: dict[str, float] = {}
    for oracle in scored_oracles(task.oracle):
        for row in oracle.ledger_tail or ():
            anchors[row.food_id] = row.grams
    return anchors


def scale_grams(
    actions: list[dict], factor: float, anchors: dict[str, float], catalog
) -> list[dict] | None:
    """Set the last log_meal of an anchored food to factor x its gold grams.

    ADR 0023's band is relative to the gold anchor, so a perturbation labelled "+14.9%" must
    land at +14.9% of gold; scaling the model's own grams lands elsewhere whenever the model
    was not exactly on gold. Only the last such write is scaled: log_meal appends, and a probed
    task has passed its baseline, so its ledger holds one row per anchored food. None when no
    log_meal names an anchored food, or an amend_meal could overwrite the write.
    """
    if any(a.get("op") == "amend_meal" for a in actions):
        return None
    out = copy.deepcopy(actions)
    for action in reversed(out):
        if action.get("op") != "log_meal" or not isinstance(action.get("food_id"), str):
            continue
        anchor = anchors.get(canonical_food_id(catalog, action["food_id"]))
        if anchor is not None:
            action["grams"] = round(anchor * factor, 3)
            return out
    return None


def reverse_logs(actions: list[dict]) -> list[dict]:
    """Same log writes, opposite order — the ledger is a multiset, not a sequence."""
    out = copy.deepcopy(actions)
    positions = [i for i, a in enumerate(out) if a.get("op") == "log_meal"]
    payloads = [out[i] for i in positions][::-1]
    for slot, payload in zip(positions, payloads):
        out[slot] = payload
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--split", default="data/splits/nutrienv-v1.1.json")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text(encoding="utf-8"))
    tasks = {t.id: t for t in load_split(args.split)}

    rows: list[dict] = []
    for entry in report.get("tasks", []):
        if not entry.get("passed"):
            continue
        actions = [s.get("action") for s in entry.get("steps", []) if s.get("action")]
        if not any(a.get("op") == "log_meal" for a in actions):
            continue  # only tasks with a weighted write exercise the band
        task = tasks.get(entry["task_id"])
        if task is None:
            continue

        base_pass, base_tag = replay(task, actions)
        if not base_pass:
            rows.append({"task_id": task.id, "family": task.family, "status": "baseline_no_longer_passes"})
            continue

        anchors = gold_anchors(task)
        if scale_grams(actions, 1.0, anchors, task.s0.catalog) is None:
            rows.append({"task_id": task.id, "family": task.family, "status": "unprobed"})
            continue

        row = {"task_id": task.id, "family": task.family, "baseline": base_tag}
        for label, mutated in (
            ("in_band_+14.9%", scale_grams(actions, 1.149, anchors, task.s0.catalog)),
            ("in_band_-14.9%", scale_grams(actions, 0.851, anchors, task.s0.catalog)),
            ("out_band_+16%", scale_grams(actions, 1.16, anchors, task.s0.catalog)),
            ("out_band_-16%", scale_grams(actions, 0.84, anchors, task.s0.catalog)),
            ("reversed_logs", reverse_logs(actions)),
        ):
            try:
                passed, tag = replay(task, mutated)
                row[label] = {"passed": passed, "tag": tag}
            except Exception as exc:
                row[label] = {"error": f"{type(exc).__name__}: {exc}"[:120]}
        rows.append(row)

    def tally(label: str, want: bool) -> dict:
        seen = [r[label] for r in rows if isinstance(r.get(label), dict) and "passed" in r[label]]
        agree = [r for r in seen if r["passed"] is want]
        return {"n": len(seen), "as_expected": len(agree)}

    summary = {
        "report": args.report.name,
        "tasks_probed": sum(1 for r in rows if "status" not in r),
        "unprobed": [r["task_id"] for r in rows if r.get("status") == "unprobed"],
        "baseline_regressions": [r["task_id"] for r in rows if r.get("status") == "baseline_no_longer_passes"],
        "in_band_should_pass": {
            "+14.9%": tally("in_band_+14.9%", True),
            "-14.9%": tally("in_band_-14.9%", True),
        },
        "out_band_should_fail": {
            "+16%": tally("out_band_+16%", False),
            "-16%": tally("out_band_-16%", False),
        },
        "reorder_should_pass": tally("reversed_logs", True),
        "rows": rows,
    }

    print(f"report={summary['report']}  tasks with an anchored weighted write and an accepted trajectory: {summary['tasks_probed']}")
    if summary["unprobed"]:
        print(f"  unprobed (no log_meal of an anchored food, or an amend_meal): {summary['unprobed']}")
    if summary["baseline_regressions"]:
        print(f"  !! baseline regressions: {summary['baseline_regressions']}")
    for label, block in summary["in_band_should_pass"].items():
        print(f"  within band {label:8s} still passes: {block['as_expected']}/{block['n']}")
    for label, block in summary["out_band_should_fail"].items():
        print(f"  past band   {label:8s} still rejected: {block['as_expected']}/{block['n']}")
    print(f"  reordered logs accepted: {summary['reorder_should_pass']['as_expected']}/{summary['reorder_should_pass']['n']}")

    # Any perturbation that contradicts its expectation is a scorer finding, whatever the tag.
    findings = []
    for label in ("in_band_+14.9%", "in_band_-14.9%", "reversed_logs"):
        findings += [r["task_id"] for r in rows if isinstance(r.get(label), dict) and r[label].get("passed") is False]
    for label in ("out_band_+16%", "out_band_-16%"):
        findings += [r["task_id"] for r in rows if isinstance(r.get(label), dict) and r[label].get("passed") is True]
    if findings:
        print(f"  scorer_outliers ({len(findings)}): {sorted(set(findings))}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
