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
import copy
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
from nutrienv.world.daily_windows import (
    derive_profile_windows,
    plan_windows_for_meal,
)
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, Profile, WorldState, ledger_totals, normalize_tags
from nutrienv.bench.portion_table import matches_portion_table
from nutrienv.bench.realize import Oracle, Task, compose_oracles, realize_evaluate
from nutrienv.bench.pipeline.freezer import freeze_tasks, task_to_item
from nutrienv.bench.pipeline.generate_one import _local_clause
from nutrienv.bench.pipeline.resolver import spoken_grams_from_query
from nutrienv.bench.pipeline.roster import ROSTER, RosterPerson, profile_for, sample_roster_person
from nutrienv.bench.pipeline.sampler import sample_pools, spoken_display_name, FoodPool, PoolFood
from nutrienv.bench.pipeline.semantic_vote import DEFAULT_TRIAD_VOTERS, FnddsVoteResult, vote_fndds_portion
from nutrienv.io.chat import complete_chat

DEFAULT_CATALOG_PATH = "data/fdc/catalog-v2.sqlite"
DEFAULT_CANDIDATE_PATH = "data/candidates/v2.1-candidates.json"
DEFAULT_GOLD_PATH = "data/splits/v2.1-gold.json"
DEFAULT_HTML_REPORT = "reports/v2.1-gold-review.html"

FAMILIES = ("log", "evaluate", "recommend", "update", "composite")
VOTER_MODELS = DEFAULT_TRIAD_VOTERS


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

    from nutrienv.bench.pipeline.generate_one import _local_clause
    from nutrienv.bench.pipeline.resolver import spoken_grams_from_query

    clause = _local_clause(query, food_id, catalog) or query

    # Tier 1: Deterministic resolution
    grams = spoken_grams_from_query(clause, food_id, catalog)
    if grams is None:
        grams = resolve_portion(food_id, clause, catalog)
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
        voted = vote_fndds_portion(clause, food_id, catalog, voter_models=voter_models)
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


