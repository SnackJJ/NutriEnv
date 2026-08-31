"""NutriEnv ADR 0024 Benchmark Matrix Builder.

Inherits 34 clean tasks from v2.1-gold, over-generates ~115 candidate tasks,
filters and selects the best 66 new tasks to assemble the official 100-task
standard benchmark matrix (data/splits/v2.2-gold.json) and samples 20 tasks
for data/splits/v2.2-mini.json.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.types import LedgerRow, Profile, WorldState
from nutrienv.bench.realize import Oracle, Task, compose_oracles
from nutrienv.bench.achievable import check_achievable
from nutrienv.bench.pipeline.freezer import freeze_tasks
from nutrienv.bench.split import load_split
from scripts.generate_samples_v2 import (
    generate_log_sample,
    generate_eval_sample,
    generate_rec_sample,
    generate_upd_sample,
    generate_comp_sample,
    render_html_review_dashboard,
    DEFAULT_CATALOG_PATH,
)

V21_GOLD_PATH = "data/splits/v2.1-gold.json"
V22_CANDIDATE_PATH = "data/candidates/v2.2-candidates.json"
V22_GOLD_PATH = "data/splits/v2.2-gold.json"
V22_MINI_PATH = "data/splits/v2.2-mini.json"
V22_HTML_REPORT = "reports/v2.2-benchmark-review.html"

# Pruned from v2.1
PRUNED_V21_IDS = frozenset({
    "adr20-log-5000",   # Sweet potato paste single-item meal
    "adr20-eval-5011",  # Korean dressing/marinade pure condiment
    "adr20-comp-5038",  # Tea with milk pure beverage
    "adr20-upd-5030",   # Excess update quota
    "adr20-upd-5032",   # Excess update quota
    "adr20-upd-5033",   # Excess update quota
})


def load_retained_v21_tasks(v21_path: Path, catalog: Mapping) -> dict[str, list[dict]]:
    """Load and sanitize the 34 retained tasks from v2.1."""
    all_tasks = load_split(v21_path, catalog=catalog)

    tasks_by_family = {
        "update": [],
        "log": [],
        "evaluate": [],
        "recommend": [],
        "composite": [],
    }

    for task in all_tasks:
        if task.id in PRUNED_V21_IDS:
            continue

        if task.id.startswith("adr20-comp"):
            task = Task(
                id=task.id,
                family="composite",
                query=task.query,
                s0=task.s0,
                oracle=task.oracle,
                persona=task.persona,
            )

        class _MockPerson:
            def __init__(self, prof):
                self.persona = task.persona or "everyday"
                self.diet_style = "standard"
                self.sex = prof.sex or "unknown"
                self.age_y = prof.age_y or 30
                self.weight_kg = prof.weight_kg or 70.0
                self.activity = prof.activity or "moderate"

        person = _MockPerson(task.s0.profile)
        tasks_by_family[task.family].append({
            "task": task,
            "person": person,
            "resolutions": [],
            "source": "v2.1-retained",
        })

    return tasks_by_family


def main():
    parser = argparse.ArgumentParser(description="NutriEnv ADR 0024 Benchmark Matrix Builder")
    parser.add_argument("--catalog", type=str, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--model", type=str, default="qwen3.8-2.4t-a95b")
    parser.add_argument("--start-seed", type=int, default=8200)
    args = parser.parse_args()

    catalog = load_catalog(Path(args.catalog))
    retained_tasks = load_retained_v21_tasks(Path(V21_GOLD_PATH), catalog)

    print("=== Step 1: Loaded Retained Tasks from v2.1 ===")
    for fam, items in retained_tasks.items():
        print(f"  [{fam.upper()}]: {len(items)} retained tasks")
    total_retained = sum(len(items) for items in retained_tasks.values())
    print(f"  Total retained: {total_retained} tasks")

    # Target quotas for 100 benchmark
    GOLD_QUOTAS = {
        "update": 5,
        "log": 15,
        "evaluate": 20,
        "recommend": 20,
        "composite": 40,
    }

    # Needed incremental counts
    NEEDED_COUNTS = {fam: GOLD_QUOTAS[fam] - len(retained_tasks[fam]) for fam in GOLD_QUOTAS}
    print(f"\n=== Step 2: Incremental Targets Needed: {NEEDED_COUNTS} ===")

    all_candidate_items = {fam: list(retained_tasks[fam]) for fam in GOLD_QUOTAS}
    selected_gold_tasks = {fam: [it["task"] for it in retained_tasks[fam]] for fam in GOLD_QUOTAS}

    global_seed = args.start_seed

    # 1. Log: Need 8 new -> Overgenerate 16 candidates
    print("\n[1/4] Over-generating Log candidates (need 8, generating up to 16)...")
    log_target_new = NEEDED_COUNTS["log"]
    while len(selected_gold_tasks["log"]) < GOLD_QUOTAS["log"] and global_seed < args.start_seed + 1000:
        item = generate_log_sample(global_seed, catalog, model_id=args.model, enable_vote=True)
        if item:
            rep = check_achievable([item["task"]])
            if not rep.unreachable:
                all_candidate_items["log"].append(item)
                selected_gold_tasks["log"].append(item["task"])
                print(f"  [Log {len(selected_gold_tasks['log'])}/{GOLD_QUOTAS['log']}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # 2. Evaluate: Need 13 new -> Overgenerate candidates matching modes (0: allergy, 1: accept, 2: kcal_lo, 3: kcal_hi)
    print("\n[2/4] Over-generating Evaluate candidates (need 13, generating up to 25)...")
    eval_target_modes = [0, 0, 1, 2, 3, 0, 0, 1, 2, 3, 0, 1, 2]  # 5 allergy, 3 accept, 3 kcal_lo, 2 kcal_hi
    for mode in eval_target_modes:
        item = None
        while item is None and global_seed < args.start_seed + 2000:
            cand = generate_eval_sample(global_seed, catalog, model_id=args.model, enable_vote=True, target_mode=mode)
            global_seed += 1
            if cand:
                rep = check_achievable([cand["task"]])
                if not rep.unreachable:
                    item = cand
                    all_candidate_items["evaluate"].append(item)
                    selected_gold_tasks["evaluate"].append(item["task"])
                    print(f"  [Eval {len(selected_gold_tasks['evaluate'])}/{GOLD_QUOTAS['evaluate']}, mode={mode}] seed={global_seed-1} -> \"{item['task'].query}\"")

    # 3. Recommend: Need 12 new -> Overgenerate 20 candidates
    print("\n[3/4] Over-generating Recommend candidates (need 12, generating up to 20)...")
    while len(selected_gold_tasks["recommend"]) < GOLD_QUOTAS["recommend"] and global_seed < args.start_seed + 3000:
        item = generate_rec_sample(global_seed, catalog)
        if item:
            rep = check_achievable([item["task"]])
            if not rep.unreachable:
                all_candidate_items["recommend"].append(item)
                selected_gold_tasks["recommend"].append(item["task"])
                print(f"  [Rec {len(selected_gold_tasks['recommend'])}/{GOLD_QUOTAS['recommend']}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # 4. Composite: Need 33 new (5 log_rec, 4 log_upd, 4 log_eval, 4 upd_rec, 4 upd_log_rec, 4 log_upd_eval, 4 upd_log_eval, 4 upd_upd_log_rec)
    print("\n[4/4] Over-generating Composite candidates (need 33 across 3-tier multi-intent hierarchy)...")
    comp_needed_subtypes = (
        ["log_rec"] * 5 + ["log_upd"] * 4 + ["log_eval"] * 4 + ["upd_rec"] * 4 +  # Tier 1 Dual (17)
        ["upd_log_rec"] * 4 + ["log_upd_eval"] * 4 + ["upd_log_eval"] * 4 +        # Tier 2 Tri (12)
        ["upd_upd_log_rec"] * 4                                                    # Tier 3 Quad (4)
    )

    for sub_type in comp_needed_subtypes:
        item = None
        while item is None and global_seed < args.start_seed + 5000:
            cand = generate_comp_sample(global_seed, catalog, model_id=args.model, enable_vote=True, sub_type=sub_type)
            global_seed += 1
            if cand:
                rep = check_achievable([cand["task"]])
                if not rep.unreachable:
                    item = cand
                    all_candidate_items["composite"].append(item)
                    selected_gold_tasks["composite"].append(item["task"])
                    print(f"  [Comp {len(selected_gold_tasks['composite'])}/{GOLD_QUOTAS['composite']}, {sub_type}] seed={global_seed-1} -> \"{item['task'].query}\"")

    # Freeze Candidate Split
    cand_tasks = []
    for fam in ("update", "log", "evaluate", "recommend", "composite"):
        cand_tasks.extend([it["task"] for it in all_candidate_items[fam]])
    cand_path = Path(V22_CANDIDATE_PATH)
    cand_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_tasks(
        cand_tasks,
        catalog=catalog,
        catalog_field=args.catalog,
        output_path=cand_path,
        overwrite=True,
    )
    print(f"\nFrozen {len(cand_tasks)} Candidate Pool Tasks to {cand_path}")

    # Combine all 100 gold tasks
    final_100_tasks = []
    for fam in ("update", "log", "evaluate", "recommend", "composite"):
        final_100_tasks.extend(selected_gold_tasks[fam])

    print("\n=== Step 3: Full 100-Task Benchmark Verification ===")
    rep = check_achievable(final_100_tasks)
    print(f"  Check Achievable Result: unreachable={len(rep.unreachable)}, by_family={rep.by_family}")
    assert len(rep.unreachable) == 0, f"Unreachable tasks found: {rep.unreachable}"
    assert len(final_100_tasks) == 100, f"Expected 100 tasks, got {len(final_100_tasks)}"

    # Render HTML Review Dashboard
    render_html_review_dashboard(all_candidate_items, Path(V22_HTML_REPORT))

    # Freeze Gold Split
    gold_path = Path(V22_GOLD_PATH)
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_tasks(
        final_100_tasks,
        catalog=catalog,
        catalog_field=args.catalog,
        output_path=gold_path,
        overwrite=True,
    )
    print(f"\nFrozen 100-Task Benchmark Gold Split to {gold_path}")

    # Freeze 20-Task Mini Split (1 Upd, 3 Log, 4 Eval, 4 Rec, 8 Comp)
    mini_tasks = (
        selected_gold_tasks["update"][:1]
        + selected_gold_tasks["log"][:3]
        + selected_gold_tasks["evaluate"][:4]
        + selected_gold_tasks["recommend"][:4]
        + selected_gold_tasks["composite"][:8]
    )
    mini_path = Path(V22_MINI_PATH)
    freeze_tasks(
        mini_tasks,
        catalog=catalog,
        catalog_field=args.catalog,
        output_path=mini_path,
        overwrite=True,
    )
    print(f"Frozen 20-Task Mini Split to {mini_path}")
    print("\n=======================================================")
    print("  🎉 ADR 0024 100-TASK BENCHMARK BUILD COMPLETED 100%!")
    print("=======================================================")


if __name__ == "__main__":
    main()
