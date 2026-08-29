#!/usr/bin/env python3
"""NutriEnv ADR 0019 Pipeline: Pure Natural Speech Generation with Two-Tier Portion Resolution.

1. Free-form natural LLM speech generation (no rigid database column handcuffs).
2. Two-tier resolution architecture:
   - Tier 1: Deterministic `resolve_portion` table lookup (zero drift, 100% confidence).
   - Tier 2: Multi-Agent Vote Fallback (`vote_fndds_portion`, Base FNDDS Unit * Multiplier).
3. Produces `.scratch/v2-samples/samples.json` and interactive Review HTML dashboard.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path
from collections.abc import Mapping, Sequence

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.daily_windows import derive_profile_windows
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, Profile, WorldState
from nutrienv.bench.realize import Task
from nutrienv.bench.pipeline.roster import ROSTER, RosterPerson, profile_for, sample_roster_person
from nutrienv.bench.pipeline.sampler import sample_pools, spoken_display_name, FoodPool, PoolFood
from nutrienv.bench.pipeline.semantic_vote import vote_fndds_portion, FnddsVoteResult
from nutrienv.io.chat import complete_chat

DEFAULT_CATALOG_PATH = "data/fdc/catalog-v2.sqlite"
DEFAULT_OUT_DIR = Path(".scratch/v2-samples")
DEFAULT_HTML_REPORT = Path("reports/adr0019-samples-review.html")

FAMILIES = ("log", "evaluate", "recommend", "update", "composite")
VOTER_MODELS = ("qwen3.8-max", "qwen3.8-2.4t-a95b")


def _complete_llm(model_id: str, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
    """Call LLM via unified chat client."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return complete_chat(model_id, messages, temperature=temperature, max_tokens=300)


