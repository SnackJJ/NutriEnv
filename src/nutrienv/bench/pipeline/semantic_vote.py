"""Multi-LLM semantic vote: spoken query phrasing ↔ declared pool food.

Generation-time only. Oracle grams stay exact PortionFact table values;
±tolerance admits query phrasing and is never written into the oracle.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from nutrienv.bench.grams_gate import judge_model
from nutrienv.io.chat import (
    DASHSCOPE_CHAT_URL,
    JUDGE_RETRY_ON,
    post_chat_completion,
)
from nutrienv.io.dotenv import load_dotenv_keys

from .resolver import spoken_grams_from_query

__all__ = [
    "DEFAULT_K",
    "DEFAULT_MODEL_IDS",
    "DEFAULT_THRESHOLD",
    "FnddsVoteResult",
    "GRAM_TOLERANCE",
    "MAX_TOKENS",
    "TEMPERATURE",
    "VOTE_SYSTEM",
    "accept_from_votes",
    "admit_query_phrasing",
    "call_voter",
    "parse_vote",
    "sample_votes",
    "semantic_vote",
    "vote_fndds_portion",
]

_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_MODEL_IDS: tuple[str, ...] = (
    "deepseek-v4-flash-0731",
    "qwen3.7-flash-2026-07-15",
)
TEMPERATURE = 0.2
MAX_TOKENS = 256
DEFAULT_K = 3
DEFAULT_THRESHOLD = 2 / 3
GRAM_TOLERANCE = 10.0

VOTE_SYSTEM = """You compare a user's spoken food diary query with one declared
pool food. Decide whether the query's wording is semantically the same food
and the same portion as the declared item.

You do NOT choose gram amounts. Grams are PortionFact table values.

- "match" = the query names that food (or a clear synonym) at that portion.
- "mismatch" = the query names a different food, a different portion, or is
  too vague to treat as the same item.