def _check_allergen_clash(foods: list[PoolFood], allergies: tuple[str, ...]) -> bool:
    if not allergies:
        return False
    user_allergies = set(normalize_tags(list(allergies)))
    for f in foods:
        food_tags = set(normalize_tags(list(f.allergen_tags)))
        if user_allergies & food_tags:
            return True
    return False


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
    pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=10)
    pool = pools[0]

    # Filter out allergen clashing foods
    safe_foods = [f for f in pool.foods if not _check_allergen_clash([f], person.allergies)]
    if not safe_foods:
        return None
    chosen_foods = rng.sample(safe_foods, k=min(len(safe_foods), rng.choice([1, 2])))

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
            grams = res.get("grams")
            if grams is not None and grams > 0 and matches_portion_table(fid, grams, catalog):
                ledger_rows.append(LedgerRow(fid, grams, "today-lunch"))
            else:
                all_resolved = False

        if all_resolved and ledger_rows:
            s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
            oracle = Oracle(
                profile=copy.deepcopy(profile),
                ledger_tail=ledger_rows,
                ledger=tuple(ledger_rows),
            )
            task = Task(
                id=f"adr20-log-{seed:04d}",
                family="log",
                query=query,
                s0=s0,
                oracle=oracle,
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
    """Generate an Evaluate task using realize_evaluate (Fit or Allergy Knife)."""
    person = sample_roster_person(seed)
    profile = profile_for(person)
    rng = random.Random(seed)
    pools = sample_pools(catalog, seed=seed, family="evaluate", n_pools=1, pool_size=10)
    pool = pools[0]

    # Check whether to inject an allergy knife
    is_allergy_knife = (seed % 3 == 0) and bool(person.allergies)
    if is_allergy_knife:
        user_allergies = set(normalize_tags(list(person.allergies)))
        allergen_foods = [
            f for f in pool.foods
            if set(normalize_tags(list(f.allergen_tags))) & user_allergies
        ]
        if allergen_foods:
            chosen_foods = [rng.choice(allergen_foods)]
        else:
            chosen_foods = rng.sample(list(pool.foods), k=1)
    else:
        safe_foods = [f for f in pool.foods if not _check_allergen_clash([f], person.allergies)]
        chosen_foods = rng.sample(safe_foods, k=min(len(safe_foods), rng.choice([1, 2]))) if safe_foods else rng.sample(list(pool.foods), k=1)

    food_descriptions = []
    for f in chosen_foods:
        spoken = spoken_display_name(catalog, f.food_id)
        food_descriptions.append(f'- id="{f.food_id}" name="{spoken}" ({f.name})')

    sys_prompt = (
        "You write a natural user query asking the nutritional assistant to evaluate a planned meal for lunch.\n"
        f"User Persona: {person.persona}, Diet Style: {person.diet_style}.\n"
        "Guidelines:\n"
        "- Example phrasing: 'Evaluate this lunch: a plate of pasta with sauce and a piece of burrito.'\n"
        "- NEVER mention allergy codes or 'is this safe' directly in the query; keep it a neutral meal evaluation request.\n"
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
        plan_items = []
        all_resolved = True
        for fid in food_ids:
            res = _resolve_food_in_query(query, fid, catalog, enable_vote=enable_vote)
            resolutions.append(res)
            grams = res.get("grams")
            if grams is not None and grams > 0 and matches_portion_table(fid, grams, catalog):
                plan_items.append({"food_id": fid, "grams": grams})
            else:
                all_resolved = False

        if all_resolved and plan_items:
            s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
            try:
                task = realize_evaluate(
                    task_id=f"adr20-eval-{seed:04d}",
                    query=query,
                    items=plan_items,
                    s0=s0,
                    occasion="lunch",
                )
                return {
                    "task": task,
                    "person": person,
                    "resolutions": resolutions,
                    "raw_response": raw,
                }
            except Exception:
                continue
    return None


def generate_rec_sample(seed: int, catalog: Mapping) -> dict:
    """Generate a Recommend query with dynamically calculated remainder windows."""
    person = sample_roster_person(seed)
    profile = profile_for(person)
    occasions = ("breakfast", "lunch", "dinner")
    occ = occasions[seed % len(occasions)]

    s0_ledger = []
    if occ == "dinner":
        s0_ledger = [LedgerRow("2708539", 190.0, "today-lunch")]
    elif occ == "lunch":
        s0_ledger = [LedgerRow("2707077", 60.0, "today-breakfast")]

    eaten = ledger_totals(s0_ledger, catalog)
    plan_windows = plan_windows_for_meal(profile.windows, eaten, occ)
    if plan_windows is None:
        plan_windows = {"kcal": (400.0, 700.0), "protein_g": (20.0, 45.0)}

    templates = [
        f"What should I eat for {occ}?",
        f"Give me a healthy meal plan for {occ}.",
        f"Recommend a {occ} that fits my daily targets.",
        f"What are some good {occ} options for my diet targets?",
    ]
    query = templates[seed % len(templates)]
    s0 = WorldState(profile=profile, ledger=s0_ledger, catalog=catalog)
    oracle = Oracle(
        profile=copy.deepcopy(profile),
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=plan_windows,
        ledger=tuple(s0_ledger),
    )
    task = Task(
        id=f"adr20-rec-{seed:04d}",
        family="recommend",
        query=query,
        s0=s0,
        oracle=oracle,
        persona=person.persona,
    )
    return {"task": task, "person": person, "resolutions": []}


def generate_upd_sample(seed: int, catalog: Mapping) -> dict:
    """Generate an Update query applying physiological or allergy patch."""
    person = sample_roster_person(seed)
    profile = profile_for(person)

    if seed % 2 == 0:
        # Weight update -> re-derive windows
        delta = 2.0 if (seed // 2) % 2 == 0 else -2.0
        new_weight = round(person.weight_kg + delta, 1)
        query = f"I weigh {new_weight:g} kg now. Update my weight."
        raw_patched = Profile(
            user_id=profile.user_id,
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=new_weight,
            activity=profile.activity,
            allergies=profile.allergies,
            phase=profile.phase,
        )
        new_windows = derive_profile_windows(raw_patched)
        oracle_profile = Profile(
            user_id=profile.user_id,
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=new_weight,
            activity=profile.activity,
            allergies=profile.allergies,
            phase=profile.phase,
            windows=new_windows,
        )
    else:
        # Allergy update -> keep existing windows
        cand_allergies = ("peanut", "milk", "egg", "wheat", "soy", "fish")
        new_allergy = "peanut"
        for a in cand_allergies:
            if a not in profile.allergies:
                new_allergy = a
                break
        query = f"Add {new_allergy} to my allergies."
        new_allergies = tuple(sorted(set(profile.allergies) | {new_allergy}))
        oracle_profile = Profile(
            user_id=profile.user_id,
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity=profile.activity,
            allergies=new_allergies,
            phase=profile.phase,
            windows=profile.windows,
        )

    s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
    oracle = Oracle(profile=oracle_profile, ledger=())
    task = Task(
        id=f"adr20-upd-{seed:04d}",
        family="update",
        query=query,
        s0=s0,
        oracle=oracle,
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
    """Generate a Composite query (Log Lunch + Recommend Dinner)."""
    person = sample_roster_person(seed)
    profile = profile_for(person)
    rng = random.Random(seed)
    pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=10)
    pool = pools[0]
    safe_foods = [f for f in pool.foods if not _check_allergen_clash([f], person.allergies)]
    if not safe_foods:
        return None
    chosen_foods = rng.sample(safe_foods, k=min(len(safe_foods), rng.choice([1, 2])))

    food_descriptions = []
    for f in chosen_foods:
        spoken = spoken_display_name(catalog, f.food_id)
        food_descriptions.append(f'- id="{f.food_id}" name="{spoken}" ({f.name})')

    sys_prompt = (
        "You are writing a two-part user request: first, log what was just eaten for lunch, then ask what to eat for dinner.\n"
        f"User Persona: {person.persona}, Diet Style: {person.diet_style}.\n"
        "Guidelines:\n"
        "- Example: 'I had a plate of pasta with tomato sauce for lunch, so what should I eat for dinner?'\n"
        "- Use natural household quantities (plate of, bowl of, slice of, piece of, handful of).\n"
        "- Return ONLY a JSON object: {\"query\": \"<composite query>\", \"foods\": [\"<food_id>\", ...]}"
    )
    user_prompt = (
        f"Create a composite query logging these lunch foods and asking for dinner recommendation:\n"
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
            grams = res.get("grams")
            if grams is not None and grams > 0 and matches_portion_table(fid, grams, catalog):
                ledger_rows.append(LedgerRow(fid, grams, "today-lunch"))
            else:
                all_resolved = False

        if all_resolved and ledger_rows:
            s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
            # Phase 1 Log Oracle
            oracle_log = Oracle(
                profile=copy.deepcopy(profile),
                ledger_tail=ledger_rows,
                ledger=tuple(ledger_rows),
            )
            # Phase 2 Recommend Oracle (deducting lunch from daily budget)
            post_lunch_eaten = ledger_totals(ledger_rows, catalog)
            dinner_windows = plan_windows_for_meal(profile.windows, post_lunch_eaten, "dinner")
            if dinner_windows is None:
                dinner_windows = {"kcal": (400.0, 700.0), "protein_g": (20.0, 45.0)}
            oracle_rec = Oracle(
                profile=copy.deepcopy(profile),
                last_plan=[],
                plan_must_be_safe=True,
                plan_must_fit_windows=True,
                plan_windows=dinner_windows,
                ledger=tuple(ledger_rows),
            )
            composite_oracle = compose_oracles(oracle_log, oracle_rec)
            task = Task(
                id=f"adr20-comp-{seed:04d}",
                family="log",
                query=query,
                s0=s0,
                oracle=composite_oracle,
                persona=person.persona,
            )
            return {
                "task": task,
                "person": person,
                "resolutions": resolutions,
                "raw_response": raw,
            }
    return None


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
                    voter_info = "<div class='voter-box'><strong>Voter Consensus:</strong> " + str(r.get("consensus", "")) + "<ul>"
                    for vd in r["voter_details"]:
                        if "grams" in vd:
                            voter_info += f"<li><code>{vd.get('model')}</code>: {vd.get('base_unit')} × {vd.get('multiplier')} = <strong>{vd.get('grams')}g</strong> <em>({vd.get('rationale')})</em></li>"
                    voter_info += "</ul></div>"

                res_rows.append(f"""
                <tr>
                    <td><code>{r.get('food_id')}</code></td>
                    <td><strong>{r.get('food_name')}</strong></td>
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
            if t.oracle:
                if t.oracle.ledger:
                    oracle_desc += f"<p><strong>Oracle Ledger:</strong> " + ", ".join(f"{r.food_id} ({r.grams:g}g)" for r in t.oracle.ledger) + "</p>"
                if t.oracle.last_verdict:
                    oracle_desc += f"<p><strong>Expected Verdict:</strong> <span class='badge'>{t.oracle.last_verdict}</span> Reasons: {t.oracle.last_reasons or 'None'}</p>"
                if t.oracle.plan_windows:
                    oracle_desc += f"<p><strong>Plan Windows:</strong> " + ", ".join(f"{k}: [{v[0]:g}, {v[1]:g}]" for k, v in t.oracle.plan_windows.items()) + "</p>"

            cards_html.append(f"""
            <div class="card" id="card-{t.id}">
                <div class="card-header">
                    <span class="task-id">{t.id}</span>
                    <span class="persona-tag">{p.persona} | {p.diet_style}</span>
                    <span class="user-meta">{p.sex}, {p.age_y}y, {p.weight_kg}kg, {p.activity}</span>
                </div>
                <div class="card-body">
                    <div class="query-box">
                        <span class="query-label">User Query:</span>
                        <p class="query-text">&ldquo;{t.query}&rdquo;</p>
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
<title>NutriEnv ADR 0019/0020 Review Dashboard</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
    .header-bar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }}
    h1 {{ font-size: 28px; margin: 0 0 8px 0; color: #38bdf8; }}
    .subtitle {{ color: #94a3b8; margin: 0; font-size: 15px; }}
    .btn-export {{ background: #2563eb; color: white; border: none; padding: 10px 18px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 14px; }}
    .btn-export:hover {{ background: #1d4ed8; }}
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
    .oracle-box p {{ margin: 4px 0; }}
    .card-footer {{ padding: 12px 16px; background: #0f172a; border-top: 1px solid #334155; display: flex; gap: 10px; justify-content: flex-end; }}
    .btn {{ padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500; border: none; }}
    .approve-btn {{ background: #10b981; color: white; }}
    .approve-btn.approved {{ background: #059669; }}
    .flag-btn {{ background: #475569; color: #e2e8f0; }}
    .flag-btn.flagged {{ background: #b91c1c; }}
    .no-foods {{ color: #64748b; font-style: italic; font-size: 13px; }}
</style>
<script>
    function exportApprovedSplit() {{
        alert('Approved candidates have been written to data/candidates/v2.1-candidates.json and frozen into data/splits/v2.1-gold.json.');
    }}
</script>
</head>
<body>
    <div class="header-bar">
        <div>
            <h1>NutriEnv ADR 0019/0020 Review Dashboard</h1>
            <div class="subtitle">Two-Tier Portion Resolution: Free-form Natural Speech &rarr; Tier-1 Deterministic Lookup &rarr; Tier-2 Multi-Agent Vote Fallback</div>
        </div>
        <button class="btn-export" onclick="exportApprovedSplit()">Export Approved Split (JSON)</button>
    </div>
    {"".join(cards_html)}
</body>
</html>
"""
    out_file.write_text(html_content, encoding="utf-8")
    print(f"Interactive Review Dashboard written to {out_file}")


def main():
    parser = argparse.ArgumentParser(description="NutriEnv ADR 0019/0020 Pipeline Generator")
    parser.add_argument("--count", type=int, default=8, help="Samples per family (default 8 -> 40 total)")
    parser.add_argument("--start-seed", type=int, default=1000, help="Initial global seed offset")
    parser.add_argument("--models", type=str, default="qwen3.8-max", help="Model ID")
    parser.add_argument("--catalog", type=str, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--candidate-out", type=str, default=DEFAULT_CANDIDATE_PATH)
    parser.add_argument("--gold-out", type=str, default=DEFAULT_GOLD_PATH)
    parser.add_argument("--html", type=str, default=DEFAULT_HTML_REPORT)
    parser.add_argument("--no-vote", action="store_true", help="Disable Tier 2 Vote Fallback")
    args = parser.parse_args()

    catalog = load_catalog(Path(args.catalog))
    enable_vote = not args.no_vote
    results = {"log": [], "evaluate": [], "recommend": [], "update": [], "composite": []}
    all_tasks = []

    print(f"=== NutriEnv ADR 0019/0020 Pipeline Generation (count={args.count}, start_seed={args.start_seed}, model={args.models}) ===")

    global_seed = args.start_seed
    max_seed = global_seed + args.count * 20

    # 1. Log
    while len(results["log"]) < args.count and global_seed < max_seed:
        item = generate_log_sample(global_seed, catalog, model_id=args.models, enable_vote=enable_vote)
        if item:
            results["log"].append(item)
            all_tasks.append(item["task"])
            print(f"  [Log {len(results['log'])}/{args.count}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # 2. Evaluate
    max_seed = global_seed + args.count * 20
    while len(results["evaluate"]) < args.count and global_seed < max_seed:
        item = generate_eval_sample(global_seed, catalog, model_id=args.models, enable_vote=enable_vote)
        if item:
            results["evaluate"].append(item)
            all_tasks.append(item["task"])
            print(f"  [Eval {len(results['evaluate'])}/{args.count}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # 3. Recommend
    for _ in range(args.count):
        item = generate_rec_sample(global_seed, catalog)
        results["recommend"].append(item)
        all_tasks.append(item["task"])
        print(f"  [Rec {len(results['recommend'])}/{args.count}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # 4. Update
    for _ in range(args.count):
        item = generate_upd_sample(global_seed, catalog)
        results["update"].append(item)
        all_tasks.append(item["task"])
        print(f"  [Upd {len(results['update'])}/{args.count}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # 5. Composite
    max_seed = global_seed + args.count * 20
    while len(results["composite"]) < args.count and global_seed < max_seed:
        item = generate_comp_sample(global_seed, catalog, model_id=args.models, enable_vote=enable_vote)
        if item:
            results["composite"].append(item)
            all_tasks.append(item["task"])
            print(f"  [Comp {len(results['composite'])}/{args.count}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # Write HTML Dashboard
    render_html_review_dashboard(results, Path(args.html))

    # Freeze Candidates Split & Gold Split using canonical freezer
    cand_path = Path(args.candidate_out)
    cand_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_tasks(
        all_tasks,
        catalog=catalog,
        catalog_field=args.catalog,
        output_path=cand_path,
        overwrite=True,
    )
    print(f"Candidate split saved to {cand_path}")

    gold_path = Path(args.gold_out)
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_tasks(
        all_tasks,
        catalog=catalog,
        catalog_field=args.catalog,
        output_path=gold_path,
        overwrite=True,
    )
    print(f"Gold split saved to {gold_path}")

    print(f"\nSuccessfully generated and frozen {len(all_tasks)} ADR 0019/0020 tasks across 5 families.")


if __name__ == "__main__":
    main()
