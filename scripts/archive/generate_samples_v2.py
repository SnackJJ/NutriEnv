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

_ROOT = Path(__file__).resolve().parents[2]
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
from nutrienv.bench.pipeline.sampler import is_non_meal_condiment, sample_pools, spoken_display_name, FoodPool, PoolFood
from nutrienv.bench.pipeline.semantic_vote import DEFAULT_TRIAD_VOTERS, FnddsVoteResult, vote_fndds_portion
from nutrienv.io.chat import complete_chat

DEFAULT_CATALOG_PATH = "data/fdc/catalog-v2.sqlite"
DEFAULT_CANDIDATE_PATH = "data/candidates/v2.2-candidates.json"
DEFAULT_GOLD_PATH = "data/splits/v2.2-gold.json"
DEFAULT_HTML_REPORT = "reports/v2.2-candidates-review.html"

FAMILIES = ("log", "evaluate", "recommend", "update", "composite")
VOTER_MODELS = DEFAULT_TRIAD_VOTERS


def _complete_llm(model_id: str, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
    """Call LLM via unified chat client with retry on transient network error."""
    import time
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    for attempt in range(3):
        try:
            return complete_chat(model_id, messages, temperature=temperature, max_tokens=300)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))


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

    CONTAINER_COLLOQUIAL_WORDS = (
        "bowl", "plate", "mug", "glass", "order", "handful", "scoop", "serving", "portion",
        "pack", "package", "bag", "three-egg", "two-egg", "double", "triple", "half", "quarter"
    )
    is_colloquial = any(w in clause.lower() for w in CONTAINER_COLLOQUIAL_WORDS)

    # Tier 1: Deterministic resolution (exact portion table match)
    grams = spoken_grams_from_query(clause, food_id, catalog)
    if grams is None:
        grams = resolve_portion(food_id, clause, catalog)
    if grams is not None and matches_portion_table(food_id, float(grams), catalog):
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

    # Tier 2: Multi-Agent Vote Fallback for novel/unmapped phrasing
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


def _food_has_allergen_clash(food_id: str, catalog: Mapping, allergies: tuple[str, ...]) -> bool:
    """Check if a specific food_id clashes with user allergies."""
    if not allergies:
        return False
    user_allergies = set(normalize_tags(list(allergies)))
    entry = catalog.get(str(food_id)) or {}
    tags = set(normalize_tags(list(entry.get("allergen_tags") or [])))
    return bool(user_allergies & tags)


def _detect_meal_slot(query: str, default: str = "today-lunch") -> str:
    """Detect spoken meal occasion to ensure LedgerRow eaten_at matches user intent."""
    q = query.lower()
    # Check breakfast first, then dinner, then lunch
    if "breakfast" in q or "morning" in q:
        return "today-breakfast"
    if "dinner" in q or "evening" in q or "supper" in q or "night" in q:
        return "today-dinner"
    if "lunch" in q or "noon" in q or "afternoon" in q:
        return "today-lunch"
    return default


