"""Pipeline composite family: fake expander → resolver → gates → freeze."""

from __future__ import annotations

from pathlib import Path

from nutrienv.bench.pipeline import catalog_digest, pass_through_reviewer, run_batch
from nutrienv.bench.pipeline.expander import (
    build_system_prompt,
    coerce_candidates,
    parse_expander_payload,
    synthetic_expander,
)
from nutrienv.bench.pipeline.types import COMPOSITE_STEPS, FoodPool, PoolFood, PortionAlternative
from nutrienv.bench.split import load_split


def _catalog() -> dict:
    return {
        "apple": {
            "name": "Apple, raw",
            "portions": {"piece": 182.0},
            "aliases": ["apple", "apples"],
            "allergen_tags": [],
            "nutrients": {"kcal": 52.0, "protein_g": 0.3},
        },
        "orange": {
            "name": "Orange, raw",
            "portions": {"piece": 131.0},
            "aliases": ["orange", "oranges"],
            "allergen_tags": [],
            "nutrients": {"kcal": 47.0, "protein_g": 0.9},
        },
        "milk_whole": {
            "name": "Milk, whole",
            "portions": {"cup": 244.0},
            "aliases": ["milk", "whole milk"],
            "allergen_tags": ["milk"],
            "nutrients": {"kcal": 61.0, "protein_g": 3.2},
        },
        "oats": {
            "name": "Oats, rolled",
            "portions": {"cup": 81.0},
            "aliases": ["oatmeal", "oats"],
            "allergen_tags": [],
            "nutrients": {"kcal": 389.0, "protein_g": 16.9},
        },
        "banana": {
            "name": "Banana, raw",
            "portions": {"piece": 118.0},
            "aliases": ["banana", "bananas"],
            "allergen_tags": [],
            "nutrients": {"kcal": 89.0, "protein_g": 1.1},
        },
        "chicken_breast": {
            "name": "Chicken breast",
            "portions": {"piece": 172.0},
            "aliases": ["chicken"],
            "allergen_tags": [],
            "nutrients": {"kcal": 165.0, "protein_g": 31.0},
        },
        "white_rice": {
            "name": "Rice, white",
            "portions": {"cup": 158.0},
            "aliases": ["rice"],
            "allergen_tags": [],
            "nutrients": {"kcal": 130.0, "protein_g": 2.7},
        },
        "broccoli": {
            "name": "Broccoli, cooked",
            "portions": {"cup": 156.0},
            "aliases": ["broccoli"],
            "allergen_tags": [],
            "nutrients": {"kcal": 34.0, "protein_g": 2.8},
        },
        "olive_oil": {
            "name": "Olive oil",
            "portions": {"tbsp": 13.5},
            "aliases": ["olive oil"],
            "allergen_tags": [],
            "nutrients": {"kcal": 884.0, "protein_g": 0.0},
        },
        "egg": {
            "name": "Egg, whole",
            "portions": {"piece": 50.0},
            "aliases": ["eggs", "egg"],
            "allergen_tags": ["egg"],
            "nutrients": {"kcal": 143.0, "protein_g": 12.6},
        },
        "tofu": {
            "name": "Tofu, firm",
            "portions": {"piece": 80.0},
            "aliases": ["tofu"],
            "allergen_tags": ["soy"],
            "nutrients": {"kcal": 144.0, "protein_g": 17.3},
        },
    }


def _expander(payloads):
    def expand(_pool, *, persona, family):
        return payloads

    return expand


def _ok_judge(_food: str, _grams: float) -> str:
    return "ok"


_COMPOSITE = {
    "items": [{"food": "milk_whole", "expression": "a cup"}],
    "query": "Please log a cup of milk for lunch, then recommend a dinner that fits what's left.",
    "steps": ["log", "recommend"],
}


def test_synthetic_expander_composite_emits_steps():
    pool = FoodPool(
        pool_id="composite-0000",
        family="composite",
        foods=(
            PoolFood(
                "milk_whole",
                "Milk, whole",
                ("milk",),
                (PortionAlternative("cup", 1.0, "a cup", 244.0),),
            ),
        ),
    )
    payload = synthetic_expander(pool, persona="everyday", family="composite")
    assert payload["steps"] == list(COMPOSITE_STEPS)
    assert "log" in payload["query"].lower()
    assert "recommend" in payload["query"].lower() or "dinner" in payload["query"].lower()
    got = coerce_candidates(
        payload, family="composite", persona="everyday", pool_id=pool.pool_id
    )
    assert len(got) == 1
    assert got[0].steps == COMPOSITE_STEPS
    assert got[0].family == "composite"


