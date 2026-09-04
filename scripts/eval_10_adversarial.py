import os
import sys
import json
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))

from nutrienv.io.dotenv import load_dotenv_keys
from nutrienv.io.chat import lookup_chat_model
from nutrienv.world.catalog_store import load_catalog
from nutrienv.bench import load_split
import eval_benchmark_suite as suite

def main():
    load_dotenv_keys(_ROOT / ".env.local")
    catalog = load_catalog(_ROOT / "data" / "fdc" / "catalog-v2.sqlite")
    all_tasks = load_split(_ROOT / "data" / "splits" / "v2.3-gold.json", catalog=catalog)

    target_ids = [
        "adr25-eval-1201",
        "adr25-eval-1202",
        "adr25-eval-1203",
        "adr25-eval-1204",
        "adr25-comp-1205",
        "adr25-comp-1206",
        "adr25-comp-1207",
        "adr25-comp-1208",
        "adr25-rec-1209",
        "adr25-rec-1210",
    ]

    target_tasks = [next(t for t in all_tasks if t.id == tid) for tid in target_ids]
    print(f"Loaded {len(target_tasks)} adversarial target tasks for evaluation.")

    spec = lookup_chat_model("ark/deepseek-v4-flash")
    api_key = os.environ.get(spec.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing API key for {spec.api_key_env}")

    harness_spec = {
        "model": spec.model_id,
        "url": spec.url,
        "api_key": api_key,
        "timeout": 90.0,
        "retries": 4,
        "version": "v0",
        "context_limit": None,
    }

    print(f"\n🚀 Running 10 New Adversarial Tasks with DeepSeek-V4-Flash via ARK (timeout=90s)...")
    results = {}

    for idx, t in enumerate(target_tasks, 1):
        print(f"\n========================================================")
        print(f"[{idx}/{len(target_tasks)}] Starting {t.id} ({t.family})")
        print(f"Query: {t.query}")
        print(f"--------------------------------------------------------")
        start_t = time.time()
        tele = suite.evaluate_task_with_telemetry(t, harness_spec, catalog)
        duration = time.time() - start_t
        results[t.id] = tele
        mark = "✅ PASS" if tele.passed else "❌ FAIL"
        print(f"Outcome: {mark} | Score Tag: {tele.score_tag} | Steps: {tele.n_steps}/{tele.max_budget} | Time: {duration:.1f}s")
        for s_idx, s in enumerate(tele.steps, 1):
            op = s.action.get("op", "unknown")
            snippet = s.observation_snippet.replace("\n", " ")[:90]
            print(f"  Step {s_idx:02d} [{op}]: obs -> {snippet}")

    out_file = _ROOT / "reports" / "eval_10_adversarial_deepseek_flash.json"
    report = {
        "model": "ark/deepseek-v4-flash",
        "total_tasks": len(target_tasks),
        "passed_tasks": sum(1 for t in results.values() if t.passed),
        "pass_rate_pct": (sum(1 for t in results.values() if t.passed) / len(target_tasks)) * 100.0,
        "tasks": [suite.asdict(results[tid]) for tid in target_ids if tid in results]
    }
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n========================================================")
    print(f"Saved trajectory report to: {out_file}")
    print(f"Overall Pass Rate: {report['pass_rate_pct']:.1f}% ({report['passed_tasks']}/{report['total_tasks']})")

if __name__ == "__main__":
    main()
