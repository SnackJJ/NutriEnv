"""Expander: schema, routing, parse retry, and handbook vocabulary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutrienv.bench.pipeline.expander import (
    HANDBOOK_VOCABULARY,
    build_system_prompt,
    coerce_candidates,
    make_llm_expander,
    parse_expander_payload,
    synthetic_expander,
)
from nutrienv.bench.pipeline.models import (
    DEFAULT_EXPANDER_MODEL,
    assign_model,
    enabled_route,
    parse_model_route,
)
from nutrienv.bench.pipeline.types import FoodPool, PoolFood, PortionAlternative
from nutrienv.harness.react import _SYSTEM_V1_TAIL
from nutrienv.io.chat import _message_text
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import resolve_portion

ROOT = Path(__file__).resolve().parents[1]
CATALOG_V1 = ROOT / "data" / "fdc" / "catalog-v1.sqlite"

_OK = {
    "items": [{"food": "milk", "expression": "a cup"}],
    "query": "Please log a cup of milk for lunch.",
}


def _pool() -> FoodPool:
    return FoodPool(
        pool_id="log-0000",
        family="log",
        foods=(
            PoolFood(
                food_id="milk_whole",
                name="Milk, whole",
                aliases=("milk", "whole milk"),
                alternatives=(
                    PortionAlternative("cup", 1.0, "a cup", 244.0),
                    PortionAlternative("cup", 2.0, "two cups", 488.0),
                ),
            ),
            PoolFood(
                food_id="egg",
                name="Egg, whole",
                aliases=("egg", "eggs"),
                alternatives=(
                    PortionAlternative("piece", 1.0, "a piece", 50.0),
                    PortionAlternative("piece", 2.0, "two pieces", 100.0),
                ),
            ),
            PoolFood(
                food_id="chicken_breast",
                name="Chicken breast",
                aliases=("chicken", "chicken breast"),
                alternatives=(
                    PortionAlternative("piece", 1.0, "a piece", 172.0),
                ),
            ),
        ),
    )


def _ok_json(query: str = _OK["query"]) -> str:
    return json.dumps(
        {"items": [{"food": "milk", "expression": "a cup"}], "query": query}
    )


def _complete_with(replies):
    it = iter(replies)

    def complete(model_id, messages):
        item = next(it)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(model_id, messages)
        return item

    return complete


def _tracking_complete(seen: list[str], query_for=None):
    def complete(model_id, messages):
        seen.append(model_id)
        query = query_for(model_id) if query_for else f"Please log a cup of milk via {model_id}."
        return _ok_json(query)

    return complete


@pytest.fixture(scope="module")
def catalog_v1():
    if not CATALOG_V1.is_file():
        pytest.fail("data/fdc/catalog-v1.sqlite is missing")
    return load_catalog(CATALOG_V1)


def test_coerce_candidates_accepts_fixed_schema() -> None:
    got = coerce_candidates(
        _OK, family="log", persona="everyday", pool_id="log-0000"
    )
    assert len(got) == 1
    assert got[0].items == (("milk", "a cup"),)
    assert got[0].query == _OK["query"]


def test_coerce_candidates_drops_malformed() -> None:
    assert (
        coerce_candidates(
            {"items": [], "query": "x"},
            family="log",
            persona="everyday",
            pool_id="p",
        )
        == []
    )
    assert (
        coerce_candidates("not-a-mapping", family="log", persona="everyday", pool_id="p")
        == []
    )
    assert (
        coerce_candidates(
            {"items": [{"food": "milk"}], "query": "log milk"},
            family="log",
            persona="everyday",
            pool_id="p",
        )
        == []
    )


def test_parse_expander_payload_accepts_fenced_json() -> None:
    raw = "Here you go:\n```json\n" + _ok_json() + "\n```\n"
    assert parse_expander_payload(raw) == {
        "items": [{"food": "milk", "expression": "a cup"}],
        "query": _OK["query"],
    }


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "{}",
        '{"query": "hi"}',
        '{"items": [], "query": "hi"}',
        '{"items": [{"food": "milk"}], "query": "hi"}',
        '{"items": [{"food": "", "expression": "a cup"}], "query": "hi"}',
        '{"items": [{"food": "milk", "expression": "a cup"}], "query": "  "}',
    ],
    ids=["empty", "prose", "no-keys", "no-items", "empty-items", "no-expr", "blank-food", "blank-query"],
)
def test_parse_expander_payload_rejects_structural_damage(raw) -> None:
    assert parse_expander_payload(raw) is None


def test_parse_model_route_dict_is_stable_by_key() -> None:
    route = parse_model_route({"b": "model-b", "a": "model-a"})
    assert route == ("model-a", "model-b")
    assert parse_model_route(["model-a", "model-b"]) == ("model-a", "model-b")
    assert parse_model_route({}) == ()
    assert parse_model_route(None) == ()


def test_assign_model_is_deterministic_for_seed_and_route() -> None:
    route = ("model-a", "model-b", "model-c")
    first = [assign_model(index, route, seed=42) for index in range(6)]
    second = [assign_model(index, route, seed=42) for index in range(6)]
    assert first == second
    assert first[0] == route[(42 + 0) % 3]
    assert first[1] == route[(42 + 1) % 3]


def test_routing_same_seed_same_table_same_assignment() -> None:
    route = ["model-a", "model-b", "model-c"]
    seen_a: list[str] = []
    seen_b: list[str] = []
    left = make_llm_expander(
        model_route=route, seed=7, complete=_tracking_complete(seen_a)
    )
    right = make_llm_expander(
        model_route=route, seed=7, complete=_tracking_complete(seen_b)
    )
    pool = _pool()
    for _ in range(5):
        left(pool, persona="everyday", family="log")
        right(pool, persona="everyday", family="log")
    assert seen_a == seen_b
    assert seen_a == [assign_model(index, tuple(route), seed=7) for index in range(5)]


def test_stub_models_return_distinguishable_queries() -> None:
    seen: list[str] = []
    expander = make_llm_expander(
        model_route=["alpha-model", "beta-model"],
        seed=0,
        complete=_tracking_complete(seen),
    )
    pool = _pool()
    first = expander(pool, persona="everyday", family="log")
    second = expander(pool, persona="everyday", family="log")
    assert first["query"] != second["query"]
    assert "alpha-model" in first["query"]
    assert "beta-model" in second["query"]
    assert seen == ["alpha-model", "beta-model"]


def test_empty_model_route_falls_back_to_default() -> None:
    seen: list[str] = []
    expander = make_llm_expander(
        model_route={}, seed=0, complete=_tracking_complete(seen)
    )
    expander(_pool(), persona="everyday", family="log")
    assert seen == [DEFAULT_EXPANDER_MODEL]


def test_retry_on_parse_failure_then_succeeds() -> None:
    complete = _complete_with(["not-json {", _ok_json()])
    expander = make_llm_expander(
        model_route=["stub"], seed=0, complete=complete, parse_retries=1
    )
    payload = expander(_pool(), persona="everyday", family="log")
    assert payload["items"][0]["food"] == "milk"
    assert payload["query"] == _OK["query"]


def test_malformed_after_retry_is_failed_candidate_not_crash() -> None:
    expander = make_llm_expander(
        model_route=["stub"],
        seed=0,
        complete=_complete_with(["nope", "still nope"]),
        parse_retries=1,
    )
    raw = expander(_pool(), persona="everyday", family="log")
    assert parse_expander_payload(json.dumps(raw) if isinstance(raw, dict) else raw) is None
    got = coerce_candidates(raw, family="log", persona="everyday", pool_id="log-0000")
    assert got == []


def test_network_exception_is_not_swallowed() -> None:
    expander = make_llm_expander(
        model_route=["stub"],
        seed=0,
        complete=_complete_with([RuntimeError("stub request failed: timeout")]),
    )
    with pytest.raises(RuntimeError, match="request failed"):
        expander(_pool(), persona="everyday", family="log")


def test_disabled_models_are_skipped() -> None:
    seen: list[str] = []
    expander = make_llm_expander(
        model_route=["dead-model", "live-model"],
        seed=0,
        complete=_tracking_complete(seen),
        disabled=["dead-model"],
    )
    expander(_pool(), persona="everyday", family="log")
    assert seen == ["live-model"]


def test_all_disabled_models_raise_clearly() -> None:
    with pytest.raises(RuntimeError, match="no enabled expander models"):
        make_llm_expander(
            model_route=["dead-a", "dead-b"],
            seed=0,
            complete=_tracking_complete([]),
            disabled=["dead-a", "dead-b"],
        )


def test_enabled_route_filters_disabled() -> None:
    assert enabled_route(("a", "b", "c"), {"b"}) == ("a", "c")
    assert enabled_route(("a",), {"a"}) == ()


def test_prompt_lists_handbook_vocabulary() -> None:
    prompt = build_system_prompt(persona="everyday", family="log")
    missing = [token for token in HANDBOOK_VOCABULARY if token.lower() not in prompt.lower()]
    assert missing == [], missing
    lowered = prompt.lower()
    assert "food_id" in lowered
    assert "slug" in lowered
    assert "kcal" in lowered or "window" in lowered
    assert "protein_g" in lowered or "window" in lowered
    assert "numeric" in lowered or "answer" in lowered


def test_handbook_vocabulary_is_covered_by_react_manual() -> None:
    tail = _SYSTEM_V1_TAIL.lower()
    # Handbook wording uses "ounce" / "Grams" / "150 g" rather than every plural.
    aliases = {
        "ounces": "ounce",
        "grams": "gram",
        "a serving of": "a serving",
    }
    missing = []
    for token in HANDBOOK_VOCABULARY:
        needle = aliases.get(token, token).lower()
        if needle not in tail:
            missing.append(token)
    assert missing == [], missing


def test_gym_prompt_allows_grams_everyday_does_not() -> None:
    gym = build_system_prompt(persona="gym", family="log").lower()
    everyday = build_system_prompt(persona="everyday", family="log").lower()
    assert "150 g" in gym or "grams" in gym
    assert "mix" in gym or "gram" in gym
    assert "do not use grams" in everyday or "except the gym" in everyday


def test_prompt_forbids_slugs_windows_and_numeric_answers() -> None:
    prompt = build_system_prompt(persona="everyday", family="log").lower()
    for needle in ("food_id", "slug", "window", "kcal"):
        assert needle in prompt
    assert "json" in prompt


def test_stub_expressions_resolve_on_catalog_v1(catalog_v1) -> None:
    phrases = (
        ("milk_whole", "a cup"),
        ("egg", "two pieces"),
        ("apple", "a serving of"),
        ("chicken_breast", "150 g"),
        ("oats", "2 ounces"),
        ("milk_whole", "a serving of"),
    )
    for food_id, expression in phrases:
        grams = resolve_portion(food_id, expression, catalog_v1)
        assert grams is not None and grams > 0, (food_id, expression)

    seen: list[str] = []

    def complete(model_id, messages):
        seen.append(model_id)
        return json.dumps(
            {
                "items": [
                    {"food": "milk", "expression": "a cup"},
                    {"food": "eggs", "expression": "two pieces"},
                ],
                "query": "Please log a cup of milk and two eggs.",
            }
        )

    expander = make_llm_expander(model_route=["stub"], seed=0, complete=complete)
    payload = expander(_pool(), persona="everyday", family="log")
    for item in payload["items"]:
        food = "milk_whole" if "milk" in item["food"] else "egg"
        grams = resolve_portion(food, item["expression"], catalog_v1)
        assert grams is not None and grams > 0


def test_message_text_falls_back_to_reasoning_content() -> None:
    body = {
        "choices": [
            {"message": {"content": "", "reasoning_content": _ok_json()}}
        ]
    }
    assert parse_expander_payload(_message_text(body)) is not None
    assert _message_text({"choices": [{"message": {"content": "hello"}}]}) == "hello"
    assert _message_text({}) == ""


def test_synthetic_expander_still_deterministic() -> None:
    pool = _pool()
    assert synthetic_expander(pool, persona="everyday", family="log") == (
        synthetic_expander(pool, persona="everyday", family="log")
    )