Answer with a single JSON object and nothing else:
{"verdict": "match" or "mismatch", "reason": "<one short sentence>"}"""

VoteFn = Callable[[str, str, str], str]


def parse_vote(text: str) -> str | None:
    """Return ``match`` / ``mismatch`` from a voter reply, or ``None``."""
    if not text or not str(text).strip():
        return None
    match = re.search(r'"verdict"\s*:\s*"(match|mismatch)"', text, re.I)
    if match:
        return match.group(1).lower()
    stripped = str(text).strip().lower()
    if stripped in {"match", "mismatch"}:
        return stripped
    return None


def format_vote_prompt(query: str, food: str, expression: str) -> str:
    """User message: the spoken query plus the declared pool food.

    The expander ``items`` array is not included; the exam judge never sees it.
    """
    return (
        f"User query:\n{query}\n\n"
        f"Declared pool food: {food}\n"
        f"Declared portion phrase: {expression}\n"
    )


def call_voter(
    query: str,
    food: str,
    expression: str,
    *,
    model: str | None = None,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """One chat completion. Network noise is retried three times."""
    load_dotenv_keys(_ROOT / ".env.local")
    payload = {
        "model": model or judge_model(),
        "messages": [
            {"role": "system", "content": VOTE_SYSTEM},
            {"role": "user", "content": format_vote_prompt(query, food, expression)},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    return post_chat_completion(
        DASHSCOPE_CHAT_URL,
        payload,
        os.environ["DASHSCOPE_API_KEY"],
        timeout=60.0,
        retries=3,
        retry_on=JUDGE_RETRY_ON,
        error_prefix="vote request failed",
    )


def vote_once(
    query: str,
    food: str,
    expression: str,
    *,
    voter: VoteFn | None = None,
    parse_retries: int = 1,
    model: str | None = None,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> tuple[str | None, str]:
    text = ""
    for _attempt in range(1 + parse_retries):
        if voter is None:
            text = (
                call_voter(
                    query,
                    food,
                    expression,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                or ""
            )
        else:
            text = voter(query, food, expression) or ""
        verdict = parse_vote(text)
        if verdict is not None:
            return verdict, text
    return None, text


def sample_votes(
    query: str,
    food: str,
    expression: str,
    *,
    voter: VoteFn | None,
    k: int,
    parse_retries: int = 1,
    models: tuple[str, ...] = DEFAULT_MODEL_IDS,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> list[str]:
    pool = models or DEFAULT_MODEL_IDS
    votes: list[str] = []
    for index in range(k):
        verdict, _text = vote_once(
            query,
            food,
            expression,
            voter=voter,
            parse_retries=parse_retries,
            model=pool[index % len(pool)],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        votes.append("parse_fail" if verdict is None else verdict)
    return votes


def accept_from_votes(votes: list[str], threshold: float) -> bool:
    """Accept when match / K votes meet ``threshold``. Fail-closed.

    ``parse_fail`` stays in the denominator so one parsed ``match`` among
    K=3 cannot become 1/1. Majority is ``ceil(K * 2/3)`` matches.
    """
    if not votes:
        return False
    return votes.count("match") / len(votes) >= threshold


def admit_query_phrasing(
    query: str,
    food_id: str,
    expression: str,
    oracle_grams: float,
    catalog: Mapping,
    *,
    tolerance_g: float = GRAM_TOLERANCE,
) -> bool:
    """True when query grams are missing or within ``tolerance_g`` of oracle.

    A resolvable phrasing outside the band is rejected. The oracle number
    itself is never rewritten here.
    """
    spoken = spoken_grams_from_query(query, food_id, catalog, expression)
    if spoken is None:
        return True
    return abs(spoken - float(oracle_grams)) <= float(tolerance_g)


def semantic_vote(
    query: str,
    *,
    food: str,
    expression: str,
    voter: VoteFn | None = None,
    k: int = DEFAULT_K,
    threshold: float = DEFAULT_THRESHOLD,
    models: tuple[str, ...] = DEFAULT_MODEL_IDS,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    oracle_grams: float | None = None,
    catalog: Mapping | None = None,
    food_id: str | None = None,
    tolerance_g: float = GRAM_TOLERANCE,
    parse_retries: int = 1,
) -> tuple[bool, str]:
    """Soft semantic judgment. Optional phrasing band is generation-only."""
    if oracle_grams is not None and catalog is not None:
        target_id = food_id or food
        if not admit_query_phrasing(
            query,
            target_id,
            expression,
            oracle_grams,
            catalog,
            tolerance_g=tolerance_g,
        ):
            return False, "phrasing"
    votes = sample_votes(
        query,
        food,
        expression,
        voter=voter,
        k=k,
        parse_retries=parse_retries,
        models=models,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return accept_from_votes(votes, threshold), "vote"


from collections import Counter
from dataclasses import dataclass
from nutrienv.io.chat import complete_chat


@dataclass(frozen=True)
class FnddsVoteResult:
    query: str
    food_id: str
    food_name: str
    status: str
    recommended_grams: float | None
    consensus: str
    high_confidence: bool
    needs_human_review: bool
    voter_details: tuple[dict, ...]


def _vote_single_agent(
    model_id: str,
    query: str,
    food_id: str,
    food_name: str,
    portion_table: Mapping[str, float],
    *,
    temperature: float = 0.1,
    max_tokens: int = 256,
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
        raw = complete_chat(
            model_id,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        import json

        data = json.loads(cleaned)
        data["model"] = model_id
        return data
    except Exception as exc:
        return {"model": model_id, "error": str(exc)}


def vote_fndds_portion(
    query: str,
    food_id: str,
    catalog: Mapping,
    *,
    voter_models: tuple[str, ...] = ("qwen3.8-max", "qwen3.8-2.4t-a95b"),
    temperature: float = 0.1,
    max_tokens: int = 256,
) -> FnddsVoteResult:
    """ADR 0019 Multi-Agent Vote: estimate (base_unit, multiplier) on FNDDS portion table."""
    entry = catalog.get(food_id) or {}
    food_name = str(entry.get("name") or food_id)
    portions = entry.get("portions") or {}
    if not isinstance(portions, Mapping) or not portions:
        return FnddsVoteResult(
            query=query,
            food_id=food_id,
            food_name=food_name,
            status="no_portions",
            recommended_grams=None,
            consensus="0/0",
            high_confidence=False,
            needs_human_review=True,
            voter_details=(),
        )

    votes = []
    for model_id in voter_models:
        vote = _vote_single_agent(
            model_id,
            query,
            food_id,
            food_name,
            portions,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        votes.append(vote)

    valid_votes = [
        v for v in votes if "grams" in v and isinstance(v["grams"], (int, float))
    ]
    if not valid_votes:
        return FnddsVoteResult(
            query=query,
            food_id=food_id,
            food_name=food_name,
            status="failed",
            recommended_grams=None,
            consensus="0/0",
            high_confidence=False,
            needs_human_review=True,
            voter_details=tuple(votes),
        )

    gram_counts = Counter(round(float(v["grams"]), 1) for v in valid_votes)
    top_grams, count = gram_counts.most_common(1)[0]
    agreement_ratio = count / len(valid_votes)
    consensus_tag = f"{count}/{len(valid_votes)} ({agreement_ratio:.0%})"

    return FnddsVoteResult(
        query=query,
        food_id=food_id,
        food_name=food_name,
        status="estimated_by_vote",
        recommended_grams=top_grams,
        consensus=consensus_tag,
        high_confidence=agreement_ratio >= 0.66,
        needs_human_review=True,
        voter_details=tuple(votes),
    )