def test_parse_expander_payload_keeps_steps():
    parsed = parse_expander_payload(
        '{"items":[{"food":"milk","expression":"a cup"}],'
        '"query":"Log a cup of milk then recommend dinner.",'
        '"steps":["log","recommend"]}'
    )
    assert parsed is not None
    assert parsed["steps"] == ["log", "recommend"]


def test_composite_prompt_asks_for_both_steps():
    prompt = build_system_prompt(persona="everyday", family="composite")
    lowered = prompt.lower()
    assert "log" in lowered and "recommend" in lowered
    assert '"steps"' in prompt or "steps" in lowered


def test_fake_expander_composite_passes_end_to_end(tmp_path: Path) -> None:
    catalog = _catalog()
    spec = {
        "seed": 7,
        "sampler_rule_version": "sampler-v1",
        "catalog_sha": catalog_digest(catalog),
        "persona": "everyday",
        "family_quotas": {"composite": 1},
        "catalog": "fixture",
        "output_path": tmp_path / "v1.0-composite-sample.json",
        "version": "v1.0-composite-sample",
    }
    result = run_batch(
        spec,
        expander=_expander([_COMPOSITE]),
        judge=_ok_judge,
        reviewer=pass_through_reviewer,
        catalog=catalog,
    )
    assert len(result.accepted) == 1
    task = result.accepted[0]
    assert task.family == "log"
    assert task.oracle.sub_oracles is not None
    assert len(task.oracle.sub_oracles) == 2
    log_oracle, rec_oracle = task.oracle.sub_oracles
    assert log_oracle.ledger_tail
    assert log_oracle.ledger_tail[0].grams == 244.0
    assert rec_oracle.last_plan == []
    assert rec_oracle.plan_must_be_safe
    assert rec_oracle.plan_windows is not None
    assert "kcal" in rec_oracle.plan_windows
    ledger = result.payload["quota_ledger"]
    assert ledger["exam_quota"] == 240
    assert ledger["composite_admission_slots"] == 36
    assert ledger["composite_accepted"] == 1
    assert ledger["single_family_accepted"] == {}
    assert ledger["requested"] == {"composite": 1}
    assert result.path is not None
    loaded = load_split(result.path, catalog=catalog)
    assert loaded[0].oracle.sub_oracles is not None
    assert loaded[0].query == _COMPOSITE["query"]


def test_unsupported_composite_steps_are_rejected(tmp_path: Path) -> None:
    catalog = _catalog()
    bad = {
        "items": [{"food": "milk_whole", "expression": "a cup"}],
        "query": "Please log a cup of milk and then evaluate it.",
        "steps": ["log", "evaluate"],
    }
    spec = {
        "seed": 7,
        "sampler_rule_version": "sampler-v1",
        "catalog_sha": catalog_digest(catalog),
        "persona": "everyday",
        "family_quotas": {"composite": 1},
        "catalog": "fixture",
        "output_path": tmp_path / "out.json",
    }
    result = run_batch(
        spec,
        expander=_expander([bad]),
        judge=_ok_judge,
        reviewer=pass_through_reviewer,
        catalog=catalog,
    )
    assert result.accepted == []
    assert any(item.reason == "unresolvable" for item in result.rejected)


def test_base_and_composite_quotas_stay_separate(tmp_path: Path) -> None:
    catalog = _catalog()
    log_payload = {
        "items": [{"food": "oats", "expression": "a cup"}],
        "query": "Please log a cup of oats for lunch.",
    }
    calls = {"n": 0}

    def expand(_pool, *, persona, family):
        calls["n"] += 1
        if family == "composite":
            return [_COMPOSITE]
        return [log_payload]

    spec = {
        "seed": 7,
        "sampler_rule_version": "sampler-v1",
        "catalog_sha": catalog_digest(catalog),
        "persona": "everyday",
        "family_quotas": {"log": 1, "composite": 1},
        "catalog": "fixture",
        "output_path": tmp_path / "mixed.json",
    }
    result = run_batch(
        spec,
        expander=expand,
        judge=_ok_judge,
        reviewer=pass_through_reviewer,
        catalog=catalog,
    )
    assert calls["n"] >= 2
    ledger = result.payload["quota_ledger"]
    assert ledger["single_family_accepted"].get("log") == 1
    assert ledger["composite_accepted"] == 1
    assert sum(1 for task in result.accepted if task.oracle.sub_oracles) == 1
    assert sum(1 for task in result.accepted if not task.oracle.sub_oracles) == 1