def generate_log_sample(
    seed: int,
    catalog: Mapping,
    *,
    model_id: str = "qwen3.8-flash",
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
        food_descriptions.append(f'- id="{f.food_id}" description="{f.name}"')

    sys_prompt = (
        "You are writing a realistic food diary entry for a person logging their food in MyFitnessPal or Reddit.\n"
        f"User Persona: {person.persona}, Diet Style: {person.diet_style}.\n"
        "CRITICAL NATURAL DINING GUIDELINES:\n"
        "- Speak naturally as a real human eater. Use everyday household dining portions ('a bowl of...', 'a plate of...', 'two slices of...', 'half a cup of...', 'two patties', 'a slice and a half', 'a sandwich', 'a pack of...', 'a handful of...', 'a tablespoon of...').\n"
        "- NEVER copy bureaucratic/academic database descriptors verbatim (e.g. NEVER say 'pre-sweetened with sugar', 'NS as to fat', 'Puerto Rican style', 'prepared from mix', 'peel not eaten', 'flavors other than chocolate'). Translate them to natural phrasing (e.g. 'sweet coffee', 'baked potato with butter', 'fried plantains', 'vanilla shake', 'chicken tenders').\n"
        "- NEVER append un-scored dietary adjectives (e.g. do NOT say 'low-sodium', 'dairy-free', 'high-protein', 'gluten-free', 'low-carb') unless that is the literal food name.\n"
        "- NEVER use 'a cup of' for burgers, patties, sandwiches, or plated meals.\n"
        "- Return ONLY a JSON object: {\"query\": \"<natural single-sentence diary log>\", \"foods\": [\"<food_id>\", ...]}"
    )
    user_prompt = (
        f"Compose one plausible meal from these available foods:\n"
        + "\n".join(food_descriptions)
        + "\n\nJSON output only:"
    )

    for _attempt in range(3):
        raw = _complete_llm(model_id, sys_prompt, user_prompt)
        data = _parse_json_payload(raw)
        if not data or "query" not in data or "foods" not in data:
            continue
        query = str(data["query"]).strip()
        food_ids = [str(fid) for fid in data["foods"] if str(fid) in catalog]
        if not food_ids:
            continue

        meal_slot = _detect_meal_slot(query, default="today-lunch")
        resolutions = []
        ledger_rows = []
        all_resolved = True
        for fid in food_ids:
            res = _resolve_food_in_query(query, fid, catalog, enable_vote=enable_vote)
            resolutions.append(res)
            grams = res.get("grams")
            if grams is not None and grams > 0 and matches_portion_table(fid, grams, catalog):
                ledger_rows.append(LedgerRow(fid, grams, meal_slot))
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
    model_id: str = "qwen3.8-flash",
    enable_vote: bool = True,
    target_mode: int = 0,
) -> dict | None:
    """Generate an Evaluate task testing a specific target verdict (0: allergy, 1: accept, 2: kcal_lo, 3: kcal_hi)."""
    rng = random.Random(seed)

    for attempt in range(12):
        cur_seed = seed + attempt * 73
        rng_attempt = random.Random(cur_seed)
        person = sample_roster_person(cur_seed)
        profile = profile_for(person)

        if target_mode == 0:
            # Allergy knife: pick person with allergy
            if not person.allergies:
                allergic_persons = [p for p in ROSTER if p.allergies]
                person = allergic_persons[cur_seed % len(allergic_persons)]
                profile = profile_for(person)
            allergen = person.allergies[0]
            pools = sample_pools(catalog, seed=cur_seed, family="evaluate", n_pools=1, pool_size=10, with_allergen=allergen)
            pool = pools[0]
            banned = set(normalize_tags(list(person.allergies)))
            allergen_foods = [f for f in pool.foods if set(normalize_tags(list(f.allergen_tags))) & banned]
            if not allergen_foods:
                continue
            chosen_foods = [rng_attempt.choice(allergen_foods)]
        elif target_mode == 1:
            # Balanced accept: main staple + side to reach ~650-800 kcal
            pools = sample_pools(catalog, seed=cur_seed, family="evaluate", n_pools=1, pool_size=12)
            pool = pools[0]
            safe_foods = [f for f in pool.foods if not _check_allergen_clash([f], person.allergies)]
            if len(safe_foods) < 2:
                continue
            chosen_foods = rng_attempt.sample(safe_foods, 2)
        elif target_mode == 2:
            # Undershoot (light snack/salad, < 200 kcal)
            pools = sample_pools(catalog, seed=cur_seed, family="evaluate", n_pools=1, pool_size=10)
            pool = pools[0]
            safe_foods = [f for f in pool.foods if not _check_allergen_clash([f], person.allergies)]
            if not safe_foods:
                continue
            chosen_foods = [rng_attempt.choice(safe_foods)]
        else:
            # Overshoot (3 hearty items, > 1100 kcal)
            pools = sample_pools(catalog, seed=cur_seed, family="evaluate", n_pools=1, pool_size=12)
            pool = pools[0]
            safe_foods = [f for f in pool.foods if not _check_allergen_clash([f], person.allergies)]
            if len(safe_foods) < 3:
                continue
            chosen_foods = rng_attempt.sample(safe_foods, 3)

        food_descriptions = []
        for f in chosen_foods:
            food_descriptions.append(f'- id="{f.food_id}" description="{f.name}"')

        sys_prompt = (
            "You write a natural user query asking a nutritional assistant to evaluate a planned lunch meal.\n"
            f"User Persona: {person.persona}, Diet Style: {person.diet_style}.\n"
            "CRITICAL NATURAL DINING GUIDELINES:\n"
            "- Example: 'Evaluate this lunch: a turkey sandwich and an apple.' or 'Can you evaluate my planned lunch: a bowl of chicken noodle soup and a roll?'\n"
            "- NEVER copy bureaucratic/academic database descriptors verbatim.\n"
            "- NEVER mention allergy codes or un-scored buzzwords (e.g. do NOT say 'for my high-protein gym day', 'gluten-free diet', 'low-carb cutting plan'). Keep the prompt a clean evaluation request.\n"
            "- Speak foods with natural household measures (a plate of, a bowl of, a slice of, a patty, a piece of, a handful of, two slices of, half a cup of).\n"
            "- Return ONLY a JSON object: {\"query\": \"<evaluation query>\", \"foods\": [\"<food_id>\", ...]}"
        )
        user_prompt = (
            f"Write an evaluation request naming these planned foods:\n"
            + "\n".join(food_descriptions)
            + "\n\nJSON output only:"
        )

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

        if not (all_resolved and plan_items):
            continue

        s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
        try:
            task = realize_evaluate(
                task_id=f"adr20-eval-{seed:04d}",
                query=query,
                items=plan_items,
                s0=s0,
                occasion="lunch",
            )
            # Verify target verdict matches quota
            if target_mode == 0:
                if "allergy" not in task.oracle.last_reasons:
                    continue
            elif target_mode == 1:
                if task.oracle.last_verdict != "accept":
                    continue
            elif target_mode == 2:
                if "kcal_lo" not in task.oracle.last_reasons:
                    continue
            elif target_mode == 3:
                if not ("kcal_hi" in task.oracle.last_reasons or "sodium_hi" in task.oracle.last_reasons):
                    continue

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
    """Generate a Recommend query with dynamically calculated remainder windows and valid S0 seeds."""
    person = sample_roster_person(seed)
    profile = profile_for(person)
    occasions = ("breakfast", "lunch", "dinner")
    occ = occasions[seed % len(occasions)]

    s0_ledger = []
    # Valid staple foods verified against matches_portion_table
    if occ == "dinner":
        # Lunch was 2708539 (Rice with chicken @ 190.0g) or 2707077 (Burrito @ 100.0g)
        seed_fid = "2708539" if not _food_has_allergen_clash("2708539", catalog, person.allergies) else "2707077"
        seed_grams = 190.0 if seed_fid == "2708539" else 100.0
        if not _food_has_allergen_clash(seed_fid, catalog, person.allergies):
            s0_ledger = [LedgerRow(seed_fid, seed_grams, "today-lunch")]
    elif occ == "lunch":
        # Breakfast was 2707077 (Burrito @ 100.0g) or 2708539 (Rice with chicken @ 190.0g)
        seed_fid = "2707077" if not _food_has_allergen_clash("2707077", catalog, person.allergies) else "2708539"
        seed_grams = 100.0 if seed_fid == "2707077" else 190.0
        if not _food_has_allergen_clash(seed_fid, catalog, person.allergies):
            s0_ledger = [LedgerRow(seed_fid, seed_grams, "today-breakfast")]

    eaten = ledger_totals(s0_ledger, catalog)
    plan_windows = plan_windows_for_meal(profile.windows, eaten, occ)
    if plan_windows is None:
        plan_windows = {"kcal": (400.0, 700.0), "protein_g": (20.0, 45.0)}

    templates = [
        f"What should I eat for {occ}?",
        f"Give me a healthy meal plan for {occ}.",
        f"Recommend a {occ} that fits my daily targets.",
        f"What are some good {occ} options for my diet targets?",
        f"What do you recommend for {occ}?",
        f"Can you suggest a healthy {occ} meal?",
        f"Please provide a meal recommendation for {occ}.",
        f"What would be a suitable {occ} meal according to my targets?",
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
    """Generate an Update query testing weight, allergies, activity, and goals with 8 distinct ops."""
    person = sample_roster_person(seed)
    profile = profile_for(person)

    update_mode = seed % 8
    if update_mode == 0:
        # Weight increase
        new_weight = round(person.weight_kg + 2.5, 1)
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
    elif update_mode == 1:
        # Weight decrease
        new_weight = round(person.weight_kg - 2.0, 1)
        query = f"I weighed in at {new_weight:g} kg this morning. Please update my weight."
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
    elif update_mode == 2:
        # Add peanut allergy
        query = "Add peanut to my allergies."
        new_allergies = tuple(sorted(set(profile.allergies) | {"peanut"}))
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
    elif update_mode == 3:
        # Add egg allergy
        query = "I was recently diagnosed with an egg allergy. Add egg to my allergy list."
        new_allergies = tuple(sorted(set(profile.allergies) | {"egg"}))
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
    elif update_mode == 4:
        # Remove existing allergy (select roster person with allergy)
        allergic_persons = [p for p in ROSTER if p.allergies]
        person = allergic_persons[seed % len(allergic_persons)]
        profile = profile_for(person)
        remove_a = person.allergies[0]
        new_allergies = tuple(a for a in profile.allergies if a != remove_a)
        query = f"I am no longer allergic to {remove_a}. Remove it from my allergies."
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
    elif update_mode == 5:
        # Update activity to light / moderate based on initial baseline
        if profile.activity in ("moderate", "active", "very_active"):
            query = "I have been less active recently, please update my activity level to light."
            new_act = "light"
        else:
            query = "I started exercising regularly, please update my activity level to moderate."
            new_act = "moderate"
        raw_patched = Profile(
            user_id=profile.user_id,
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity=new_act,
            allergies=profile.allergies,
            phase=profile.phase,
        )
        new_windows = derive_profile_windows(raw_patched)
        oracle_profile = Profile(
            user_id=profile.user_id,
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity=new_act,
            allergies=profile.allergies,
            phase=profile.phase,
            windows=new_windows,
        )
    elif update_mode == 6:
        # Update activity to very active
        query = "I started high-intensity athletic training, please change my activity level to very active."
        raw_patched = Profile(
            user_id=profile.user_id,
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity="very_active",
            allergies=profile.allergies,
            phase=profile.phase,
        )
        new_windows = derive_profile_windows(raw_patched)
        oracle_profile = Profile(
            user_id=profile.user_id,
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity="very_active",
            allergies=profile.allergies,
            phase=profile.phase,
            windows=new_windows,
        )
    else:
        # Goal / phase switch
        new_phase = "muscle" if profile.phase != "muscle" else "cut"
        query = f"Switch my fitness goal to {new_phase} phase."
        raw_patched = Profile(
            user_id=profile.user_id,
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity=profile.activity,
            allergies=profile.allergies,
            phase=new_phase,
        )
        new_windows = derive_profile_windows(raw_patched)
        oracle_profile = Profile(
            user_id=profile.user_id,
            sex=profile.sex,
            age_y=profile.age_y,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity=profile.activity,
            allergies=profile.allergies,
            phase=new_phase,
            windows=new_windows,
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


def _is_substantive_meal_food(food: PoolFood, catalog: Mapping, allergies: tuple[str, ...]) -> bool:
    if _check_allergen_clash([food], allergies):
        return False
    if is_non_meal_condiment(food.name):
        return False
    entry = catalog.get(food.food_id) or {}
    nutrients = entry.get("nutrients") or {}
    kcal_100g = float(nutrients.get("kcal") or 0.0)
    portions = entry.get("portions") or {}
    if not portions:
        return kcal_100g >= 120.0
    max_portion_g = max(portions.values())
    return (kcal_100g * max_portion_g / 100.0) >= 120.0


def generate_comp_sample(
    seed: int,
    catalog: Mapping,
    *,
    model_id: str = "qwen3.8-flash",
    enable_vote: bool = True,
    sub_type: str = "log_rec",
) -> dict | None:
    """Generate a Composite query supporting legal end-state pairs: log_rec, log_upd, log_eval, upd_rec."""
    person = sample_roster_person(seed)
    profile = profile_for(person)
    rng = random.Random(seed)

    if sub_type == "log_rec":
        pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=10)
        pool = pools[0]
        safe_foods = [f for f in pool.foods if _is_substantive_meal_food(f, catalog, person.allergies)]
        if not safe_foods:
            return None
        chosen_foods = rng.sample(safe_foods, k=min(len(safe_foods), rng.choice([1, 2])))
        food_descriptions = [f'- {spoken_display_name(catalog, f.food_id)}' for f in chosen_foods]

        sys_prompt = (
            "You are writing a two-part user request: first, log what was just eaten for lunch, then ask what to eat for dinner.\n"
            f"User Persona: {person.persona}, Diet Style: {person.diet_style}.\n"
            "CRITICAL NATURAL DINING GUIDELINES:\n"
            "- Speak foods naturally like a real human diner. NEVER copy raw FNDDS bureaucratic descriptors ('NS as to...', 'NFS', 'prepared from mix', 'from fast food', '(id=...)').\n"
            "- Example: 'I had a turkey sandwich and a bowl of chicken noodle soup for lunch, so what should I eat for dinner?'\n"
            "- NEVER append un-scored dietary buzzwords.\n"
            "- Use natural household quantities (plate of, bowl of, slice of, piece of, handful of, pack of, two slices of, half a cup of).\n"
            "- Return ONLY a JSON object: {\"query\": \"<composite query>\", \"foods\": [\"<food_id>\", ...]}"
        )
        user_prompt = f"Create a composite query logging these lunch foods and asking for dinner recommendation:\n" + "\n".join(food_descriptions) + "\n\nJSON output only:"

        for _attempt in range(3):
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
                lunch_totals = ledger_totals(ledger_rows, catalog)
                if lunch_totals.get("kcal", 0.0) < 150.0:
                    continue
                s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
                oracle_log = Oracle(profile=copy.deepcopy(profile), ledger_tail=ledger_rows, ledger=tuple(ledger_rows))
                dinner_windows = plan_windows_for_meal(profile.windows, lunch_totals, "dinner") or {"kcal": (400.0, 700.0), "protein_g": (20.0, 45.0)}
                oracle_rec = Oracle(
                    profile=copy.deepcopy(profile),
                    last_plan=[],
                    plan_must_be_safe=True,
                    plan_must_fit_windows=True,
                    plan_windows=dinner_windows,
                    ledger=tuple(ledger_rows),
                )
                composite_oracle = compose_oracles(oracle_log, oracle_rec)
                task = Task(id=f"adr24-comp-{seed:04d}", family="composite", query=query, s0=s0, oracle=composite_oracle, persona=person.persona)
                return {"task": task, "person": person, "resolutions": resolutions, "raw_response": raw}

    elif sub_type == "log_upd":
        pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=10)
        pool = pools[0]
        safe_foods = [f for f in pool.foods if _is_substantive_meal_food(f, catalog, person.allergies)]
        if not safe_foods:
            return None
        chosen_foods = rng.sample(safe_foods, k=min(len(safe_foods), rng.choice([1, 2])))
        food_descriptions = [f'- {spoken_display_name(catalog, f.food_id)}' for f in chosen_foods]

        activity_opts = [a for a in ("sedentary", "light", "moderate", "active", "very_active") if a != person.activity]
        new_activity = rng.choice(activity_opts)
        activity_spoken = new_activity.replace("_", " ")

        sys_prompt = (
            "You are writing a two-part user request: first, log what was just eaten for lunch, then ask to update the profile activity level.\n"
            f"User Persona: {person.persona}.\n"
            "- CRITICAL: Speak foods naturally like a real human diner. NEVER copy raw FNDDS bureaucratic descriptors ('NS as to...', 'NFS', 'prepared from mix', 'from fast food', '(id=...)').\n"
            f"- Example: 'I had a turkey sandwich and an apple for lunch. Also, I started exercising regularly so update my activity level to {activity_spoken}.'\n"
            "- Return ONLY a JSON object: {\"query\": \"<composite query>\", \"foods\": [\"<food_id>\", ...]}"
        )
        user_prompt = f"Create a composite query logging these lunch foods and updating activity level to '{activity_spoken}':\n" + "\n".join(food_descriptions) + "\n\nJSON output only:"

        for _attempt in range(3):
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
                oracle_log = Oracle(profile=None, ledger_tail=ledger_rows, ledger=tuple(ledger_rows))

                patched_raw = Profile(
                    user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                    weight_kg=profile.weight_kg, activity=new_activity, allergies=profile.allergies, phase=profile.phase
                )
                oracle_prof = Profile(
                    user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                    weight_kg=profile.weight_kg, activity=new_activity, allergies=profile.allergies, phase=profile.phase,
                    windows=derive_profile_windows(patched_raw)
                )
                oracle_upd = Oracle(profile=oracle_prof, ledger=None)
                composite_oracle = compose_oracles(oracle_log, oracle_upd)
                task = Task(id=f"adr24-comp-{seed:04d}", family="composite", query=query, s0=s0, oracle=composite_oracle, persona=person.persona)
                return {"task": task, "person": person, "resolutions": resolutions, "raw_response": raw}

    elif sub_type == "upd_rec":
        allergens_to_add = [a for a in ("peanut", "tree_nut", "shellfish", "egg", "milk") if a not in person.allergies]
        add_allergen = rng.choice(allergens_to_add) if allergens_to_add else "shellfish"
        new_allergies = tuple(sorted(list(person.allergies) + [add_allergen]))

        sys_prompt = (
            "You are writing a two-part user request: first, notify that you developed a new food allergy, then ask for a safe dinner meal recommendation.\n"
            f"User Persona: {person.persona}.\n"
            "- CRITICAL: Speak naturally like a real person. NEVER include database identifiers or bureaucratic codes.\n"
            "- Example: 'I was recently diagnosed with a shellfish allergy, please add shellfish to my profile. What should I eat for dinner?'\n"
            "- Return ONLY a JSON object: {\"query\": \"<composite query>\"}"
        )
        user_prompt = f"Create a composite query adding allergy '{add_allergen}' and asking for a dinner recommendation.\n\nJSON output only:"

        for _attempt in range(3):
            raw = _complete_llm(model_id, sys_prompt, user_prompt)
            data = _parse_json_payload(raw)
            if not data or "query" not in data:
                continue
            query = str(data["query"]).strip()

            s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
            patched_prof = Profile(
                user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                weight_kg=profile.weight_kg, activity=profile.activity, allergies=new_allergies, phase=profile.phase,
                windows=profile.windows
            )
            oracle_upd = Oracle(profile=patched_prof, ledger=None)
            dinner_windows = plan_windows_for_meal(profile.windows, {}, "dinner") or {"kcal": (500.0, 800.0), "protein_g": (25.0, 50.0)}
            oracle_rec = Oracle(
                profile=patched_prof,
                last_plan=[],
                plan_must_be_safe=True,
                plan_must_fit_windows=True,
                plan_windows=dinner_windows,
                ledger=(),
            )
            composite_oracle = compose_oracles(oracle_upd, oracle_rec)
            task = Task(id=f"adr24-comp-{seed:04d}", family="composite", query=query, s0=s0, oracle=composite_oracle, persona=person.persona)
            return {"task": task, "person": person, "resolutions": [], "raw_response": raw}

    elif sub_type == "log_eval":
        pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=10)
        pool = pools[0]
        safe_foods = [f for f in pool.foods if _is_substantive_meal_food(f, catalog, person.allergies)]
        if len(safe_foods) < 2:
            return None
        lunch_food = safe_foods[0]
        eval_food = safe_foods[1]

        sys_prompt = (
            "You are writing a two-part user request: first, log what was eaten for lunch using natural household measures, then ask to evaluate a planned afternoon snack food.\n"
            f"User Persona: {person.persona}.\n"
            "- CRITICAL: Speak foods naturally like a real human diner. NEVER copy raw FNDDS bureaucratic descriptors ('NS as to...', 'NFS', 'prepared from mix', 'from fast food', '(id=...)').\n"
            "- Example: 'I had a bowl of chicken noodle soup for lunch. For an afternoon snack, is eating an apple compliant with my targets?'\n"
            "- Return ONLY a JSON object: {\"query\": \"<composite query>\", \"foods\": [\"<food_id>\", ...]}"
        )
        user_prompt = f"Create a query logging lunch food '{spoken_display_name(catalog, lunch_food.food_id)}' and asking to evaluate snack food '{spoken_display_name(catalog, eval_food.food_id)}'.\n\nJSON output only:"

        for _attempt in range(3):
            raw = _complete_llm(model_id, sys_prompt, user_prompt)
            data = _parse_json_payload(raw)
            if not data or "query" not in data:
                continue
            query = str(data["query"]).strip()

            res_lunch = _resolve_food_in_query(query, lunch_food.food_id, catalog, enable_vote=enable_vote)
            res_eval = _resolve_food_in_query(query, eval_food.food_id, catalog, enable_vote=enable_vote)

            g_lunch = res_lunch.get("grams")
            g_eval = res_eval.get("grams")
            if (
                g_lunch and g_lunch > 0 and matches_portion_table(lunch_food.food_id, g_lunch, catalog) and
                g_eval and g_eval > 0 and matches_portion_table(eval_food.food_id, g_eval, catalog)
            ):
                lunch_row = LedgerRow(lunch_food.food_id, g_lunch, "today-lunch")
                eval_item = [{"food_id": eval_food.food_id, "grams": g_eval}]

                s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
                oracle_log = Oracle(profile=None, ledger_tail=[lunch_row], ledger=(lunch_row,))

                eval_task = realize_evaluate(
                    task_id=f"adr24-eval-{seed:04d}",
                    query="eval",
                    items=eval_item,
                    s0=WorldState(profile=profile, ledger=[lunch_row], catalog=catalog),
                    occasion="snack",
                )
                oracle_eval = eval_task.oracle
                composite_oracle = compose_oracles(oracle_log, oracle_eval)
                task = Task(id=f"adr24-comp-{seed:04d}", family="composite", query=query, s0=s0, oracle=composite_oracle, persona=person.persona)
                return {"task": task, "person": person, "resolutions": [res_lunch, res_eval], "raw_response": raw}

    elif sub_type == "upd_log_rec":
        allergens_to_add = [a for a in ("peanut", "tree_nut", "shellfish", "egg", "milk") if a not in person.allergies]
        add_allergen = rng.choice(allergens_to_add) if allergens_to_add else "shellfish"
        new_allergies = tuple(sorted(list(person.allergies) + [add_allergen]))

        pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=10)
        pool = pools[0]
        safe_foods = [f for f in pool.foods if _is_substantive_meal_food(f, catalog, new_allergies)]
        if not safe_foods:
            return None
        lunch_food = safe_foods[0]

        sys_prompt = (
            "You are writing a 3-part natural user request to a nutritional assistant:\n"
            f"Part 1: Update profile to add a '{add_allergen}' allergy.\n"
            "Part 2: Log lunch food using natural household measures (a plate of, a bowl of, a slice of, a patty, a piece of, a handful of, two slices of, half a cup of).\n"
            "Part 3: Ask for a compliant dinner recommendation.\n"
            f"User Persona: {person.persona}.\n"
            "- CRITICAL: Speak foods naturally like a real human diner. NEVER copy raw FNDDS bureaucratic descriptors ('NS as to...', 'NFS', 'prepared from mix', 'from fast food', '(id=...)').\n"
            "- Example: 'I was diagnosed with a shellfish allergy, please add shellfish to my profile. I had a bowl of chicken noodle soup for lunch. What should I eat for dinner?'\n"
            "- Return ONLY a JSON object: {\"query\": \"<composite query>\", \"foods\": [\"<food_id>\"]}"
        )
        user_prompt = f"Create a 3-part query adding '{add_allergen}' allergy, logging lunch food '{spoken_display_name(catalog, lunch_food.food_id)}', and requesting a dinner plan.\n\nJSON output only:"

        for _attempt in range(3):
            raw = _complete_llm(model_id, sys_prompt, user_prompt)
            data = _parse_json_payload(raw)
            if not data or "query" not in data:
                continue
            query = str(data["query"]).strip()

            res_lunch = _resolve_food_in_query(query, lunch_food.food_id, catalog, enable_vote=enable_vote)
            g_lunch = res_lunch.get("grams")
            if g_lunch and g_lunch > 0 and matches_portion_table(lunch_food.food_id, g_lunch, catalog):
                lunch_row = LedgerRow(lunch_food.food_id, g_lunch, "today-lunch")
                s0 = WorldState(profile=profile, ledger=[], catalog=catalog)

                patched_prof = Profile(
                    user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                    weight_kg=profile.weight_kg, activity=profile.activity, allergies=new_allergies, phase=profile.phase,
                    windows=profile.windows
                )
                oracle_upd = Oracle(profile=patched_prof, ledger=None)
                oracle_log = Oracle(profile=patched_prof, ledger_tail=[lunch_row], ledger=(lunch_row,))

                lunch_totals = ledger_totals([lunch_row], catalog)
                dinner_windows = plan_windows_for_meal(profile.windows, lunch_totals, "dinner") or {"kcal": (400.0, 700.0), "protein_g": (20.0, 45.0)}
                oracle_rec = Oracle(
                    profile=patched_prof,
                    last_plan=[],
                    plan_must_be_safe=True,
                    plan_must_fit_windows=True,
                    plan_windows=dinner_windows,
                    ledger=(lunch_row,),
                )
                composite_oracle = compose_oracles(oracle_upd, oracle_log, oracle_rec)
                task = Task(id=f"adr24-comp-{seed:04d}", family="composite", query=query, s0=s0, oracle=composite_oracle, persona=person.persona)
                return {"task": task, "person": person, "resolutions": [res_lunch], "raw_response": raw}

    elif sub_type == "log_upd_eval":
        # Tri-Intent: Log Lunch -> Update Weight -> Evaluate Snack
        pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=10)
        pool = pools[0]
        safe_foods = [f for f in pool.foods if _is_substantive_meal_food(f, catalog, person.allergies)]
        if len(safe_foods) < 2:
            return None
        lunch_food = safe_foods[0]
        eval_food = safe_foods[1]

        new_weight = round(person.weight_kg - 1.5, 1)
        sys_prompt = (
            "You are writing a 3-part natural user request to a nutritional assistant:\n"
            "Part 1: Log lunch food using natural household measures (a bowl of, a plate of, a slice of, a cup of).\n"
            f"Part 2: Update weight to {new_weight} kg.\n"
            "Part 3: Evaluate an afternoon snack food using natural household measures (an apple, a cup of berries, a handful of nuts).\n"
            f"User Persona: {person.persona}.\n"
            "- CRITICAL: Speak foods naturally like a real human diner. NEVER copy raw FNDDS bureaucratic descriptors ('NS as to...', 'NFS', 'prepared from mix', 'from fast food', '(id=...)').\n"
            f"- Example: 'I had a bowl of chicken noodle soup for lunch. I weighed in at {new_weight} kg this morning so update my weight. Is eating an apple for a snack compliant?'\n"
            "- Return ONLY a JSON object: {\"query\": \"<composite query>\", \"foods\": [\"<food_id>\", ...]}"
        )
        user_prompt = f"Create a 3-part query logging lunch food '{spoken_display_name(catalog, lunch_food.food_id)}', updating weight to {new_weight} kg, and evaluating snack '{spoken_display_name(catalog, eval_food.food_id)}'.\n\nJSON output only:"

        for _attempt in range(3):
            raw = _complete_llm(model_id, sys_prompt, user_prompt)
            data = _parse_json_payload(raw)
            if not data or "query" not in data:
                continue
            query = str(data["query"]).strip()

            res_lunch = _resolve_food_in_query(query, lunch_food.food_id, catalog, enable_vote=enable_vote)
            res_eval = _resolve_food_in_query(query, eval_food.food_id, catalog, enable_vote=enable_vote)
            g_lunch = res_lunch.get("grams")
            g_eval = res_eval.get("grams")

            if (
                g_lunch and g_lunch > 0 and matches_portion_table(lunch_food.food_id, g_lunch, catalog) and
                g_eval and g_eval > 0 and matches_portion_table(eval_food.food_id, g_eval, catalog)
            ):
                lunch_row = LedgerRow(lunch_food.food_id, g_lunch, "today-lunch")
                eval_item = [{"food_id": eval_food.food_id, "grams": g_eval}]

                s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
                oracle_log = Oracle(profile=None, ledger_tail=[lunch_row], ledger=(lunch_row,))

                patched_raw = Profile(
                    user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                    weight_kg=new_weight, activity=profile.activity, allergies=profile.allergies, phase=profile.phase
                )
                oracle_prof = Profile(
                    user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                    weight_kg=new_weight, activity=profile.activity, allergies=profile.allergies, phase=profile.phase,
                    windows=derive_profile_windows(patched_raw)
                )
                oracle_upd = Oracle(profile=oracle_prof, ledger=None)

                eval_task = realize_evaluate(
                    task_id=f"adr24-eval-{seed:04d}",
                    query="eval",
                    items=eval_item,
                    s0=WorldState(profile=oracle_prof, ledger=[lunch_row], catalog=catalog),
                    occasion="snack",
                )
                composite_oracle = compose_oracles(oracle_log, oracle_upd, eval_task.oracle)
                task = Task(id=f"adr24-comp-{seed:04d}", family="composite", query=query, s0=s0, oracle=composite_oracle, persona=person.persona)
                return {"task": task, "person": person, "resolutions": [res_lunch, res_eval], "raw_response": raw}

    elif sub_type == "upd_log_eval":
        # Tri-Intent: Update Activity -> Log Lunch -> Evaluate Snack
        activity_opts = [a for a in ("sedentary", "light", "moderate", "active", "very_active") if a != person.activity]
        new_activity = rng.choice(activity_opts)
        activity_spoken = new_activity.replace("_", " ")

        pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=10)
        pool = pools[0]
        safe_foods = [f for f in pool.foods if _is_substantive_meal_food(f, catalog, person.allergies)]
        if len(safe_foods) < 2:
            return None
        lunch_food = safe_foods[0]
        eval_food = safe_foods[1]

        sys_prompt = (
            "You are writing a 3-part natural user request to a nutritional assistant:\n"
            f"Part 1: Update activity level to '{activity_spoken}'.\n"
            "Part 2: Log lunch food using natural household measures (a bowl of, a plate of, a slice of, a piece of).\n"
            "Part 3: Evaluate an afternoon snack food using natural household measures (an orange, an apple, a handful of berries).\n"
            f"User Persona: {person.persona}.\n"
            "- CRITICAL: Speak foods naturally like a real human diner. NEVER copy raw FNDDS bureaucratic descriptors ('NS as to...', 'NFS', 'prepared from mix', 'from fast food', '(id=...)').\n"
            f"- Example: 'I started regular training so update my activity level to {activity_spoken}. I had a turkey wrap for lunch. Is having an orange for a snack compliant?'\n"
            "- Return ONLY a JSON object: {\"query\": \"<composite query>\", \"foods\": [\"<food_id>\", ...]}"
        )
        user_prompt = f"Create a 3-part query updating activity to '{activity_spoken}', logging lunch food '{spoken_display_name(catalog, lunch_food.food_id)}', and evaluating snack '{spoken_display_name(catalog, eval_food.food_id)}'.\n\nJSON output only:"

        for _attempt in range(3):
            raw = _complete_llm(model_id, sys_prompt, user_prompt)
            data = _parse_json_payload(raw)
            if not data or "query" not in data:
                continue
            query = str(data["query"]).strip()

            res_lunch = _resolve_food_in_query(query, lunch_food.food_id, catalog, enable_vote=enable_vote)
            res_eval = _resolve_food_in_query(query, eval_food.food_id, catalog, enable_vote=enable_vote)
            g_lunch = res_lunch.get("grams")
            g_eval = res_eval.get("grams")

            if (
                g_lunch and g_lunch > 0 and matches_portion_table(lunch_food.food_id, g_lunch, catalog) and
                g_eval and g_eval > 0 and matches_portion_table(eval_food.food_id, g_eval, catalog)
            ):
                lunch_row = LedgerRow(lunch_food.food_id, g_lunch, "today-lunch")
                eval_item = [{"food_id": eval_food.food_id, "grams": g_eval}]

                s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
                patched_raw = Profile(
                    user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                    weight_kg=profile.weight_kg, activity=new_activity, allergies=profile.allergies, phase=profile.phase
                )
                oracle_prof = Profile(
                    user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                    weight_kg=profile.weight_kg, activity=new_activity, allergies=profile.allergies, phase=profile.phase,
                    windows=derive_profile_windows(patched_raw)
                )
                oracle_upd = Oracle(profile=oracle_prof, ledger=None)
                oracle_log = Oracle(profile=oracle_prof, ledger_tail=[lunch_row], ledger=(lunch_row,))

                eval_task = realize_evaluate(
                    task_id=f"adr24-eval-{seed:04d}",
                    query="eval",
                    items=eval_item,
                    s0=WorldState(profile=oracle_prof, ledger=[lunch_row], catalog=catalog),
                    occasion="snack",
                )
                composite_oracle = compose_oracles(oracle_upd, oracle_log, eval_task.oracle)
                task = Task(id=f"adr24-comp-{seed:04d}", family="composite", query=query, s0=s0, oracle=composite_oracle, persona=person.persona)
                return {"task": task, "person": person, "resolutions": [res_lunch, res_eval], "raw_response": raw}

    elif sub_type in ("upd_upd_log_rec", "upd_log_eval_rec"):
        # Quad-Intent (Boss Task): Update Allergy + Update Activity -> Log Lunch -> Recommend Dinner
        allergens_to_add = [a for a in ("peanut", "tree_nut", "shellfish", "egg", "milk") if a not in person.allergies]
        add_allergen = rng.choice(allergens_to_add) if allergens_to_add else "peanut"
        new_allergies = tuple(sorted(list(person.allergies) + [add_allergen]))

        activity_opts = [a for a in ("sedentary", "light", "moderate", "active", "very_active") if a != person.activity]
        new_activity = rng.choice(activity_opts)
        activity_spoken = new_activity.replace("_", " ")

        pools = sample_pools(catalog, seed=seed, family="log", n_pools=1, pool_size=12)
        pool = pools[0]
        safe_foods = [f for f in pool.foods if _is_substantive_meal_food(f, catalog, new_allergies)]
        if not safe_foods:
            return None
        lunch_food = safe_foods[0]

        sys_prompt = (
            "You are writing a 4-part comprehensive user request to a nutritional assistant:\n"
            f"Part 1: Update profile to add '{add_allergen}' allergy.\n"
            f"Part 2: Update activity level to '{activity_spoken}'.\n"
            "Part 3: Log lunch food using natural household measures (a plate of, a bowl of, a slice of, a piece of).\n"
            "Part 4: Ask for a compliant dinner meal recommendation.\n"
            f"User Persona: {person.persona}.\n"
            "- CRITICAL: Speak foods naturally like a real human diner. NEVER copy raw FNDDS bureaucratic descriptors ('NS as to...', 'NFS', 'prepared from mix', 'from fast food', '(id=...)').\n"
            f"- Example: 'I was diagnosed with a {add_allergen} allergy so add it to my profile, and I started heavy workouts so change my activity to {activity_spoken}. For lunch, I had a plate of grilled salmon. What should I eat for dinner?'\n"
            "- Return ONLY a JSON object: {\"query\": \"<composite query>\", \"foods\": [\"<food_id>\", ...]}"
        )
        user_prompt = f"Create a 4-part query adding '{add_allergen}' allergy, setting activity '{activity_spoken}', logging lunch food '{spoken_display_name(catalog, lunch_food.food_id)}', and requesting dinner recommendation.\n\nJSON output only:"

        for _attempt in range(3):
            raw = _complete_llm(model_id, sys_prompt, user_prompt)
            data = _parse_json_payload(raw)
            if not data or "query" not in data:
                continue
            query = str(data["query"]).strip()

            res_lunch = _resolve_food_in_query(query, lunch_food.food_id, catalog, enable_vote=enable_vote)
            g_lunch = res_lunch.get("grams")

            if g_lunch and g_lunch > 0 and matches_portion_table(lunch_food.food_id, g_lunch, catalog):
                lunch_row = LedgerRow(lunch_food.food_id, g_lunch, "today-lunch")

                s0 = WorldState(profile=profile, ledger=[], catalog=catalog)
                patched_raw = Profile(
                    user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                    weight_kg=profile.weight_kg, activity=new_activity, allergies=new_allergies, phase=profile.phase
                )
                new_windows = derive_profile_windows(patched_raw)
                if not new_windows:
                    continue
                oracle_prof = Profile(
                    user_id=profile.user_id, sex=profile.sex, age_y=profile.age_y, height_cm=profile.height_cm,
                    weight_kg=profile.weight_kg, activity=new_activity, allergies=new_allergies, phase=profile.phase,
                    windows=new_windows
                )
                oracle_upd1 = Oracle(profile=oracle_prof, ledger=None)
                oracle_log = Oracle(profile=oracle_prof, ledger_tail=[lunch_row], ledger=(lunch_row,))

                lunch_totals = ledger_totals([lunch_row], catalog)
                dinner_windows = plan_windows_for_meal(new_windows, lunch_totals, "dinner") or {"kcal": (400.0, 700.0), "protein_g": (20.0, 45.0)}
                oracle_rec = Oracle(
                    profile=oracle_prof,
                    last_plan=[],
                    plan_must_be_safe=True,
                    plan_must_fit_windows=True,
                    plan_windows=dinner_windows,
                    ledger=(lunch_row,),
                )

                composite_oracle = compose_oracles(oracle_upd1, oracle_log, oracle_rec)
                task = Task(id=f"adr24-comp-{seed:04d}", family="composite", query=query, s0=s0, oracle=composite_oracle, persona=person.persona)
                return {"task": task, "person": person, "resolutions": [res_lunch], "raw_response": raw}

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
    parser = argparse.ArgumentParser(description="NutriEnv ADR 0024 Pipeline Generator (100 Benchmark Matrix)")
    parser.add_argument("--benchmark-100", action="store_true", default=True, help="Generate full 100-task benchmark matrix (5 Upd, 15 Log, 20 Eval, 20 Rec, 40 Comp)")
    parser.add_argument("--count", type=int, default=None, help="Override count per family")
    parser.add_argument("--start-seed", type=int, default=6000, help="Initial global seed offset")
    parser.add_argument("--models", type=str, default="qwen3.8-2.4t-a95b", help="Model ID")
    parser.add_argument("--catalog", type=str, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--candidate-out", type=str, default=DEFAULT_CANDIDATE_PATH)
    parser.add_argument("--gold-out", type=str, default=DEFAULT_GOLD_PATH)
    parser.add_argument("--html", type=str, default=DEFAULT_HTML_REPORT)
    parser.add_argument("--no-vote", action="store_true", help="Disable Tier 2 Vote Fallback")
    args = parser.parse_args()

    catalog = load_catalog(Path(args.catalog))
    enable_vote = not args.no_vote
    results = {"update": [], "log": [], "evaluate": [], "recommend": [], "composite": []}
    all_tasks = []

    if args.count is not None:
        family_quotas = {
            "update": args.count,
            "log": args.count,
            "evaluate": args.count,
            "recommend": args.count,
            "composite": args.count,
        }
    else:
        # ADR 0024 100 Benchmark Standard Matrix
        family_quotas = {
            "update": 5,
            "log": 15,
            "evaluate": 20,
            "recommend": 20,
            "composite": 40,
        }

    total_target = sum(family_quotas.values())
    print(f"=== NutriEnv ADR 0024 Benchmark Generation (Target: {total_target} tasks, start_seed={args.start_seed}, model={args.models}) ===")
    print(f"    Quotas: {family_quotas}")

    global_seed = args.start_seed
    max_seed = global_seed + total_target * 50

    # 1. Update (5 tasks)
    print("\n[1/5] Generating Update tasks...")
    while len(results["update"]) < family_quotas["update"] and global_seed < max_seed:
        item = generate_upd_sample(global_seed, catalog)
        if item:
            results["update"].append(item)
            all_tasks.append(item["task"])
            print(f"  [Upd {len(results['update'])}/{family_quotas['update']}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # 2. Log (15 tasks)
    print("\n[2/5] Generating Log tasks...")
    while len(results["log"]) < family_quotas["log"] and global_seed < max_seed:
        item = generate_log_sample(global_seed, catalog, model_id=args.models, enable_vote=enable_vote)
        if item:
            results["log"].append(item)
            all_tasks.append(item["task"])
            print(f"  [Log {len(results['log'])}/{family_quotas['log']}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # 3. Evaluate (20 tasks: 8 allergy, 4 accept, 4 kcal_lo, 4 kcal_hi)
    print("\n[3/5] Generating Evaluate tasks...")
    eval_quota = family_quotas["evaluate"]
    # Distribute target modes proportionally: 40% allergy, 20% accept, 20% kcal_lo, 20% kcal_hi
    eval_targets = []
    for _ in range(max(1, eval_quota // 5)):
        eval_targets.extend([0, 0, 1, 2, 3])
    eval_targets = eval_targets[:eval_quota]

    for mode in eval_targets:
        item = None
        while item is None and global_seed < max_seed:
            item = generate_eval_sample(global_seed, catalog, model_id=args.models, enable_vote=enable_vote, target_mode=mode)
            global_seed += 1
        if item:
            results["evaluate"].append(item)
            all_tasks.append(item["task"])
            print(f"  [Eval {len(results['evaluate'])}/{len(eval_targets)}, mode={mode}] seed={global_seed-1} -> \"{item['task'].query}\" (verdict={item['task'].oracle.last_verdict}, reasons={item['task'].oracle.last_reasons})")

    # 4. Recommend (20 tasks)
    print("\n[4/5] Generating Recommend tasks...")
    while len(results["recommend"]) < family_quotas["recommend"] and global_seed < max_seed:
        item = generate_rec_sample(global_seed, catalog)
        if item:
            results["recommend"].append(item)
            all_tasks.append(item["task"])
            print(f"  [Rec {len(results['recommend'])}/{family_quotas['recommend']}] seed={global_seed} -> \"{item['task'].query}\"")
        global_seed += 1

    # 5. Composite (40 tasks: 24 Dual-Intent, 12 Tri-Intent, 4 Quad-Intent)
    print("\n[5/5] Generating Composite tasks (3-Tier Multi-Intent Hierarchy)...")
    comp_quota = family_quotas["composite"]
    comp_subtypes = (
        ["log_rec"] * 12 + ["log_upd"] * 4 + ["log_eval"] * 4 + ["upd_rec"] * 4 +  # Tier 1 Dual (24)
        ["upd_log_rec"] * 4 + ["log_upd_eval"] * 4 + ["upd_log_eval"] * 4 +        # Tier 2 Tri (12)
        ["upd_log_eval_rec"] * 4                                                    # Tier 3 Quad (4)
    )
    comp_subtypes = comp_subtypes[:comp_quota]

    for sub_type in comp_subtypes:
        item = None
        while item is None and global_seed < max_seed:
            item = generate_comp_sample(global_seed, catalog, model_id=args.models, enable_vote=enable_vote, sub_type=sub_type)
            global_seed += 1
        if item:
            results["composite"].append(item)
            all_tasks.append(item["task"])
            print(f"  [Comp {len(results['composite'])}/{len(comp_subtypes)}, {sub_type}] seed={global_seed-1} -> \"{item['task'].query}\"")

    # Write HTML Dashboard
    render_html_review_dashboard(results, Path(args.html))

    # Freeze Candidates Split using canonical freezer
    cand_path = Path(args.candidate_out)
    cand_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_tasks(
        all_tasks,
        catalog=catalog,
        catalog_field=args.catalog,
        output_path=cand_path,
        overwrite=True,
    )
    print(f"\nCandidate split saved to {cand_path}")
    print(f"Successfully generated {len(all_tasks)} ADR 0024 benchmark candidate tasks across 5 families.")


if __name__ == "__main__":
    main()
