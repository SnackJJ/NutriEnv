#!/usr/bin/env python3
"""Re-judge an exam report's trajectories with the current Scorer.

The Scorer judges only the finished world, after the episode, so a scoring-rule change does not
change what any model did: replaying each recorded action into a fresh Env rebuilds the exact end
state the run reached, and scoring it with today's rule is what a rerun under that rule would have
scored for the same trajectories. What a rescore cannot stand in for is a change to anything the
model saw or how its turns were handled, so it refuses a report whose prompt generation or episode
loop differs from the current code; that needs a real run.

Replay fidelity is checked, not assumed: every executed action must be accepted or refused by Env
exactly as the run recorded it (`refused`), or the report is left alone.

    .venv/bin/python scripts/rescore_report.py reports/run.json --out reports/run.rescored.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.bench import SCORER_VERSION, Scorer, load_split  # noqa: E402
from nutrienv.env import NutriEnv  # noqa: E402
from nutrienv.harness.prompt_freeze import assert_frozen  # noqa: E402
from nutrienv.harness.runner import FINISH_OPS, LOOP_VERSION  # noqa: E402

FAMILIES = ("update", "log", "evaluate", "recommend", "composite")


def _executed(step: dict, policy: str) -> bool:
    """Whether the run handed this step's action to Env."""
    op = (step.get("action") or {}).get("op")
    if op == "text_response":  # native-tools turn with no tool call
        return False
    # Under feedback/resample a violating turn is re-asked, not executed; under silent the
    # recorded action is the fallback the loop did execute.
    return not (step.get("protocol_violation") and policy != "silent")


def rescore_task(task, record: dict, policy: str, scorer: Scorer) -> dict:
    """The task's record re-judged, or ValueError when the replay diverges from the run."""
    env = NutriEnv()
    env.reset(task.s0)
    for index, step in enumerate(record.get("steps", [])):
        action = step.get("action") or {}
        if action.get("op") in FINISH_OPS:
            break
        if not _executed(step, policy):
            continue
        result = env.step(action)
        if (not result.get("ok")) != bool(step.get("refused", False)):
            raise ValueError(
                f"{record['task_id']} step {index}: Env "
                f"{'refused' if not result.get('ok') else 'accepted'} an action the run recorded "
                f"as {'refused' if step.get('refused') else 'accepted'}"
            )
    score = scorer.score(env.state(), task.oracle)
    tag = str(score["tag"])
    return {
        **record,
        "passed": bool(score["passed"]),
        "score_tag": tag,
        "allergen_violated": tag in ("allergy", "FatalAllergyClash"),
    }


def rescore_report(report: dict, tasks: dict) -> dict:
    """The report with every non-void task re-judged and its pass figures recomputed."""
    assert_frozen(report)
    if report.get("loop_version") != LOOP_VERSION:
        raise SystemExit(
            f"report ran under loop_version={report.get('loop_version') or 'unrecorded'}, the "
            f"current loop is {LOOP_VERSION}: its trajectories are not this loop's, rerun instead"
        )
    policy = str(report.get("parse_error_policy") or "silent")
    scorer = Scorer()
    missing = [r["task_id"] for r in report["tasks"] if r["task_id"] not in tasks]
    if missing:
        raise ValueError(f"the split has no task {missing[0]!r} ({len(missing)} missing)")
    rows = [
        record if record.get("is_void") else rescore_task(tasks[record["task_id"]], record, policy, scorer)
        for record in report["tasks"]
    ]
    total = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    # From the rows, not the recorded count, so the rate is what a fresh summary would compute.
    clean = total - sum(1 for r in rows if r.get("is_void"))
    families = dict(report.get("family_breakdown") or {})
    for fam in FAMILIES:
        fam_rows = [r for r in rows if r.get("family") == fam]
        if not fam_rows or fam not in families:
            continue
        fam_pass = sum(1 for r in fam_rows if r["passed"])
        fam_void = sum(1 for r in fam_rows if r.get("is_void"))
        families[fam] = {
            **families[fam],
            "passed": fam_pass,
            "pass_rate": fam_pass / len(fam_rows) * 100,
            "clean_pass_rate": fam_pass / (len(fam_rows) - fam_void) * 100
            if len(fam_rows) > fam_void
            else 0.0,
        }
    return {
        **report,
        "passed_tasks": passed,
        "pass_rate_pct": round(passed / total * 100, 2) if total else 0.0,
        "clean_pass_rate_pct": round(passed / clean * 100, 2) if clean else 0.0,
        "total_allergen_violations": sum(1 for r in rows if r.get("allergen_violated")),
        "scorer_version": SCORER_VERSION,
        # Provenance: which ruler judged this file when the run wrote it.
        "rescored_from_scorer_version": report.get("scorer_version") or "unrecorded",
        "family_breakdown": families,
        "tasks": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-judge an exam report's trajectories with the current Scorer.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    tasks = {t.id: t for t in load_split(report["split"])}
    try:
        rescored = rescore_report(report, tasks)
    except ValueError as exc:
        raise SystemExit(f"replay diverged, report left alone: {exc}") from exc
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rescored, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"{args.report.name}: {report['passed_tasks']} -> {rescored['passed_tasks']}"
        f"/{rescored['total_tasks']} ({report.get('scorer_version')} -> {SCORER_VERSION})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
