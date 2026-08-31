#!/usr/bin/env python3
"""Prototype: Multi-Agent Portion Vote & FNDDS Multiplier Estimation (ADR 0019).

Demonstrates:
1. Tier 1: Deterministic parser (resolve_portion) for known rules.
2. Tier 2: Multi-Agent Vote (FNDDS Reference Table + Multiplier) for novel/fractional speech.
3. Vote Consensus & Confidence score to assist human review.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from collections import Counter
from collections.abc import Mapping

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import resolve_portion
from nutrienv.io.chat import complete_chat

DEFAULT_CATALOG = "data/fdc/catalog-v2.sqlite"
VOTER_MODELS = ("deepseek-v4-flash-0731", "kimi-k2.7-code", "glm-5.2")


def vote_single_agent(
    model_id: str,
    query: str,
    food_id: str,
    food_name: str,
    portion_table: Mapping[str, float],
) -> dict:
    """Prompt one LLM subagent to estimate (base_unit, multiplier) against FNDDS table."""
    table_str = "\n".join(f"  - {k}: {v:g} g" for k, v in portion_table.items())
    system_prompt = (
        "You are an expert nutritional measurement judge. Your task is to ground a user's "
        "spoken portion query into an official FNDDS reference portion table by picking a base unit "
        "and a multiplier/fraction.\n\n"
        "Return ONLY a JSON object with this exact schema:\n"
        '{"base_unit": "<unit from table>", "multiplier": <float>, "grams": <float>, "rationale": "<short 1-sentence reasoning>"}'
    )
    user_prompt = (
        f'User Query: "{query}"\n'
        f'Target Food: {food_name} (id: {food_id})\n'
        f"FNDDS Official Portion Table:\n{table_str}\n\n"
        "Instructions:\n"
        "1. Identify the most fitting base unit from the table.\n"
        "2. Estimate the multiplier/quantity based on the user's speech (e.g. 0.5 for half, 1.0 for one/regular, 1.5 for a portion and a half / generous, 2.0 for two).\n"
        "3. Compute final grams = base_unit_grams * multiplier.\n"
        "Output the JSON object only."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        raw = complete_chat(model_id, messages, temperature=0.1, max_tokens=256)
        cleaned = raw.strip()
        if "</think>" in cleaned:
            cleaned = cleaned.split("</think>", 1)[1].strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        data = json.loads(match.group(0)) if match else json.loads(cleaned)
        data["model"] = model_id
        return data
    except Exception as exc:
        return {"model": model_id, "error": str(exc)}


def resolve_with_vote_fallback(
    query: str,
    food_id: str,
    catalog: Mapping,
    voter_models: tuple[str, ...] = VOTER_MODELS,
) -> dict:
    """Two-tier resolver: Deterministic table lookup -> Multi-Agent Vote Fallback."""
    entry = catalog.get(food_id) or {}
    food_name = entry.get("name") or food_id
    portions = entry.get("portions") or {}

    # Tier 1: Deterministic resolution
    exact_grams = resolve_portion(food_id, query, catalog)
    if exact_grams is not None:
        return {
            "tier": "Tier-1 (Deterministic Rule)",
            "query": query,
            "food_id": food_id,
            "food_name": food_name,
            "status": "resolved_exact",
            "grams": exact_grams,
            "consensus": "100% Rule Matched",
            "needs_human_review": False,
        }

    # Tier 2: Multi-Agent Vote Fallback
    votes = []
    for model_id in voter_models:
        vote = vote_single_agent(model_id, query, food_id, food_name, portions)
        votes.append(vote)

    valid_votes = [v for v in votes if "grams" in v and isinstance(v["grams"], (int, float))]
    if not valid_votes:
        return {
            "tier": "Tier-2 (Vote Fallback)",
            "query": query,
            "food_id": food_id,
            "food_name": food_name,
            "status": "failed",
            "error": "All voters failed or produced invalid JSON",
            "needs_human_review": True,
        }

    gram_counts = Counter(round(v["grams"], 1) for v in valid_votes)
    top_grams, count = gram_counts.most_common(1)[0]
    agreement_ratio = count / len(valid_votes)
    consensus_tag = f"{count}/{len(valid_votes)} Consensus ({agreement_ratio:.0%})"

    return {
        "tier": "Tier-2 (Multi-Agent Vote Fallback)",
        "query": query,
        "food_id": food_id,
        "food_name": food_name,
        "status": "estimated_by_vote",
        "recommended_grams": top_grams,
        "consensus": consensus_tag,
        "high_confidence": agreement_ratio >= 0.66,
        "needs_human_review": True,  # Always flags for Human-in-the-loop Gate
        "voter_details": votes,
    }


def main():
    catalog = load_catalog(Path(DEFAULT_CATALOG))
    test_cases = [
        # (food_id, query, description)
        (
            "2708829",
            "For lunch I had a bowl of pasta with sauce.",
            "Standard colloquial bowl (Tier 1 should match 250g exact)",
        ),
        (
            "2705847",
            "For lunch I had a slice and a half of roast beef.",
            "Fractional portion: 1.5 x slice (60g) = 90g (Tier 2 Vote)",
        ),
        (
            "2705847",
            "I ate a generous portion of roast beef for dinner.",
            "Colloquial modifier: generous portion (Tier 2 Vote)",
        ),
        (
            "2707473",
            "I had two veggie burger patties for lunch.",
            "Countable multiple (Tier 1 should match 200g exact)",
        ),
    ]

    print("=" * 70)
    print("NutriEnv ADR 0019: Multi-Agent Portion Vote Prototype Test")
    print("=" * 70)

    for food_id, query, desc in test_cases:
        print(f"\n[Case]: {desc}")
        print(f"Query: \"{query}\"")
        res = resolve_with_vote_fallback(query, food_id, catalog)
        print(f"Resolver Tier: {res['tier']}")
        if res.get("status") == "resolved_exact":
            print(f"-> Output Grams: {res['grams']} g (Deterministic 0-Drift)")
            print(f"-> Needs Review: {res['needs_human_review']}")
        else:
            print(f"-> Voted Grams: {res.get('recommended_grams')} g")
            print(f"-> Consensus: {res.get('consensus')} (High Confidence: {res.get('high_confidence')})")
            print("-> Voter Breakdown:")
            for v in res.get("voter_details", []):
                if "grams" in v:
                    print(f"   * [{v['model']}]: base_unit={v.get('base_unit')}, multiplier={v.get('multiplier')} -> {v.get('grams')}g | Rationale: {v.get('rationale')}")
                else:
                    print(f"   * [{v.get('model')}]: Error -> {v.get('error')}")
            print(f"-> Needs Human Review: {res['needs_human_review']}")

    print("\n" + "=" * 70)
    print("Prototype test finished.")


if __name__ == "__main__":
    main()
