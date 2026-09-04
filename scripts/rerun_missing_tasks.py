import json
import time
from pathlib import Path
from nutrienv.bench.split import load_split
from nutrienv.harness.runner import AgentRunner
from nutrienv.bench.scorer import Scorer
from nutrienv.adapters.openai_agent import OpenAIAgentAdapter

SPLIT_PATH = "data/splits/v2.7-gold.json"
REPORT_PATH = "reports/benchmark_ark_deepseek-v4-flash_v2.7.json"
TARGET_IDS = {"adr25-rec-1209", "adr26-rec-1308"}
MODEL = "ark/deepseek-v4-flash"

print(f"Loading split from {SPLIT_PATH}...")
tasks = load_split(SPLIT_PATH)
target_tasks = [t for t in tasks if t.id in TARGET_IDS]
print(f"Found {len(target_tasks)} tasks to run: {[t.id for t in target_tasks]}")

existing_data = json.load(open(REPORT_PATH))
# Remove any existing void or partial runs for target tasks
clean_tasks = [t for t in existing_data.get("tasks", []) if t.get("task_id") not in TARGET_IDS]

scorer = Scorer()
for t in target_tasks:
    print(f"\n>>> Running task {t.id} ({t.family})...")
    adapter = OpenAIAgentAdapter(model=MODEL, timeout_seconds=90.0)
    runner = AgentRunner(harness_version="v2", max_steps=t.max_budget)
    
    t0 = time.time()
    try:
        traj = runner.run(adapter, t.s0, t.query)
        res = scorer.score(traj.final_state, t.oracle)
        elapsed = time.time() - t0
        passed = bool(res.get("passed", False))
        tag = res.get("tag", "unknown")
        print(f"Result {t.id}: Passed={passed}, Tag={tag}, Steps={len(traj.steps)}, Time={elapsed:.1f}s")
        
        clean_tasks.append({
            "task_id": t.id,
            "family": t.family,
            "passed": passed,
            "score_tag": tag,
            "n_steps": len(traj.steps),
            "elapsed_seconds": elapsed,
            "is_void": False,
        })
    except Exception as e:
        print(f"Error on {t.id}: {e}")
        clean_tasks.append({
            "task_id": t.id,
            "family": t.family,
            "passed": False,
            "score_tag": "error",
            "n_steps": 0,
            "elapsed_seconds": time.time() - t0,
            "is_void": True,
            "error": str(e),
        })

existing_data["tasks"] = clean_tasks
passed_count = sum(1 for x in clean_tasks if x.get("passed"))
total_count = len(clean_tasks)
existing_data["summary"] = {
    "total": total_count,
    "passed": passed_count,
    "pass_rate_pct": round(passed_count / total_count * 100, 2) if total_count else 0.0,
    "clean_pass_rate_pct": round(passed_count / total_count * 100, 2) if total_count else 0.0,
}

with open(REPORT_PATH, "w") as f:
    json.dump(existing_data, f, indent=2)

print(f"\n=== COMPLETED ALL {total_count} TASKS! Final Passed: {passed_count}/{total_count} ({passed_count/total_count*100:.1f}%) ===")