def _parse_json_payload(raw: str) -> dict | None:
    """Extract and parse JSON object from LLM response."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def _resolve_food_in_query(
    query: str,
    food_id: str,
    catalog: Mapping,
    *,
    enable_vote: bool = True,
    voter_models: tuple[str, ...] = VOTER_MODELS,
) -> dict:
    """Two-tier portion resolution for a food inside a query clause."""
    entry = catalog.get(food_id) or {}
    food_name = entry.get("name") or food_id
    spoken_name = spoken_display_name(catalog, food_id)

    # Tier 1: Deterministic resolution
    grams = resolve_portion(food_id, query, catalog)
    if grams is not None:
        return {
            "tier": "Tier-1 (Deterministic Rule)",
            "food_id": food_id,
            "food_name": food_name,
            "spoken_name": spoken_name,
            "grams": float(grams),
            "method": "rule_exact",
            "consensus": "100% Rule Match",
            "high_confidence": True,
            "needs_review": False,
            "voter_details": (),
        }

    # Tier 2: Multi-Agent Vote Fallback
    if enable_vote:
        voted = vote_fndds_portion(query, food_id, catalog, voter_models=voter_models)
        if voted.status == "estimated_by_vote" and voted.recommended_grams is not None:
            return {
                "tier": "Tier-2 (Multi-Agent Vote)",
                "food_id": food_id,
                "food_name": food_name,
                "spoken_name": spoken_name,
                "grams": float(voted.recommended_grams),
                "method": "vote_estimated",
                "consensus": voted.consensus,
                "high_confidence": voted.high_confidence,
                "needs_review": True,
                "voter_details": voted.voter_details,
            }

    return {
        "tier": "Failed",
        "food_id": food_id,
        "food_name": food_name,
        "spoken_name": spoken_name,
        "grams": None,
        "method": "unresolvable",
        "needs_review": True,
    }


def generate_log_sample(
    seed: int,
    catalog: Mapping,
    *,
    model_id: str = "qwen3.8-max",
    enable_vote: bool = True,
) -> dict | None:
    """Generate a natural Log meal entry using pure human dining speech."""
    person = sample_roster_person(seed)
    profile = profile_for(person)
    rng = random.Random(seed)
    pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=6)
    pool = pools[0]
    chosen_foods = rng.sample(list(pool.foods), k=rng.choice([1, 2]))

    food_descriptions = []
    for f in chosen_foods:
        spoken = spoken_display_name(catalog, f.food_id)
        food_descriptions.append(f'- id="{f.food_id}" name="{spoken}" ({f.name})')

    sys_prompt = (
        "You are writing a natural food diary entry that a real person would type in an everyday app (like MyFitnessPal/Reddit).\n"
        f"User Persona: {person.persona}, Diet Style: {person.diet_style}.\n"
        "Guidelines:\n"
        "- Speak naturally using everyday dining portion words (e.g. 'a plate of...', 'a bowl of...', 'two slices of...', 'a piece of...', 'a burrito', 'a tablespoon of...').\n"
        "- NEVER use 'a cup of' for burgers, patties, sandwiches, or plated meals.\n"
        "- Return ONLY a JSON object with schema: {\"query\": \"<natural single-sentence diary log>\", \"foods\": [\"<food_id>\", ...]}"
    )
    user_prompt = (
        f"Compose one plausible meal from these available foods:\n"
        + "\n".join(food_descriptions)
        + "\n\nJSON output only:"
    )

    for _attempt in range(2):
        raw = _complete_llm(model_id, sys_prompt, user_prompt)
        data = _parse_json_payload(raw)
        if not data or "query" not in data or "foods" not in data:
            continue
        query = str(data["query"]).strip()
        food_ids = [str(fid) for fid in data["foods"] if str(fid) in catalog]
        if not food_ids:
            continue

        resolutions = []
        ledger_rows = []
        all_resolved = True
        for fid in food_ids:
            res = _resolve_food_in_query(query, fid, catalog, enable_vote=enable_vote)
            resolutions.append(res)
            if res.get("grams") is not None and res["grams"] > 0:
                ledger_rows.append(LedgerRow(fid, res["grams"], "today-lunch"))
            else:
                all_resolved = False

        if all_resolved and ledger_rows:
            task = Task(
                id=f"adr19-log-{seed:04d}",
                family="log",
                query=query,
                s0=WorldState(profile=profile, ledger=[], catalog=catalog),
                oracle=WorldState(profile=profile, ledger=ledger_rows, catalog=catalog),
                persona=person.persona,
            )
            return {
                "task": task,
                "person": person,
                "resolutions": resolutions,
                "raw_response": raw,
            }
    return None


def generate_eval_sample(
    seed: int,
    catalog: Mapping,
    *,
    model_id: str = "qwen3.8-max",
    enable_vote: bool = True,
) -> dict | None:
    """Generate a natural Evaluate query asking to evaluate a planned meal."""
    person = sample_roster_person(seed)
    profile = profile_for(person)
    rng = random.Random(seed)
    pools = sample_pools(catalog, seed=seed, family="evaluate", n_pools=1, pool_size=6)
    pool = pools[0]
    chosen_foods = rng.sample(list(pool.foods), k=rng.choice([1, 2]))

    food_descriptions = []
    target_plan = []
    for f in chosen_foods:
        spoken = spoken_display_name(catalog, f.food_id)
        entry = catalog.get(f.food_id) or {}
        portions = entry.get("portions") or {}
        default_grams = portions.get("qns") or portions.get("cup") or portions.get("piece") or 150.0
        target_plan.append({"food_id": f.food_id, "grams": float(default_grams)})
        food_descriptions.append(f'- id="{f.food_id}" name="{spoken}" ({f.name})')

    sys_prompt = (
        "You write a natural user query asking the nutritional assistant to evaluate a planned meal for lunch.\n"
        f"User Persona: {person.persona}, Diet Style: {person.diet_style}.\n"
        "Guidelines:\n"
        "- Example phrasing: 'Evaluate this lunch: a plate of pasta with sauce and a piece of burrito.'\n"
        "- Speak foods with natural household measures (a plate of, a bowl of, a slice of, a patty, a piece of).\n"
        "- Return ONLY a JSON object: {\"query\": \"<evaluation query>\", \"foods\": [\"<food_id>\", ...]}"
    )
    user_prompt = (
        f"Write an evaluation request naming these planned foods:\n"
        + "\n".join(food_descriptions)
        + "\n\nJSON output only:"
    )

    for _attempt in range(2):
        raw = _complete_llm(model_id, sys_prompt, user_prompt)
        data = _parse_json_payload(raw)
        if not data or "query" not in data or "foods" not in data:
            continue
        query = str(data["query"]).strip()
        food_ids = [str(fid) for fid in data["foods"] if str(fid) in catalog]
        if not food_ids:
            continue

        resolutions = []
        plan_rows = []
        all_resolved = True
        for fid in food_ids:
            res = _resolve_food_in_query(query, fid, catalog, enable_vote=enable_vote)
            resolutions.append(res)
            if res.get("grams") is not None and res["grams"] > 0:
                plan_rows.append(LedgerRow(fid, res["grams"], "today-lunch"))
            else:
                all_resolved = False

        if all_resolved and plan_rows:
            task = Task(
                id=f"adr19-eval-{seed:04d}",
                family="evaluate",
                query=query,
                s0=WorldState(profile=profile, ledger=[], catalog=catalog),
                oracle=WorldState(profile=profile, ledger=plan_rows, catalog=catalog),
                persona=person.persona,
            )
            return {
                "task": task,
                "person": person,
                "resolutions": resolutions,
                "raw_response": raw,
            }
    return None


def generate_rec_sample(seed: int, catalog: Mapping) -> dict:
    """Generate a Recommend query."""
    person = sample_roster_person(seed)
    profile = profile_for(person)
    occasions = ("breakfast", "lunch", "dinner")
    occ = occasions[seed % len(occasions)]
    templates = [
        f"What should I eat for {occ}?",
        f"Give me a healthy meal plan for {occ}.",
        f"Recommend a {occ} that fits my daily targets.",
    ]
    query = templates[seed % len(templates)]
    task = Task(
        id=f"adr19-rec-{seed:04d}",
        family="recommend",
        query=query,
        s0=WorldState(profile=profile, ledger=[], catalog=catalog),
        oracle=WorldState(profile=profile, ledger=[], catalog=catalog),
        persona=person.persona,
    )
    return {"task": task, "person": person, "resolutions": []}


def generate_upd_sample(seed: int, catalog: Mapping) -> dict:
    """Generate an Update query."""
    person = sample_roster_person(seed)
    profile = profile_for(person)
    upd_types = [
        f"Add milk to my allergies.",
        f"I weigh {person.weight_kg + 2:g} kg now. Update my weight.",
        f"Add peanut to my allergies.",
    ]
    query = upd_types[seed % len(upd_types)]
    task = Task(
        id=f"adr19-upd-{seed:04d}",
        family="update",
        query=query,
        s0=WorldState(profile=profile, ledger=[], catalog=catalog),
        oracle=WorldState(profile=profile, ledger=[], catalog=catalog),
        persona=person.persona,
    )
    return {"task": task, "person": person, "resolutions": []}


def generate_comp_sample(
    seed: int,
    catalog: Mapping,
    *,
    model_id: str = "qwen3.8-max",
    enable_vote: bool = True,
) -> dict | None:
    """Generate a Composite multi-step task (Log meal then ask for next meal)."""
    log_part = generate_log_sample(seed, catalog, model_id=model_id, enable_vote=enable_vote)
    if not log_part:
        return None
    person = log_part["person"]
    profile = profile_for(person)
    log_task = log_part["task"]
    log_query = log_task.query
    comp_query = f"{log_query.rstrip('.')}, so what should I eat next?"
    
    task = Task(
        id=f"adr19-comp-{seed:04d}",
        family="composite",
        query=comp_query,
        s0=WorldState(profile=profile, ledger=[], catalog=catalog),
        oracle=log_task.oracle,
        persona=person.persona,
    )
    return {
        "task": task,
        "person": person,
        "resolutions": log_part["resolutions"],
        "raw_response": log_part.get("raw_response", ""),
    }


def render_html_review_dashboard(results: dict[str, list[dict]], out_file: Path) -> None:
    """Render interactive HTML Review Dashboard for generated samples."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    cards_html = []

    for family, items in results.items():
        cards_html.append(f"""
        <div class="family-section">
            <h2 class="family-title">{family.upper()} ({len(items)} items)</h2>
            <div class="cards-grid">
        """)
        for item in items:
            t = item["task"]
            p = item["person"]
            resolutions = item.get("resolutions", [])
            
            res_rows = []
            for r in resolutions:
                tier_badge = (
                    '<span class="badge tier-1">🟢 Tier-1 Rule</span>'
                    if "Tier-1" in r.get("tier", "")
                    else '<span class="badge tier-2">🟡 Tier-2 Vote</span>'
                )
                voter_info = ""
                if r.get("voter_details"):
                    voter_info = "<div class='voter-box'><strong>Voter Consensus:</strong> " + r.get("consensus", "") + "<ul>"
                    for vd in r["voter_details"]:
                        if "grams" in vd:
                            voter_info += f"<li><code>{vd.get('model')}</code>: {vd.get('base_unit')} × {vd.get('multiplier')} = <strong>{vd.get('grams')}g</strong> <em>({vd.get('rationale')})</em></li>"
                    voter_info += "</ul></div>"

                res_rows.append(f"""
                <tr>
                    <td><code>{r.get('food_id')}</code></td>
                    <td><strong>{r.get('spoken_name')}</strong></td>
                    <td>{tier_badge}</td>
                    <td><strong>{r.get('grams')} g</strong></td>
                </tr>
                {f"<tr><td colspan='4'>{voter_info}</td></tr>" if voter_info else ""}
                """)

            res_table = (
                f"""
                <table class="res-table">
                    <thead><tr><th>Food ID</th><th>Food Name</th><th>Resolution Tier</th><th>Resolved Grams</th></tr></thead>
                    <tbody>{''.join(res_rows)}</tbody>
                </table>
                """
                if res_rows
                else "<p class='no-foods'>No food portion binding required for this task type.</p>"
            )

            oracle_desc = ""
            if t.oracle and t.oracle.ledger:
                label = "Evaluated Plan" if t.family == "evaluate" else "Oracle Ledger"
                oracle_desc = f"<strong>{label}:</strong> " + ", ".join(f"{r.food_id}: {r.grams:g}g" for r in t.oracle.ledger)

            cards_html.append(f"""
            <div class="card">
                <div class="card-header">
                    <span class="task-id">{t.id}</span>
                    <span class="persona-tag">{p.persona} | {p.diet_style}</span>
                    <span class="user-meta">{p.sex}, {p.age_y}y, {p.weight_kg}kg, {p.activity}</span>
                </div>
                <div class="card-body">
                    <div class="query-box">
                        <span class="query-label">User Query:</span>
                        <p class="query-text">"{t.query}"</p>
                    </div>
                    <div class="resolution-container">
                        {res_table}
                    </div>
                    {f"<div class='oracle-box'>{oracle_desc}</div>" if oracle_desc else ""}
                </div>
                <div class="card-footer">
                    <button class="btn approve-btn" onclick="this.innerText='✓ Approved'; this.classList.add('approved');">Approve for Gold Split</button>
                    <button class="btn flag-btn" onclick="this.innerText='Flagged for Review'; this.classList.add('flagged');">Flag</button>
                </div>
            </div>
            """)
        cards_html.append("</div></div>")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>NutriEnv ADR 0019 Review Dashboard</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
    h1 {{ font-size: 28px; margin-bottom: 8px; color: #38bdf8; }}
    .subtitle {{ color: #94a3b8; margin-bottom: 32px; font-size: 15px; }}
    .family-title {{ font-size: 20px; color: #e2e8f0; border-bottom: 2px solid #334155; padding-bottom: 8px; margin-top: 32px; }}
    .cards-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(540px, 1fr)); gap: 20px; margin-top: 16px; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; }}
    .card-header {{ background: #0f172a; padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }}
    .task-id {{ font-family: monospace; font-weight: bold; color: #38bdf8; }}
    .persona-tag {{ background: #0284c7; color: white; padding: 3px 8px; border-radius: 4px; font-size: 12px; }}
    .user-meta {{ color: #94a3b8; font-size: 13px; }}
    .card-body {{ padding: 16px; flex: 1; }}
    .query-box {{ background: #0f172a; padding: 12px; border-radius: 6px; margin-bottom: 14px; border-left: 4px solid #38bdf8; }}
    .query-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; font-weight: bold; }}
    .query-text {{ margin: 6px 0 0 0; font-size: 15px; color: #f1f5f9; line-height: 1.4; }}
    .res-table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }}
    .res-table th, .res-table td {{ padding: 8px; text-align: left; border-bottom: 1px solid #334155; }}
    .res-table th {{ color: #94a3b8; font-weight: 600; }}
    .badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }}
    .tier-1 {{ background: #065f46; color: #34d399; }}
    .tier-2 {{ background: #854d0e; color: #fde047; }}
    .voter-box {{ background: #172554; border: 1px solid #1e3a8a; border-radius: 6px; padding: 8px; margin: 4px 0; font-size: 12px; color: #bfdbfe; }}
    .voter-box ul {{ margin: 4px 0; padding-left: 18px; }}
    .oracle-box {{ margin-top: 12px; padding: 8px; background: #0f172a; border-radius: 4px; font-size: 13px; color: #cbd5e1; }}
    .card-footer {{ padding: 12px 16px; background: #0f172a; border-top: 1px solid #334155; display: flex; gap: 10px; justify-content: flex-end; }}
    .btn {{ padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500; border: none; }}
    .approve-btn {{ background: #10b981; color: white; }}
    .approve-btn.approved {{ background: #059669; }}
    .flag-btn {{ background: #475569; color: #e2e8f0; }}
    .flag-btn.flagged {{ background: #b91c1c; }}
    .no-foods {{ color: #64748b; font-style: italic; font-size: 13px; }}
</style>
</head>
<body>
    <h1>NutriEnv ADR 0019 Live Review Dashboard</h1>
    <div class="subtitle">Two-Tier Portion Resolution: Free-form Natural Speech &rarr; Tier-1 Deterministic Lookup &rarr; Tier-2 Multi-Agent Vote Fallback</div>
    {"".join(cards_html)}
</body>
</html>
"""
    out_file.write_text(html_content, encoding="utf-8")
    print(f"Interactive Review Dashboard written to {out_file}")


def main():
    parser = argparse.ArgumentParser(description="NutriEnv ADR 0019 Pipeline Generator")
    parser.add_argument("--count", type=int, default=2, help="Samples per family")
    parser.add_argument("--models", type=str, default="qwen3.8-max", help="Model ID")
    parser.add_argument("--catalog", type=str, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--html", type=str, default=str(DEFAULT_HTML_REPORT))
    parser.add_argument("--no-vote", action="store_true", help="Disable Tier 2 Vote Fallback")
    args = parser.parse_args()

    catalog = load_catalog(Path(args.catalog))
    enable_vote = not args.no_vote
    results = {"log": [], "evaluate": [], "recommend": [], "update": [], "composite": []}

    print(f"=== NutriEnv ADR 0019 Pipeline Generation (count={args.count}, model={args.models}) ===")
    
    # 1. Log
    seed = 0
    while len(results["log"]) < args.count and seed < 20:
        item = generate_log_sample(seed, catalog, model_id=args.models, enable_vote=enable_vote)
        if item:
            results["log"].append(item)
            print(f"  [Log {len(results['log'])}/{args.count}] seed={seed} -> \"{item['task'].query}\"")
        seed += 1

    # 2. Evaluate
    seed = 0
    while len(results["evaluate"]) < args.count and seed < 20:
        item = generate_eval_sample(seed, catalog, model_id=args.models, enable_vote=enable_vote)
        if item:
            results["evaluate"].append(item)
            print(f"  [Eval {len(results['evaluate'])}/{args.count}] seed={seed} -> \"{item['task'].query}\"")
        seed += 1

    # 3. Recommend
    for i in range(args.count):
        item = generate_rec_sample(i, catalog)
        results["recommend"].append(item)
        print(f"  [Rec {len(results['recommend'])}/{args.count}] seed={i} -> \"{item['task'].query}\"")

    # 4. Update
    for i in range(args.count):
        item = generate_upd_sample(i, catalog)
        results["update"].append(item)
        print(f"  [Upd {len(results['update'])}/{args.count}] seed={i} -> \"{item['task'].query}\"")

    # 5. Composite
    seed = 0
    while len(results["composite"]) < args.count and seed < 20:
        item = generate_comp_sample(seed, catalog, model_id=args.models, enable_vote=enable_vote)
        if item:
            results["composite"].append(item)
            print(f"  [Comp {len(results['composite'])}/{args.count}] seed={seed} -> \"{item['task'].query}\"")
        seed += 1

    # Write HTML Dashboard
    render_html_review_dashboard(results, Path(args.html))
    print(f"\nSuccessfully generated {sum(len(v) for v in results.values())} ADR 0019 samples across 5 families.")


if __name__ == "__main__":
    main()
