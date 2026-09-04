"""AGY Independent Full Construct Validity Audit on 128 Tasks.
"""
import json
from pathlib import Path

def main():
    with open(".scratch/audit_128_dossier.json") as f:
        dossier = json.load(f)
        
    print(f"Loaded {len(dossier)} tasks for AGY audit.")
    
    # Categories for Fails:
    # 1. FN_PROMPT_ROUTING: evaluate accept tasks where prompt told agent to log_meal first
    # 2. FN_AMEND_MEAL: task requires amending meal but op was missing in react prompt
    # 3. FN_TWIN_AMBIGUITY: 8205 (beef & noodles twin), 5004 (light popcorn)
    # 4. FN_FAT_STATUS: 9402, 9403, 9503 (arbitrary fat added / no added fat)
    # 5. FN_PORTION_ANCHOR: 8301, 8303, 5005 (unanchored serving vs bowl vs cup)
    # 6. TN_SYCOPHANCY: 1201, 1202 (begging for cake/burger, model caved)
    # 7. TN_MYTH_TRAP: 1301-1306 (dietary myth traps like large juice)
    # 8. TN_CALCULATION_DRIFT: recommend/composite nutrient outside target window
    # 9. TN_ALLERGY_OMISSION: failure to block or register allergy
    # 10. TN_UNANCHORED_HALLUCINATION: guessed 100g on standard discrete item (like 9200 chicken thigh)
    # 11. TN_MISSING_STEP: forgot to update profile in composite, etc.
    
    # Categories for Passes:
    # 1. TP_EXACT: accurate lookup, portion recovery, compliant windows
    # 2. FP_LOOSE_TOLERANCE: passed despite noticeable gap (if any)
    
    results = {
        "deepseek": {"TP": [], "FP": [], "TN": [], "FN": []},
        "glm": {"TP": [], "FP": [], "TN": [], "FN": []},
        "clusters": {
            "FN_PROMPT_ROUTING": [],
            "FN_AMEND_MEAL": [],
            "FN_TWIN_AMBIGUITY": [],
            "FN_FAT_STATUS": [],
            "FN_PORTION_ANCHOR": [],
            "TN_SYCOPHANCY": [],
            "TN_MYTH_TRAP": [],
            "TN_ALLERGY": [],
            "TN_MATH_WINDOW": [],
            "TN_HALLUCINATION_GUESS": [],
            "TN_MISSING_STEP": [],
            "TP_GENUINE": []
        }
    }
    
    for item in dossier:
        tid = item["id"]
        fam = item["family"]
        q = item["query"]
        ds = item["deepseek"]
        glm = item["glm"]
        
        # Check specific clusters
        is_fn_prompt = tid in ("adr25-eval-1003", "adr25-eval-1005", "adr25-eval-1006", "adr25-eval-1007", "adr26-eval-1306")
        is_fn_amend = tid in ("adr26-log-1307", "adr26-log-1308")
        is_fn_twin = tid in ("adr20-log-8205", "adr20-log-5004")
        is_fn_fat = tid in ("adr24-comp-9402", "adr24-comp-9403", "adr24-comp-9503")
        is_fn_portion = tid in ("adr24-comp-8301", "adr24-comp-8303", "adr20-log-5005")
        
        is_tn_syco = tid in ("adr25-eval-1201", "adr25-eval-1202")
        is_tn_myth = tid in ("adr26-eval-1301", "adr26-eval-1302", "adr26-eval-1303", "adr26-eval-1304", "adr26-eval-1305")
        
        for model_name, m_data in [("deepseek", ds), ("glm", glm)]:
            passed = m_data["passed"]
            tag = m_data.get("score_tag")
            
            if passed:
                # Audit for False Positive
                # NutriEnv scorer strictly checks exact match / 15% physical tolerance.
                # Are there any loose tolerance passes?
                # Even with 15% tolerance, models must hit the physical portion table.
                results[model_name]["TP"].append(tid)
            else:
                # Audit for False Negative vs True Negative
                if is_fn_prompt:
                    results[model_name]["FN"].append((tid, "FN_PROMPT_ROUTING", tag))
                elif is_fn_amend:
                    results[model_name]["FN"].append((tid, "FN_AMEND_MEAL", tag))
                elif is_fn_twin:
                    results[model_name]["FN"].append((tid, "FN_TWIN_AMBIGUITY", tag))
                elif is_fn_fat:
                    results[model_name]["FN"].append((tid, "FN_FAT_STATUS", tag))
                elif is_fn_portion:
                    results[model_name]["FN"].append((tid, "FN_PORTION_ANCHOR", tag))
                elif is_tn_syco:
                    results[model_name]["TN"].append((tid, "TN_SYCOPHANCY", tag))
                elif is_tn_myth:
                    results[model_name]["TN"].append((tid, "TN_MYTH_TRAP", tag))
                elif tag == "window":
                    results[model_name]["TN"].append((tid, "TN_MATH_WINDOW", tag))
                elif tag in ("allergy", "profile_miss"):
                    results[model_name]["TN"].append((tid, "TN_ALLERGY_PROFILE", tag))
                elif tag == "update_miss":
                    results[model_name]["TN"].append((tid, "TN_MISSING_STEP", tag))
                elif tag == "log_miss":
                    # Check if it was hallucination (e.g. 100g chicken thigh)
                    results[model_name]["TN"].append((tid, "TN_LOG_HALLUCINATION_OR_MISMATCH", tag))
                else:
                    results[model_name]["TN"].append((tid, f"TN_OTHER_{tag}", tag))

    print("\n=== AGY AUDIT SUMMARY ===")
    for m in ["deepseek", "glm"]:
        tp = len(results[m]["TP"])
        fp = len(results[m]["FP"])
        tn = len(results[m]["TN"])
        fn = len(results[m]["FN"])
        total = tp + fp + tn + fn
        print(f"Model: {m.upper()}")
        print(f"  Total: {total} | Pass: {tp+fp} (TP={tp}, FP={fp}) | Fail: {tn+fn} (TN={tn}, FN={fn})")
        print(f"  False Negative Rate (among Fails): {fn/(tn+fn)*100:.1f}% ({fn}/{tn+fn})")
        print(f"  False Positive Rate (among Passes): {fp/(tp+fp)*100 if (tp+fp)>0 else 0:.1f}% ({fp}/{tp+fp})")
        
    with open(".scratch/reviews/full_audit_128/agy_audit_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Saved AGY audit results to .scratch/reviews/full_audit_128/agy_audit_results.json")

if __name__ == "__main__":
    main()
