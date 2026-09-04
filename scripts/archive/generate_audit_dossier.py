"""Generate a structured dossier for all 128 tasks in the v1.0 benchmark
comparing DeepSeek-V4-Flash and GLM-5.3-flash executions for False Positive / False Negative audit.
"""
import json
from pathlib import Path
from nutrienv.bench import load_split
from nutrienv.world.catalog_store import load_catalog

def main():
    root = Path(".")
    catalog = load_catalog(root / "data/fdc/catalog-v2.sqlite")
    gold_tasks = {t.id: t for t in load_split(root / "data/splits/v2.5-gold.json", catalog=catalog)}
    
    with open("reports/benchmark_ark_deepseek-v4-flash_v1.0.json") as f:
        ds = {t["task_id"]: t for t in json.load(f)["tasks"]}
    with open("reports/benchmark_ark_glm-5.3-flash_v1.0.json") as f:
        glm = {t["task_id"]: t for t in json.load(f)["tasks"]}
        
    all_ids = sorted(list(gold_tasks.keys()))
    
    dossier = []
    
    for tid in all_ids:
        t = gold_tasks[tid]
        d = ds.get(tid, {})
        g = glm.get(tid, {})
        
        # summarize actions
        def summarize_steps(steps):
            summary = []
            for s in steps:
                act = s.get("action", {})
                op = act.get("op")
                if op in ("log_meal", "amend_meal"):
                    summary.append(f"{op}(fid={act.get('food_id')}, g={act.get('grams')})")
                elif op == "update_profile":
                    summary.append(f"update_profile({list(act.get('patch', {}).keys())})")
                elif op == "submit_plan":
                    v = act.get("verdict")
                    items_len = len(act.get("items", []))
                    reasons = act.get("reasons", [])
                    summary.append(f"submit_plan(v={v}, items={items_len}, r={reasons})")
                elif op in ("search_foods", "get_food"):
                    pass # query ops
                else:
                    summary.append(f"{op}")
            return summary
            
        entry = {
            "id": tid,
            "family": t.family,
            "query": t.query,
            "oracle": {
                "profile_patch": t.oracle.profile_patch if hasattr(t.oracle, "profile_patch") else None,
                "ledger": [{"food_id": r.food_id, "grams": r.grams} for r in (t.oracle.ledger or ())] if hasattr(t.oracle, "ledger") else [],
                "verdict": getattr(t.oracle, "last_verdict", None),
                "reasons": getattr(t.oracle, "last_reasons", []),
            },
            "deepseek": {
                "passed": d.get("passed", False),
                "score_tag": d.get("score_tag"),
                "total_steps": len(d.get("steps", [])),
                "key_actions": summarize_steps(d.get("steps", [])),
            },
            "glm": {
                "passed": g.get("passed", False),
                "score_tag": g.get("score_tag"),
                "total_steps": len(g.get("steps", [])),
                "key_actions": summarize_steps(g.get("steps", [])),
            }
        }
        dossier.append(entry)
        
    out_path = Path(".scratch/audit_128_dossier.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(dossier, f, indent=2)
        
    print(f"Generated dossier with {len(dossier)} tasks at {out_path}")

if __name__ == "__main__":
    main()
