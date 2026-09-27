#!/usr/bin/env python3
"""Counterfactual scoring for the verify-then-revise ablation (DESIGN_v2.1, 2026-09-25).

The verify gate acts only at a hand-in, so up to its first bounce an episode is the baseline
episode. Without the gate the bounced plan would have reached Env, been accepted, and ended the
episode. Replaying the env-stepped prefix and then submitting that plan gives the no-gate
outcome exactly (the Env is deterministic); the actual outcome is the gated one.

    # per-event records and per-report counts for verify / verify-placebo reports
    .venv/bin/python scripts/verify_counterfactual.py pairs R1_verify.json R1_placebo.json ... \\
        --json pairs.json

    # the pre-registered decision statistics over a pairs file (DESIGN_v2.1 §4)
    .venv/bin/python scripts/verify_counterfactual.py stats pairs.json

    # run the gate offline over an ungated report (exam or ablation) to count would-be bounces
    .venv/bin/python scripts/verify_counterfactual.py simulate x_full.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.bench import SCORER_VERSION, Scorer, load_split  # noqa: E402
from nutrienv.env import NutriEnv  # noqa: E402
from nutrienv.harness.buddy import (  # noqa: E402
    ObservationCache,
    ingest_observation,
    plan_key,
    track_ledger,
    verify_plan,
)
from nutrienv.harness.prompt_freeze import assert_frozen  # noqa: E402
from nutrienv.harness.runner import FINISH_OPS  # noqa: E402
from nutrienv.world.catalog_store import GOLD_CATALOG_PATH, load_catalog  # noqa: E402

DEFAULT_SPLIT = _ROOT / "data" / "splits" / "nutrienv-v1.0.json"
VERIFY_ARM = "verify"
PLACEBO_ARM = "verify-placebo"
PREVIEW_ARM = "preview"

# Pre-registered thresholds (DESIGN_v2.1 §4). Fixed before any verify run; do not tune.
MAX_FALSE_REJECT_RATE = 0.05
MIN_RESCUE_RATE_GAP = 0.25
ALPHA = 0.05
FUTILITY_MIN_TRIGGERS = 12
FUTILITY_MAX_NET = 1


def replay_then_submit(task, prefix: list[dict], plan: dict) -> dict:
    """Step ``prefix`` through a fresh Env, submit ``plan``, and score the end state.

    Returns ``{"resolved": False}`` when Env refuses the plan: without the gate that episode
    would have continued, and its continuation is not in this run.
    """
    env = NutriEnv()
    env.reset(task.s0)
    for action in prefix:
        if isinstance(action, dict) and action.get("op") in FINISH_OPS:
            break
        env.step(action)
    result = env.step(plan)
    if not result.get("ok"):
        return {"resolved": False, "error": str(result.get("error"))[:200]}
    score = Scorer().score(env.state(), task.oracle)
    return {
        "resolved": True,
        "passed": bool(score["passed"]),
        "tag": score["tag"],
        "sub_tags": list(score.get("sub_tags") or []),
    }


def classify(cf: dict, actual_passed: bool) -> str:
    if not cf.get("resolved"):
        return "unresolved"
    if not cf["passed"] and actual_passed:
        return "rescued"
    if cf["passed"] and not actual_passed:
        return "broken"
    if cf["passed"]:
        return "false_reject_harmless"
    return "still_failed"


def classify_preview(cf: dict, actual_passed: bool, unchanged: bool) -> str:
    """A preview fires on every hand-in, so a passing plan can be changed into a failing one."""
    if not cf.get("resolved"):
        return "unresolved"
    if not cf["passed"] and actual_passed:
        return "rescued"
    if cf["passed"] and not actual_passed:
        return "broken"
    prefix = "confirmed" if unchanged else "changed_still"
    return f"{prefix}_{'pass' if actual_passed else 'fail'}"


def _committed_plan(row: dict, after: int) -> dict | None:
    """The last hand-in that reached Env at or after step ``after`` (the one that ended it)."""
    for step in reversed(row["steps"][after:]):
        action = step.get("action")
        if isinstance(action, dict) and action.get("op") == "submit_plan" and not step.get("refused"):
            return action
    return None


def failing_tags(cf: dict) -> list[str]:
    """Every failing check of the counterfactual end state (a composite's children included)."""
    if not cf.get("resolved") or cf.get("passed"):
        return []
    subs = [tag for tag in cf.get("sub_tags") or [] if tag != "pass"]
    return subs or [cf["tag"]]


def score_pairs(
    rows: list[dict], tasks: dict, *, arm: str = "", run: str = "", lookup=None
) -> list[dict]:
    """One record per task whose episode was bounced or previewed (first event only)."""
    out = []
    for row in rows:
        events = row.get("verify_events") or []
        if row.get("void") or not events:
            continue
        task_id = row.get("id") or row.get("task_id")
        first = events[0]
        prefix = [s["action"] for s in row["steps"][: first["env_steps_before"]]]
        cf = replay_then_submit(tasks[task_id], prefix, first["action"])
        failing = failing_tags(cf)
        actual_passed = bool(row["passed"])
        if first.get("kind") == "preview":
            committed = _committed_plan(row, first["env_steps_before"])
            unchanged = committed is not None and plan_key(committed, lookup) == plan_key(
                first["action"], lookup
            )
            outcome = classify_preview(cf, actual_passed, unchanged)
        else:
            outcome = classify(cf, actual_passed)
        out.append(
            {
                "arm": arm,
                "run": run,
                "id": task_id,
                "bounces": len(events),
                "drift": int(row.get("verify_drift", 0) or 0),
                "cf": cf,
                "actual_passed": actual_passed,
                "actual_tag": row.get("tag") or row.get("score_tag"),
                "outcome": outcome,
                "cf_tag": cf.get("tag"),
                # Mechanism attribution: fixing the window can only rescue a plan whose sole
                # failure was the window. `window_anywhere` is the loose upper bound.
                "window_only": failing == ["window"],
                "window_anywhere": "window" in failing,
            }
        )
    return out


def counts(records: list[dict]) -> dict:
    tally = {k: 0 for k in ("rescued", "broken", "false_reject_harmless", "still_failed",
                             "unresolved")}
    for rec in records:
        tally[rec["outcome"]] = tally.get(rec["outcome"], 0) + 1
    resolved = len(records) - tally["unresolved"]
    cf_pass = tally["broken"] + tally["false_reject_harmless"]
    return {
        "triggers": len(records),
        **tally,
        "cf_pass": cf_pass,
        "false_reject_rate": cf_pass / resolved if resolved else 0.0,
        "net": tally["rescued"] - tally["broken"],
        "rescued_window_only": sum(
            1 for r in records if r["outcome"] == "rescued" and r["window_only"]
        ),
        "window_only_events": sum(1 for r in records if r["window_only"]),
        "rescued_window_anywhere": sum(
            1 for r in records if r["outcome"] == "rescued" and r["window_anywhere"]
        ),
        "drift": sum(r["drift"] for r in records),
    }


# --- statistics -------------------------------------------------------------------------------


def _event_score(rec: dict) -> int:
    return {"rescued": 1, "broken": -1}.get(rec["outcome"], 0)


def net_gain_ci(
    records: list[dict], universe: list[str], runs: int, *, iters: int = 10000, seed: int = 0
) -> dict:
    """Claim A: mean per-run net gain, with a 95% bootstrap CI clustered on task.

    Every task in ``universe`` is a cluster (a task that never bounced contributes 0), so the
    resampling keeps the denominator the exam's, not just the bounced subset.
    """
    per_task = {task: 0 for task in universe}
    for rec in records:
        per_task[rec["id"]] = per_task.get(rec["id"], 0) + _event_score(rec)
    values = list(per_task.values())
    point = sum(values) / runs
    rng = random.Random(seed)
    draws = sorted(
        sum(rng.choice(values) for _ in values) / runs for _ in range(iters)
    )
    return {
        "mean_net_per_run": point,
        "ci95": [draws[int(0.025 * iters)], draws[int(0.975 * iters) - 1]],
    }


def _rescue_rate(records: list[dict]) -> float:
    pool = [r for r in records if r["outcome"] in ("rescued", "still_failed")]
    return sum(1 for r in pool if r["outcome"] == "rescued") / len(pool) if pool else 0.0


def rescue_rate_permutation(
    verify: list[dict], placebo: list[dict], *, iters: int = 10000, seed: int = 0
) -> dict:
    """Claim B: rescue rate (among bounced plans that would have failed), verify vs placebo.

    One-sided permutation test clustered on task: under H0 the arm label is exchangeable, so
    each task's verify events and placebo events swap sides together with probability 1/2.
    """
    by_task: dict[str, tuple[list, list]] = {}
    for rec in verify:
        by_task.setdefault(rec["id"], ([], []))[0].append(rec)
    for rec in placebo:
        by_task.setdefault(rec["id"], ([], []))[1].append(rec)
    observed = _rescue_rate(verify) - _rescue_rate(placebo)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(iters):
        left: list[dict] = []
        right: list[dict] = []
        for v, p in by_task.values():
            if rng.random() < 0.5:
                v, p = p, v
            left.extend(v)
            right.extend(p)
        if _rescue_rate(left) - _rescue_rate(right) >= observed:
            extreme += 1
    return {
        "rescue_rate_verify": _rescue_rate(verify),
        "rescue_rate_placebo": _rescue_rate(placebo),
        "gap": observed,
        "p_one_sided": (extreme + 1) / (iters + 1),
    }


def decide_preview(pairs: dict) -> dict:
    """Claim C (DESIGN_v3.1 §4): preview vs no preview, ITT over every first preview."""
    records = [r for r in pairs["records"] if r["arm"] == PREVIEW_ARM]
    runs = pairs["runs"].get(PREVIEW_ARM, [])
    tally = counts(records)
    claim = net_gain_ci(records, pairs["universe"], max(1, len(runs)))
    if claim["ci95"][0] > 0:
        verdict = "effective"
    elif claim["ci95"][1] < 0:
        verdict = "harmful"
    elif tally["window_only_events"] >= FUTILITY_MIN_TRIGGERS and tally["net"] <= FUTILITY_MAX_NET:
        verdict = "no effect"
    else:
        verdict = "inconclusive"
    broken = [r for r in records if r["outcome"] == "broken"]
    return {
        "runs": runs,
        "preview": tally,
        "broken_detail": [
            {"id": r["id"], "cf_tag": r["cf_tag"], "actual_tag": r["actual_tag"], "drift": r["drift"]}
            for r in broken
        ],
        "claim_c": {**claim, "verdict": verdict},
    }


def decide(pairs: dict) -> dict:
    """Apply the pre-registered rules to a pairs file (records + per-arm task universes)."""
    if PREVIEW_ARM in pairs["runs"]:
        return decide_preview(pairs)
    records = pairs["records"]
    verify = [r for r in records if r["arm"] == VERIFY_ARM]
    placebo = [r for r in records if r["arm"] == PLACEBO_ARM]
    runs = pairs["runs"].get(VERIFY_ARM, [])
    verify_counts = counts(verify)
    claim_a = net_gain_ci(verify, pairs["universe"], max(1, len(runs)))
    a_effective = (
        claim_a["ci95"][0] > 0 and verify_counts["false_reject_rate"] <= MAX_FALSE_REJECT_RATE
    )
    futile = (
        verify_counts["triggers"] >= FUTILITY_MIN_TRIGGERS
        and verify_counts["net"] <= FUTILITY_MAX_NET
    )
    out = {
        "runs": {arm: sorted(v) for arm, v in pairs["runs"].items()},
        "verify": verify_counts,
        "placebo": counts(placebo),
        "claim_a": {**claim_a, "effective": a_effective,
                    "verdict": "effective" if a_effective else ("no effect" if futile else "inconclusive")},
    }
    if placebo:
        claim_b = rescue_rate_permutation(verify, placebo)
        b_effective = (
            claim_b["gap"] >= MIN_RESCUE_RATE_GAP and claim_b["p_one_sided"] < ALPHA
        )
        out["claim_b"] = {**claim_b, "verdict": "effective" if b_effective else "inconclusive"}
    return out


# --- report loading ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_ruler(report: dict, split: Path) -> None:
    """Refuse a report measured on another scorer, prompt generation, split or catalog."""
    if report.get("scorer_version") != SCORER_VERSION:
        raise SystemExit(
            f"scorer mismatch: report {report.get('scorer_version')!r} vs {SCORER_VERSION!r}"
        )
    assert_frozen(report)
    recorded = report.get("split")
    if recorded and (_ROOT / recorded).resolve() != split.resolve():
        raise SystemExit(f"split mismatch: report {recorded!r} vs {split}")
    meta = json.loads(split.read_text(encoding="utf-8"))
    catalog = (_ROOT / meta["catalog"]).resolve()
    if catalog != GOLD_CATALOG_PATH.resolve() or _sha256(catalog) != meta["catalog_sha256"]:
        raise SystemExit(f"catalog mismatch: split records {meta['catalog']}")


def _catalog_lookup():
    catalog = load_catalog(GOLD_CATALOG_PATH)

    def lookup(food_id: str):
        entry = catalog.get(food_id)
        if entry is None or not ("nutrients" in entry or "allergen_tags" in entry):
            return None
        return dict(entry)

    return lookup


def _actions(row: dict) -> list[dict]:
    return [s["action"] if isinstance(s, dict) else s.action for s in row.get("steps") or []]


def simulate(rows: list[dict], tasks: dict, lookup) -> list[dict]:
    """Where would the verify gate have bounced this ungated trajectory, and to what end?"""
    out = []
    for row in rows:
        task = tasks.get(row.get("task_id") or row.get("id"))
        if task is None or row.get("is_void") or row.get("void"):
            continue
        env = NutriEnv()
        observation = env.reset(task.s0)
        cache = ObservationCache()
        prefix: list[dict] = []
        for action in _actions(row):
            ingest_observation(cache, observation)
            track_ledger(cache, observation)
            if not isinstance(action, dict) or action.get("op") in FINISH_OPS:
                break
            verdict = verify_plan(action, cache, query=task.query, lookup=lookup)
            if not verdict.ok:
                cf = replay_then_submit(task, prefix, action)
                outcome = (
                    "unresolved" if not cf.get("resolved")
                    else "cf_pass" if cf["passed"] else "cf_fail"
                )
                out.append({"id": task.id, "lines": list(verdict.lines), "cf": cf,
                            "outcome": outcome})
                break
            result = env.step(action)
            prefix.append(action)
            observation = (
                result["observation"]
                if result.get("ok") and isinstance(result.get("observation"), dict)
                else {"error": result.get("error")}
            )
            if action.get("op") == "submit_plan" and result.get("ok"):
                break
    return out


def run_id(report: dict, path: Path) -> str:
    """An interleaved report names its window; otherwise its directory tells the rounds apart."""
    window = (report.get("config") or {}).get("run_window_id")
    return str(window) if window else f"{path.parent.name}/{path.stem}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["pairs", "stats", "simulate"])
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--json", type=Path, default=None, help="pairs: write records here")
    args = parser.parse_args(argv)

    if args.mode == "stats":
        for path in args.inputs:
            print(json.dumps(decide(json.loads(path.read_text(encoding="utf-8"))), indent=2))
        return 0

    tasks = {t.id: t for t in load_split(args.split)}
    all_records: list[dict] = []
    runs: dict[str, set] = {}
    lookup = _catalog_lookup()
    universe: set[str] = set()
    for path in args.inputs:
        report = json.loads(path.read_text(encoding="utf-8"))
        check_ruler(report, args.split)
        rows = report["tasks"]
        if args.mode == "simulate":
            records = simulate(rows, tasks, lookup)
            tally: dict[str, int] = {}
            for rec in records:
                tally[rec["outcome"]] = tally.get(rec["outcome"], 0) + 1
            print(f"{path.name}: would bounce {len(records)} {tally}")
            for rec in records:
                print("  " + json.dumps(rec, default=str)[:300])
            continue
        arm = str(report.get("scaffold") or "")
        run = run_id(report, path)
        records = score_pairs(rows, tasks, arm=arm, run=run, lookup=lookup)
        all_records.extend(records)
        runs.setdefault(arm, set()).add(run)
        if arm in (VERIFY_ARM, PREVIEW_ARM):
            universe.update(r.get("id") for r in rows if not r.get("void"))
        print(f"{path.name} [{arm} {run}]: {json.dumps(counts(records))}")
    if args.mode == "pairs" and args.json:
        payload = {
            "records": all_records,
            "runs": {arm: sorted(v) for arm, v in runs.items()},
            "universe": sorted(universe),
        }
        args.json.write_text(json.dumps(payload, indent=1, default=str) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
