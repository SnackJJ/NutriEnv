"""Audit gap between resolve_portion default serving and FNDDS QNS (modifier 90000).

Outputs results to reports/qns-gap-audit.json.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import zipfile

from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import resolve_portion

ROOT = Path(__file__).resolve().parents[1]
SURVEY_ZIP_PATH = ROOT / "data" / "fdc" / "raw" / "survey.zip"
EXAM_SPLIT_PATH = ROOT / "data" / "splits" / "archive" / "v0.5-gold.json"
REPORT_OUTPUT_PATH = ROOT / "reports" / "qns-gap-audit.json"


def load_qns_table(zip_path: Path) -> dict[str, float]:
    """Load QNS (modifier 90000) gram weights by FDC ID from survey food_portion.csv."""
    qns_map: dict[str, float] = {}
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.endswith("food_portion.csv"):
                with z.open(name) as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                    for row in reader:
                        if row.get("modifier") == "90000":
                            gw = float(row.get("gram_weight") or 0.0)
                            if gw > 0:
                                qns_map[row["fdc_id"]] = gw
    return qns_map


def extract_gold_foods(gold_path: Path, catalog) -> tuple[set[str], dict[str, str], list[str]]:
    """Extract unique food IDs and slugs from v0.5-gold.json."""
    with open(gold_path, "r", encoding="utf-8") as f:
        gold_data = json.load(f)

    gold_slugs: set[str] = set()
    for item in gold_data.get("items", []):
        s0 = item.get("s0", {})
        for entry in s0.get("ledger", []):
            if "food_id" in entry:
                gold_slugs.add(entry["food_id"])
        oracle = item.get("oracle", {})
        if isinstance(oracle, dict):
            for entry in oracle.get("ledger_tail", []):
                if "food_id" in entry:
                    gold_slugs.add(entry["food_id"])
            plan = oracle.get("plan", {})
            if isinstance(plan, dict):
                for meal in plan.get("meals", []):
                    for entry in meal.get("items", []):
                        if "food_id" in entry:
                            gold_slugs.add(entry["food_id"])

    sorted_slugs = sorted(gold_slugs)
    fdc_to_slug: dict[str, str] = {}
    gold_fdc_ids: set[str] = set()

    for slug in sorted_slugs:
        cat_entry = catalog.get(slug)
        if cat_entry:
            fid = str(cat_entry.get("fdc_id") or cat_entry.get("id") or slug)
            fdc_to_slug[fid] = slug
            gold_fdc_ids.add(fid)
        else:
            gold_fdc_ids.add(slug)
            fdc_to_slug[slug] = slug

    return gold_fdc_ids, fdc_to_slug, sorted_slugs


def run_audit():
    print("Loading catalog...")
    catalog = load_catalog()
    total_catalog = len(catalog)

    print("Loading QNS table from survey.zip...")
    qns_map = load_qns_table(SURVEY_ZIP_PATH)
    total_qns = len(qns_map)

    print("Extracting gold foods from v0.5-gold.json...")
    gold_fdc_ids, gold_fdc_to_slug, gold_slug_list = extract_gold_foods(EXAM_SPLIT_PATH, catalog)

    matched_items = []
    foods_with_portions = 0
    foods_resolving_serving = 0
    foods_with_qns_in_catalog = 0

    for fid, entry in catalog.items():
        fid_str = str(fid)
        portions = entry.get("portions") or {}
        if not portions:
            continue
        foods_with_portions += 1

        qns = qns_map.get(fid_str)
        if qns is not None:
            foods_with_qns_in_catalog += 1

        name = entry.get("name", "")
        current_serving = resolve_portion(fid_str, f"a serving of {name}", catalog)
        if current_serving is not None:
            foods_resolving_serving += 1

        if current_serving is not None and qns is not None:
            gap = round(abs(current_serving - qns), 2)
            ratio = round(max(current_serving / qns, qns / current_serving), 4) if (qns > 0 and current_serving > 0) else None
            in_gold = fid_str in gold_fdc_ids
            matched_items.append({
                "food_id": fid_str,
                "name": name,
                "current_serving": current_serving,
                "qns": qns,
                "gap": gap,
                "ratio": ratio,
                "in_gold": in_gold,
            })

    # Sort rankings
    by_ratio = sorted(matched_items, key=lambda x: (x["ratio"] if x["ratio"] is not None else 0), reverse=True)
    by_gap = sorted(matched_items, key=lambda x: x["gap"], reverse=True)

    top_50_by_ratio = by_ratio[:50]
    top_50_by_gap = by_gap[:50]

    # Detailed audit for all 25 gold foods
    gold_foods_audit = []
    for slug in gold_slug_list:
        cat_entry = catalog.get(slug)
        if not cat_entry:
            gold_foods_audit.append({
                "slug": slug,
                "food_id": None,
                "name": None,
                "portions": {},
                "current_serving": None,
                "qns": None,
                "gap": None,
                "ratio": None,
                "in_gold": True,
                "data_source": "unknown",
                "notes": "Food not found in catalog",
            })
            continue

        fid = str(cat_entry.get("fdc_id") or cat_entry.get("id") or slug)
        name = cat_entry.get("name", "")
        portions = cat_entry.get("portions") or {}
        curr = resolve_portion(fid, f"a serving of {name}", catalog)
        qns_val = qns_map.get(fid)

        gap_val = round(abs(curr - qns_val), 2) if (curr is not None and qns_val is not None) else None
        rat_val = round(max(curr / qns_val, qns_val / curr), 4) if (curr is not None and qns_val is not None and qns_val > 0 and curr > 0) else None

        is_sr = len(fid) == 6 or fid.startswith("17") or fid.startswith("16")
        data_source = "sr_legacy" if is_sr else "fndds_survey"
        notes = []
        if curr is None and not portions:
            notes.append("Empty portions table (no serving)")
        elif curr is None:
            notes.append(f"No piece/slice/cup fallback in portions {list(portions.keys())}")
        elif curr == qns_val:
            notes.append("Exact match with QNS (0 gap)")
        elif gap_val is not None and rat_val is not None:
            notes.append(f"Gap {gap_val}g (ratio {rat_val:.2f}x)")

        if qns_val is None:
            notes.append(f"No QNS in FNDDS survey (source: {data_source})")

        gold_foods_audit.append({
            "slug": slug,
            "food_id": fid,
            "name": name,
            "portions": portions,
            "current_serving": curr,
            "qns": qns_val,
            "gap": gap_val,
            "ratio": rat_val,
            "in_gold": True,
            "data_source": data_source,
            "notes": "; ".join(notes),
        })

    # Summary metrics
    ratio_over_10 = sum(1 for x in matched_items if x["ratio"] is not None and x["ratio"] >= 10.0)
    ratio_over_5 = sum(1 for x in matched_items if x["ratio"] is not None and x["ratio"] >= 5.0)
    ratio_over_2 = sum(1 for x in matched_items if x["ratio"] is not None and x["ratio"] >= 2.0)
    ratio_exact_1 = sum(1 for x in matched_items if x["ratio"] is not None and x["ratio"] == 1.0)

    summary = {
        "total_catalog_foods": total_catalog,
        "foods_with_portions": foods_with_portions,
        "foods_resolving_serving": foods_resolving_serving,
        "foods_with_qns_in_catalog": foods_with_qns_in_catalog,
        "foods_with_both_serving_and_qns": len(matched_items),
        "gold_foods_total": len(gold_slug_list),
        "gold_foods_in_survey_with_qns": sum(1 for g in gold_foods_audit if g["qns"] is not None),
        "distribution": {
            "exact_match_ratio_1x": ratio_exact_1,
            "ratio_ge_2x": ratio_over_2,
            "ratio_ge_5x": ratio_over_5,
            "ratio_ge_10x": ratio_over_10,
        },
    }

    report = {
        "summary": summary,
        "top_50": top_50_by_ratio,
        "top_50_by_ratio": top_50_by_ratio,
        "top_50_by_gap": top_50_by_gap,
        "gold_foods": gold_foods_audit,
    }

    REPORT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nAudit completed. Output written to: {REPORT_OUTPUT_PATH}")
    print("\n" + "=" * 80)
    print("SUMMARY OF AUDIT RESULTS:")
    print(f"Total catalog foods:               {summary["total_catalog_foods"]}")
    print(f"Foods with portions:               {summary["foods_with_portions"]}")
    print(f"Foods resolving serving:           {summary["foods_resolving_serving"]}")
    print(f"Foods with survey QNS:             {summary["foods_with_qns_in_catalog"]}")
    print(f"Foods evaluated (serving + QNS):   {summary["foods_with_both_serving_and_qns"]}")
    print(f"  - Exact match (ratio 1.0x):      {ratio_exact_1} ({ratio_exact_1/len(matched_items)*100:.1f}%)")
    print(f"  - Ratio >= 2.0x:                 {ratio_over_2} ({ratio_over_2/len(matched_items)*100:.1f}%)")
    print(f"  - Ratio >= 5.0x:                 {ratio_over_5} ({ratio_over_5/len(matched_items)*100:.1f}%)")
    print(f"  - Ratio >= 10.0x:                {ratio_over_10} ({ratio_over_10/len(matched_items)*100:.1f}%)")
    print("=" * 80)
    print("\nTOP 10 FOODS WITH LARGEST RATIO GAP (Current Serving vs QNS):")
    print(f"{"#":<3} | {"Food ID":<8} | {"Name":<40} | {"Current":<8} | {"QNS":<8} | {"Gap":<8} | {"Ratio":<8} | {"In Gold"}")
    print("-" * 100)
    for idx, it in enumerate(top_50_by_ratio[:10], 1):
        nm = it["name"][:38]
        curr = f"{it["current_serving"]}g"
        qns_str = f"{it["qns"]}g"
        gap_str = f"{it["gap"]}g"
        rat_str = f"{it["ratio"]:.2f}x"
        gold_str = "YES" if it["in_gold"] else "no"
        print(f"{idx:<3} | {it["food_id"]:<8} | {nm:<40} | {curr:<8} | {qns_str:<8} | {gap_str:<8} | {rat_str:<8} | {gold_str}")

    print("\n" + "=" * 80)
    print("GOLD DATASET (25 FOODS) AUDIT:")
    print(f"{"Slug":<15} | {"Food ID":<8} | {"Current":<8} | {"QNS":<8} | {"Gap":<8} | {"Ratio":<8} | {"Notes"}")
    print("-" * 100)
    for g in gold_foods_audit:
        s = g["slug"]
        fid = g["food_id"] or "-"
        curr = f"{g["current_serving"]}g" if g["current_serving"] is not None else "None"
        qns_str = f"{g["qns"]}g" if g["qns"] is not None else "None"
        gap_str = f"{g["gap"]}g" if g["gap"] is not None else "-"
        rat_str = f"{g["ratio"]:.2f}x" if g["ratio"] is not None else "-"
        notes = g["notes"]
        print(f"{s:<15} | {fid:<8} | {curr:<8} | {qns_str:<8} | {gap_str:<8} | {rat_str:<8} | {notes}")
    print("=" * 80)


if __name__ == "__main__":
    run_audit()
