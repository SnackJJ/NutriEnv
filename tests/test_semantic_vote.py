"""Ticket 10: injectable multi-LLM semantic vote at the generation seam."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutrienv.bench import Oracle, Scorer
from nutrienv.bench.pipeline import catalog_digest
from nutrienv.bench.pipeline.legacy_run_batch import pass_through_reviewer, run_batch
from nutrienv.bench.pipeline.expander import validate_expander_payload
from nutrienv.bench.pipeline.semantic_vote import (
    DEFAULT_K,
    DEFAULT_MODEL_IDS,
    DEFAULT_THRESHOLD,
    GRAM_TOLERANCE,
    MAX_TOKENS,
    TEMPERATURE,
    accept_from_votes,
    admit_query_phrasing,
    call_voter,
    semantic_vote,
)
from nutrienv.bench.pipeline.types import FoodPool, PoolFood, PortionAlternative
from nutrienv.io.chat import DASHSCOPE_CHAT_URL
from nutrienv.world.types import LedgerRow, Profile, WorldState


def _seq_voter(replies):
    it = iter(replies)

    def fake(_query: str, _food: str, _expression: str) -> str:
        return next(it)

    return fake


def _const_voter(text: str):
    def fake(_query: str, _food: str, _expression: str) -> str:
        return text

    return fake


def test_default_vote_parameters() -> None:
    assert DEFAULT_K == 3
    assert DEFAULT_THRESHOLD == pytest.approx(2 / 3)
    assert TEMPERATURE == 0.2
    assert MAX_TOKENS == 256
    assert DEFAULT_MODEL_IDS == (
        "deepseek-v4-flash-0731",
        "qwen3.7-flash-2026-07-15",
    )
    assert GRAM_TOLERANCE == 10.0


def test_majority_two_of_three_accepts() -> None:
    accepted, source = semantic_vote(
        "Please log a banana.",
        food="banana",
        expression="one banana",
        voter=_seq_voter(["match", "mismatch", "match"]),
        k=3,
        threshold=2 / 3,
    )
    assert accepted is True
    assert source == "vote"


def test_majority_below_two_of_three_rejects() -> None:
    accepted, source = semantic_vote(
        "Please log a banana.",
        food="banana",
        expression="one banana",
        voter=_seq_voter(["match", "mismatch", "mismatch"]),
        k=3,
        threshold=2 / 3,
    )
    assert accepted is False
    assert source == "vote"


def test_parse_fail_is_fail_closed() -> None:
    accepted, _source = semantic_vote(
        "Please log a banana.",
        food="banana",
        expression="one banana",
        voter=_const_voter("not-json"),
        k=3,
    )
    assert accepted is False


def test_accept_from_votes_uses_majority() -> None:
    assert accept_from_votes(["match", "match", "mismatch"], 2 / 3) is True
    assert accept_from_votes(["match", "mismatch", "mismatch"], 2 / 3) is False
    assert accept_from_votes(["parse_fail", "parse_fail", "parse_fail"], 2 / 3) is False


def test_one_match_two_parse_fail_is_rejected() -> None:
    """parse_fail must not shrink the K=3 denominator (codex 10 rework)."""
    assert accept_from_votes(["match", "parse_fail", "parse_fail"], 2 / 3) is False
    accepted, source = semantic_vote(
        "Please log a banana.",
        food="banana",
        expression="one banana",
        voter=_seq_voter(["match", "not-json", "still-not-json"]),
        k=3,
        threshold=2 / 3,
        parse_retries=0,
    )
    assert accepted is False
    assert source == "vote"


def _capture_post(monkeypatch):
    captured: dict = {}

    def fake_post(url, payload, api_key, **_kwargs):
        captured["url"] = url
        captured["model"] = payload["model"]
        captured["temperature"] = payload["temperature"]
        captured["max_tokens"] = payload["max_tokens"]
        captured["api_key"] = api_key
        captured["messages"] = payload["messages"]
        return '{"verdict": "match", "reason": "same fruit"}'

    monkeypatch.setattr(
        "nutrienv.bench.pipeline.semantic_vote.post_chat_completion", fake_post
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-dummy")
    return captured


def test_injected_k1_accepts_on_single_match() -> None:
    accepted, source = semantic_vote(
        "Please log a banana.",
        food="banana",
        expression="one banana",
        voter=_const_voter("match"),
        k=1,
        threshold=1.0,
    )
    assert accepted is True
    assert source == "vote"


def test_injected_unanimous_threshold_rejects_two_of_three() -> None:
    accepted, source = semantic_vote(
        "Please log a banana.",
        food="banana",
        expression="one banana",
        voter=_seq_voter(["match", "match", "mismatch"]),
        k=3,
        threshold=1.0,
    )
    assert accepted is False
    assert source == "vote"


def test_call_voter_honors_injected_model_temp_and_tokens(monkeypatch) -> None:
    captured = _capture_post(monkeypatch)
    text = call_voter(
        "Please log a banana.",
        "banana",
        "one banana",
        model="qwen3.7-flash-2026-07-15",
        temperature=0.5,
        max_tokens=64,
    )
    assert json.loads(text)["verdict"] == "match"
    assert captured["model"] == "qwen3.7-flash-2026-07-15"
    assert captured["temperature"] == 0.5
    assert captured["max_tokens"] == 64


def test_call_voter_posts_judge_grade_defaults(monkeypatch) -> None:
    captured = _capture_post(monkeypatch)
    monkeypatch.delenv("NUTRIENV_JUDGE_MODEL", raising=False)
    text = call_voter("Please log a banana.", "banana", "one banana")
    assert json.loads(text)["verdict"] == "match"
    assert captured["model"] == "deepseek-v4-flash-0731"
    assert captured["url"] == DASHSCOPE_CHAT_URL
    assert captured["temperature"] == 0.2
    assert captured["max_tokens"] == 256
    user = captured["messages"][1]["content"]
    assert "Please log a banana." in user
    assert '"items"' not in user


def test_admit_phrasing_within_tolerance_keeps_oracle_grams() -> None:
    catalog = {"milk_whole": {"name": "Milk, whole", "portions": {"cup": 244.0}}}
    assert (
        admit_query_phrasing(
            "Please log 240 g of milk.",
            "milk_whole",
            "a cup",
            244.0,
            catalog,
            tolerance_g=10.0,
        )
        is True
    )
    assert (
        admit_query_phrasing(
            "Please log 200 g of milk.",
            "milk_whole",
            "a cup",
            244.0,
            catalog,
            tolerance_g=10.0,
        )
        is False
    )


def _batch_catalog() -> dict:
    return {
        "apple": {
            "name": "Apple, raw",
            "portions": {"piece": 182.0},
            "aliases": ["apple", "apples"],
            "allergen_tags": [],
        },
        "orange": {
            "name": "Orange, raw",
            "portions": {"piece": 131.0},
            "aliases": ["orange", "oranges"],
            "allergen_tags": [],
        },
        "milk_whole": {
            "name": "Milk, whole",
            "portions": {"cup": 244.0},
            "aliases": ["milk", "whole milk"],
            "allergen_tags": ["milk"],
        },
        "oats": {
            "name": "Oats, rolled",
            "portions": {"cup": 81.0},
            "aliases": ["oatmeal", "oats"],
            "allergen_tags": [],
        },
        "banana": {
            "name": "Banana, raw",
            "portions": {"piece": 118.0},
            "aliases": ["banana", "bananas"],
            "allergen_tags": [],
        },
        "egg": {
            "name": "Egg, whole",
            "portions": {"piece": 50.0},
            "aliases": ["egg", "eggs"],
            "allergen_tags": ["egg"],
        },
        "white_rice": {
            "name": "Rice, white",
            "portions": {"cup": 158.0},
            "aliases": ["rice"],
            "allergen_tags": [],
        },
        "broccoli": {
            "name": "Broccoli, cooked",
            "portions": {"cup": 156.0},
            "aliases": ["broccoli"],
            "allergen_tags": [],
        },
        "chicken_breast": {
            "name": "Chicken breast",
            "portions": {"piece": 172.0},
            "aliases": ["chicken"],
            "allergen_tags": [],
        },
        "tofu": {
            "name": "Tofu, firm",
            "portions": {"piece": 80.0},
            "aliases": ["tofu"],
            "allergen_tags": ["soy"],
        },
    }


def _expander(payloads):
    def expand(_pool, *, persona, family):
        return payloads

    return expand


def _ok_judge(_food: str, _grams: float) -> str:
    return "ok"


_VOTE_KW = {
    "vote_k",
    "vote_threshold",
    "vote_models",
    "vote_temperature",
    "vote_max_tokens",
    "enable_semantic_vote",
}


def _run(tmp_path: Path, payloads, *, voter=None, catalog=None, **overrides):
    foods = catalog if catalog is not None else _batch_catalog()
    spec = {
        "seed": 7,
        "sampler_rule_version": "sampler-v1",
        "catalog_sha": catalog_digest(foods),
        "persona": "everyday",
        "family_quotas": {"log": 1},
        "model_route": {},
        "catalog": "fixture",
        "output_path": tmp_path / "batch.json",
        "overwrite": True,
    }
    batch_kwargs = {key: overrides.pop(key) for key in list(overrides) if key in _VOTE_KW}
    spec.update(overrides)
    return run_batch(
        spec,
        expander=_expander(payloads),
        judge=_ok_judge,
        reviewer=pass_through_reviewer,
        catalog=foods,
        voter=voter,
        **batch_kwargs,
    )


_MILK_PAYLOAD = {
    "items": [{"food": "milk_whole", "expression": "a cup"}],
    "query": "Please log a cup of milk for lunch.",
}


def test_run_batch_k1_calls_voter_once(tmp_path: Path) -> None:
    calls: list[tuple[str, str, str]] = []

    def voter(query: str, food: str, expression: str) -> str:
        calls.append((query, food, expression))
        return '{"verdict": "match"}'

    result = _run(tmp_path, [_MILK_PAYLOAD], voter=voter, vote_k=1)
    assert len(result.accepted) == 1
    assert len(calls) == 1


def test_run_batch_unanimous_threshold_rejects_split_vote(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [_MILK_PAYLOAD],
        voter=_seq_voter(["match", "match", "mismatch"]),
        vote_k=3,
        vote_threshold=1.0,
    )
    assert result.accepted == []
    assert any(item.reason == "semantic" for item in result.rejected)


def test_run_batch_injects_model_pool_temp_and_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts: list = []
    _install_production_voter(monkeypatch, posts)
    result = _run(
        tmp_path,
        [_MILK_PAYLOAD],
        voter=None,
        enable_semantic_vote=True,
        vote_k=3,
        vote_models=("alpha-vote", "beta-vote"),
        vote_temperature=0.5,
        vote_max_tokens=64,
    )
    assert len(result.accepted) == 1
    assert [item["model"] for item in posts] == [
        "alpha-vote",
        "beta-vote",
        "alpha-vote",
    ]
    assert all(item["temperature"] == 0.5 for item in posts)
    assert all(item["max_tokens"] == 64 for item in posts)


def test_voter_replaces_hard_backresolve_and_keeps_oracle_bytes(tmp_path: Path) -> None:
    payload = {
        "items": [{"food": "milk_whole", "expression": "a cup"}],
        "query": "Please log 240 g of milk for lunch.",
    }
    result = _run(tmp_path, [payload], voter=_const_voter('{"verdict": "match"}'))
    assert len(result.accepted) == 1
    row = result.accepted[0].oracle.ledger_tail[0]
    assert row.grams == 244.0
    oracle = result.payload["items"][0]["oracle"]
    grams = [item["grams"] for item in oracle["ledger_tail"]]
    assert grams == [244.0]
    assert json.dumps(grams) == "[244.0]"


def test_discipline_5_scorer_stays_exact_end_state() -> None:
    catalog = _batch_catalog()
    s0 = WorldState(profile=Profile(user_id="exact"), catalog=catalog, ledger=[])
    oracle = Oracle(ledger_tail=[LedgerRow("milk_whole", 244.0, "today-lunch")])
    passed = WorldState(
        profile=s0.profile,
        catalog=catalog,
        ledger=[LedgerRow("milk_whole", 244.0, "today-lunch")],
    )
    close = WorldState(
        profile=s0.profile,
        catalog=catalog,
        ledger=[LedgerRow("milk_whole", 240.0, "today-lunch")],
    )
    miss = WorldState(
        profile=s0.profile,
        catalog=catalog,
        ledger=[LedgerRow("milk_whole", 200.0, "today-lunch")],
    )
    assert Scorer().score(passed, oracle)["passed"] is True
    # 240 g vs gold 244 g is inside ±15% (ADR 0029); 200 g is not.
    assert Scorer().score(close, oracle)["passed"] is True
    assert Scorer().score(miss, oracle)["passed"] is False
    assert Scorer().score(miss, oracle)["tag"] == "log_miss"


def test_deterministic_leak_still_rejects_when_voter_would_pass(tmp_path: Path) -> None:
    leak = {
        "items": [{"food": "milk_whole", "expression": "a cup"}],
        "query": "Please log a cup of milk_whole for lunch.",
    }
    result = _run(tmp_path, [leak], voter=_const_voter('{"verdict": "match"}'))
    assert result.accepted == []
    assert any(item.reason == "leak" for item in result.rejected)


def test_deterministic_pool_check_stays_independent_of_vote() -> None:
    pool = FoodPool(
        pool_id="log-0000",
        family="log",
        foods=(
            PoolFood(
                food_id="milk_whole",
                name="Milk, whole",
                aliases=("milk",),
                alternatives=(PortionAlternative("cup", 1.0, "a cup", 244.0),),
            ),
        ),
    )
    outsider = {
        "items": [{"food": "steak", "expression": "a cup"}],
        "query": "Please log a cup of steak.",
    }
    assert validate_expander_payload(outsider, pool)
    accepted, _source = semantic_vote(
        outsider["query"],
        food="steak",
        expression="a cup",
        voter=_const_voter('{"verdict": "match"}'),
    )
    assert accepted is True


GRAY_CASES = (
    ("sandwich", 175.0, 115.0, "a piece", "a sandwich"),
    ("lasagna", 206.0, 250.0, "a piece", "a lasagna"),
    ("omelet", 55.0, 110.0, "a piece", "an omelet"),
)


def _gray_foods() -> dict:
    return {
        "sandwich": {
            "name": "Sandwich",
            "portions": {"piece": 175.0, "qns": 115.0},
            "aliases": ["sandwich"],
            "allergen_tags": [],
        },
        "lasagna": {
            "name": "Lasagna",
            "portions": {"piece": 206.0, "qns": 250.0},
            "aliases": ["lasagna"],
            "allergen_tags": [],
        },
        "omelet": {
            "name": "Egg omelet",
            "portions": {"piece": 55.0, "qns": 110.0},
            "aliases": ["omelet"],
            "allergen_tags": [],
        },
    }


def _gray_catalog() -> dict:
    return {**_batch_catalog(), **_gray_foods()}


def _install_production_voter(monkeypatch, posts: list, *, force_match: bool = False):
    """Route run_batch through production ``call_voter`` (K=3, DashScope)."""

    def fake_post(url, payload, api_key, **_kwargs):
        posts.append(payload)
        if force_match:
            return '{"verdict": "match", "reason": "forced"}'
        user = payload["messages"][1]["content"]
        query = user.split("User query:\n", 1)[-1].split("\n\n", 1)[0]
        declared = ""
        for line in user.splitlines():
            if line.startswith("Declared portion phrase:"):
                declared = line.split(":", 1)[1].strip()
                break
        if declared and declared.lower() in query.lower():
            return '{"verdict": "match", "reason": "query speaks the declared phrase"}'
        return '{"verdict": "mismatch", "reason": "query does not speak the declared phrase"}'

    monkeypatch.setattr(
        "nutrienv.bench.pipeline.semantic_vote.post_chat_completion", fake_post
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-dummy")


@pytest.mark.parametrize("food,piece,qns,piece_expr,other_query", GRAY_CASES)
def test_gray_zone_spoken_phrasing_is_not_false_rejected(
    tmp_path: Path, monkeypatch, food, piece, qns, piece_expr, other_query
) -> None:
    posts: list = []
    _install_production_voter(monkeypatch, posts)
    query = f"Please log {piece_expr} of {food}."
    result = _run(
        tmp_path,
        [{"items": [{"food": food, "expression": piece_expr}], "query": query}],
        voter=call_voter,
        catalog=_gray_catalog(),
        output_path=tmp_path / f"{food}-piece.json",
    )
    assert len(result.accepted) == 1
    assert result.accepted[0].oracle.ledger_tail[0].grams == piece
    assert len(posts) == DEFAULT_K
    assert all(item["max_tokens"] == MAX_TOKENS for item in posts)
    assert all(item["temperature"] == TEMPERATURE for item in posts)
    assert (
        admit_query_phrasing(query, food, piece_expr, piece, _gray_foods()) is True
    )
    assert abs(piece - qns) > GRAM_TOLERANCE


@pytest.mark.parametrize("food,piece,qns,piece_expr,other_query", GRAY_CASES)
def test_gray_zone_other_portion_is_not_admitted_via_tolerance(
    tmp_path: Path, monkeypatch, food, piece, qns, piece_expr, other_query
) -> None:
    posts: list = []
    _install_production_voter(monkeypatch, posts, force_match=True)
    query = f"Please log {other_query}."
    result = _run(
        tmp_path,
        [{"items": [{"food": food, "expression": piece_expr}], "query": query}],
        voter=call_voter,
        catalog=_gray_catalog(),
        output_path=tmp_path / f"{food}-other.json",
    )
    assert result.accepted == []
    assert any(item.reason == "semantic" for item in result.rejected)
    assert posts == []
    assert (
        admit_query_phrasing(query, food, piece_expr, piece, _gray_foods()) is False
    )
