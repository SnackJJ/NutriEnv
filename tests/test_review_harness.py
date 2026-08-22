"""Two-stage review committee: Stage A code-gate then injected voters."""

from __future__ import annotations

import pytest

from nutrienv.io.chat import DASHSCOPE_CHAT_URL

from nutrienv.bench.pipeline import catalog_digest, pass_through_reviewer, run_batch
from nutrienv.bench.pipeline.review_harness import (
    _route,
    call_reviewer,
    format_stage_a_prompt,
    resolved_items,
    review_candidates,
)
from nutrienv.bench.pipeline.review_harness import (
    REASON_GRAMS_OFF_TABLE,
    REASON_LEAK_ALLERGY,
    REASON_LEAK_LEFTOVER,
    REASON_LEAK_REMAINING_KCAL,
    REASON_WINDOWS_EMPTY,
    REASON_WINDOWS_OUT_OF_BOUNDS,
    REASON_WINDOWS_UNPASSABLE,
    STAGE_A_MODEL_IDS,
    STAGE_B_MODEL_IDS,
    format_stage_b_prompt,
    make_reviewer,
    stage_a_code_gate,
    stage_b_leak_scan,
)
from nutrienv.bench.realize import Oracle, Task, compose_oracles
from nutrienv.world.types import LedgerRow, Profile, WorldState, ledger_totals

_CATALOG = {
    "milk_whole": {
        "name": "Milk, whole",
        "portions": {"cup": 244.0},
        "aliases": ["milk", "whole milk"],
        "allergen_tags": ["milk"],
        "nutrients": {
            "kcal": 61.0,
            "protein_g": 3.2,
            "carb_g": 4.8,
            "fat_g": 3.3,
            "fiber_g": 0.0,
            "sodium_mg": 43.0,
        },
    },
}


def _log_task(
    task_id: str,
    query: str,
    *,
    food_id: str = "milk_whole",
    grams: float = 244.0,
) -> Task:
    s0 = WorldState(profile=Profile(user_id=task_id), catalog=_CATALOG)
    oracle = Oracle(ledger_tail=[LedgerRow(food_id, grams, "today-lunch")])
    return Task(task_id, "log", query, s0, oracle, ("multi_item_log",), "everyday")


def _boom(_prompt: str) -> str:
    raise AssertionError("LLM voter must not be used")


_DAILY = {
    "kcal": (1800.0, 2200.0),
    "protein_g": (50.0, 180.0),
    "carb_g": (100.0, 400.0),
    "fat_g": (40.0, 120.0),
    "fiber_g": (20.0, 80.0),
    "sodium_mg": (0.0, 2300.0),
}
_MEAL = {
    "kcal": (540.0, 880.0),
    "protein_g": (0.0, 180.0),
    "carb_g": (0.0, 400.0),
    "fat_g": (0.0, 120.0),
    "fiber_g": (0.0, 80.0),
    "sodium_mg": (0.0, 2300.0),
}
_PLAN_CATALOG = {
    **_CATALOG,
    "chicken_breast": {
        "name": "Chicken breast",
        "portions": {"piece": 172.0, "cup": 140.0},
        "aliases": ["chicken"],
        "allergen_tags": [],
        "nutrients": {
            "kcal": 165.0,
            "protein_g": 31.0,
            "carb_g": 0.0,
            "fat_g": 3.6,
            "fiber_g": 0.0,
            "sodium_mg": 74.0,
        },
    },
    "white_rice": {
        "name": "Rice, white, cooked",
        "portions": {"cup": 158.0},
        "aliases": ["rice"],
        "allergen_tags": [],
        "nutrients": {
            "kcal": 130.0,
            "protein_g": 2.7,
            "carb_g": 28.2,
            "fat_g": 0.3,
            "fiber_g": 0.4,
            "sodium_mg": 1.0,
        },
    },
    "broccoli": {
        "name": "Broccoli, cooked",
        "portions": {"cup": 156.0},
        "aliases": ["broccoli"],
        "allergen_tags": [],
        "nutrients": {
            "kcal": 34.0,
            "protein_g": 2.8,
            "carb_g": 6.6,
            "fat_g": 0.4,
            "fiber_g": 2.6,
            "sodium_mg": 33.0,
        },
    },
    "olive_oil": {
        "name": "Oil, olive",
        "portions": {"tbsp": 13.5},
        "aliases": ["olive oil"],
        "allergen_tags": [],
        "nutrients": {
            "kcal": 884.0,
            "protein_g": 0.0,
            "carb_g": 0.0,
            "fat_g": 100.0,
            "fiber_g": 0.0,
            "sodium_mg": 2.0,
        },
    },
}


def _rec_task(
    task_id: str,
    *,
    plan_windows: dict[str, tuple[float, float]] | None,
    query: str = "What's for dinner?",
) -> Task:
    profile = Profile(user_id=task_id, windows=dict(_DAILY))
    s0 = WorldState(profile=profile, catalog=_PLAN_CATALOG)
    oracle = Oracle(
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=plan_windows,
    )
    return Task(task_id, "recommend", query, s0, oracle, (), "everyday")


_TABLE = _log_task("log-table", "Please log a cup of milk for lunch.", grams=244.0)
_OFF = _log_task("log-off", "Please log a cup of milk for lunch.", grams=300.0)


def test_code_gate_off_table_grams_rejects_without_llm_vote() -> None:
    assert REASON_GRAMS_OFF_TABLE in stage_a_code_gate(_OFF)
    assert stage_a_code_gate(_TABLE) == []

    calls: list[str] = []

    def track(prompt: str) -> str:
        calls.append(prompt)
        return '{"eatable": true, "reason": "ok"}'

    review = make_reviewer(
        stage_a={"a1": track, "a2": track, "a3": track},
        stage_b={"b1": track, "b2": track, "b3": track},
    )([_OFF, _TABLE])

    assert _OFF.id in {row["id"] for row in review["dropped"]}
    assert _TABLE.id not in {row["id"] for row in review["dropped"]}
    off = review["per_candidate"][_OFF.id]
    assert off["dropped"] is True
    assert REASON_GRAMS_OFF_TABLE in off["stage_a"]["code_gate"]
    assert off["stage_a"]["votes"] == {}
    table = review["per_candidate"][_TABLE.id]
    assert table["dropped"] is False
    assert table["stage_a"]["code_gate"] == []
    # Only the table-gram candidate is voted: 3 Stage A plate votes then
    # 3 Stage B speech votes.
    assert len(calls) == 6
    for prompt in calls[:3]:
        assert _TABLE.query not in prompt
        assert "300" not in prompt
    for prompt in calls[3:]:
        assert "Please log a cup of milk" in prompt


def test_log_without_pinned_windows_skips_window_checks() -> None:
    assert _TABLE.oracle.plan_windows is None
    assert stage_a_code_gate(_TABLE) == []


def test_pinned_empty_intersection_windows_fail_code_gate() -> None:
    empty = dict(_MEAL)
    empty["kcal"] = (900.0, 200.0)
    task = _rec_task("rec-empty", plan_windows=empty)
    assert REASON_WINDOWS_EMPTY in stage_a_code_gate(task)
    review = make_reviewer(
        stage_a={"a1": _boom, "a2": _boom, "a3": _boom},
        stage_b={"b1": _boom, "b2": _boom, "b3": _boom},
    )([task])
    assert task.id in {row["id"] for row in review["dropped"]}


def test_pinned_windows_outside_profile_bounds_fail_code_gate() -> None:
    wide = dict(_MEAL)
    wide["kcal"] = (540.0, 5000.0)
    task = _rec_task("rec-wide", plan_windows=wide)
    assert REASON_WINDOWS_OUT_OF_BOUNDS in stage_a_code_gate(task)


def test_pinned_unpassable_windows_fail_code_gate() -> None:
    tight = {key: (1.0, 2.0) for key in _MEAL}
    task = _rec_task("rec-tight", plan_windows=tight)
    assert REASON_WINDOWS_UNPASSABLE in stage_a_code_gate(task)


def test_pinned_passable_windows_pass_code_gate() -> None:
    task = _rec_task("rec-ok", plan_windows=dict(_MEAL))
    assert stage_a_code_gate(task) == []


def _leftover_rec(
    task_id: str,
    *,
    plan_windows: dict[str, tuple[float, float]] | None,
    allergies: tuple[str, ...] = (),
    ledger: tuple[LedgerRow, ...] = (
        LedgerRow("milk_whole", 244.0, "today-breakfast"),
    ),
) -> Task:
    profile = Profile(user_id=task_id, windows=dict(_DAILY), allergies=allergies)
    s0 = WorldState(profile=profile, ledger=list(ledger), catalog=_PLAN_CATALOG)
    oracle = Oracle(
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=plan_windows,
    )
    return Task(task_id, "recommend", "What can I still eat today?", s0, oracle, (), "leftover")


def _remainder_windows(ledger: list[LedgerRow]) -> dict[str, tuple[float, float]]:
    eaten = ledger_totals(list(ledger), _PLAN_CATALOG)
    return {
        key: (
            round(max(0.0, lo - eaten.get(key, 0.0)), 2),
            round(max(0.0, hi - eaten.get(key, 0.0)), 2),
        )
        for key, (lo, hi) in _DAILY.items()
    }


def test_stage_b_leak_scan_skips_non_recommend() -> None:
    assert stage_b_leak_scan(_TABLE) == []


def test_stage_b_leftover_unpinned_windows_leak() -> None:
    task = _leftover_rec("leak-lo", plan_windows=None)
    assert REASON_LEAK_LEFTOVER in stage_b_leak_scan(task)


def test_stage_b_pinned_over_remainder_leaks_remaining_kcal() -> None:
    over = dict(_remainder_windows(list(_leftover_rec("x", plan_windows=None).s0.ledger)))
    over["kcal"] = (over["kcal"][0], over["kcal"][1] + 50.0)
    assert REASON_LEAK_REMAINING_KCAL in stage_b_leak_scan(
        _leftover_rec("leak-kcal", plan_windows=over)
    )


def test_stage_b_allergen_ledger_food_leaks() -> None:
    remainder = _remainder_windows(
        [_leftover_rec("x", plan_windows=None).s0.ledger[0]]
    )
    task = _leftover_rec(
        "leak-allergy",
        plan_windows=remainder,
        allergies=("milk",),
    )
    assert REASON_LEAK_ALLERGY in stage_b_leak_scan(task)


def test_stage_b_consistent_leftover_is_clean_and_reviewed() -> None:
    ledger = [LedgerRow("milk_whole", 244.0, "today-breakfast")]
    task = _leftover_rec(
        "lo-clean",
        plan_windows=_remainder_windows(ledger),
        ledger=tuple(ledger),
    )
    assert stage_a_code_gate(task) == []
    assert stage_b_leak_scan(task) == []

    calls_b: list[str] = []

    def track_b(prompt: str) -> str:
        calls_b.append(prompt)
        return '{"eatable": true, "reason": "fine"}'

    def track_a(_prompt: str) -> str:
        return '{"eatable": true, "reason": "fine"}'

    review = make_reviewer(
        stage_a={"a1": track_a, "a2": track_a, "a3": track_a},
        stage_b={"b1": track_b, "b2": track_b, "b3": track_b},
    )([task])
    entry = review["per_candidate"]["lo-clean"]
    assert entry["dropped"] is False
    assert entry["alarm"] is False
    assert entry["anomaly"] is False
    assert entry["verdict"] == "pass"
    assert entry["stage_a"]["majority"] == "pass"
    assert entry["stage_b"]["majority"] == "pass"
    assert calls_b and "What can I still eat today?" in calls_b[0]


def test_stage_b_majority_fail_alarms_without_dropping() -> None:
    task = _rec_task("rec-vote-fail", plan_windows=dict(_MEAL))

    def yes(_prompt: str) -> str:
        return '{"eatable": true, "reason": "ok"}'

    def no(_prompt: str) -> str:
        return '```json\n{"eatable": false, "reason": "too much"}\n```'

    review = make_reviewer(
        stage_a={"a1": yes, "a2": yes, "a3": yes},
        stage_b={"b1": no, "b2": no, "b3": yes},
    )([task])
    entry = review["per_candidate"]["rec-vote-fail"]
    assert entry["dropped"] is False
    assert entry["alarm"] is True
    assert entry["verdict"] == "alarm_majority"
    assert entry["stage_b"]["majority"] == "fail"


def test_stage_b_unparsed_votes_are_anomaly_with_alarm() -> None:
    task = _rec_task("rec-vote-junk", plan_windows=dict(_MEAL))

    def junk(_prompt: str) -> str:
        return "I cannot answer that."

    review = make_reviewer(
        stage_a={"a1": junk, "a2": junk, "a3": junk},
        stage_b={"b1": junk, "b2": junk, "b3": junk},
    )([task])
    entry = review["per_candidate"]["rec-vote-junk"]
    assert entry["dropped"] is False
    assert entry["alarm"] is True
    assert entry["anomaly"] is True
    assert entry["stage_a"]["majority"] == "undecided"


def test_stage_b_votes_see_query_but_not_grams() -> None:
    task = _leftover_rec(
        "lo-speech",
        plan_windows=_remainder_windows([_leftover_rec("y", plan_windows=None).s0.ledger[0]]),
    )
    seen_a: list[str] = []
    seen_b: list[str] = []

    def track_a(prompt: str) -> str:
        seen_a.append(prompt)
        return '{"eatable": true, "reason": "ok"}'

    def track_b(prompt: str) -> str:
        seen_b.append(prompt)
        return '{"eatable": true, "reason": "ok"}'

    make_reviewer(
        stage_a={"a1": track_a, "a2": track_a, "a3": track_a},
        stage_b={"b1": track_b, "b2": track_b, "b3": track_b},
    )([task])
    assert seen_a and seen_b
    for prompt in seen_a:
        assert task.query not in prompt
    for prompt in seen_b:
        assert task.query in prompt
        assert "244" not in prompt


def test_stage_b_speech_votes_cover_log_candidates() -> None:
    seen_a: list[str] = []
    seen_b: list[str] = []

    def track_a(prompt: str) -> str:
        seen_a.append(prompt)
        return '{"eatable": true, "reason": "ok"}'

    def track_b(prompt: str) -> str:
        seen_b.append(prompt)
        return '{"eatable": true, "reason": "ok"}'

    review = make_reviewer(
        stage_a={"a1": track_a, "a2": track_a, "a3": track_a},
        stage_b={"b1": track_b, "b2": track_b, "b3": track_b},
    )([_TABLE])
    entry = review["per_candidate"][_TABLE.id]
    assert entry["dropped"] is False
    assert entry["verdict"] == "pass"
    assert len(seen_a) == 3 and len(seen_b) == 3
    for prompt in seen_a:
        assert _TABLE.query not in prompt
    for prompt in seen_b:
        assert _TABLE.query in prompt


@pytest.mark.parametrize("skip_backresolve", [False, True])
def test_run_batch_structural_code_gate_drops_off_table_grams(
    tmp_path, skip_backresolve
) -> None:
    catalog = {
        "milk_whole": {
            "name": "Milk, whole",
            "portions": {"cup": 244.0},
            "aliases": ["milk"],
            "allergen_tags": [],
        },
        "apple": {
            "name": "Apple, raw",
            "portions": {"piece": 182.0},
            "aliases": ["apple"],
            "allergen_tags": [],
        },
        "orange": {
            "name": "Orange, raw",
            "portions": {"piece": 131.0},
            "aliases": ["orange"],
            "allergen_tags": [],
        },
    }

    def expand(_pool, *, persona, family):
        return {
            "items": [{"food": "milk_whole", "expression": "300 g"}],
            "query": "Please log 300 grams of milk for lunch.",
        }

    spec = {
        "seed": 7,
        "sampler_rule_version": "sampler-v1",
        "catalog_sha": catalog_digest(catalog),
        "persona": "everyday",
        "family_quotas": {"log": 1},
        "model_route": {},
        "catalog": "fixture",
        "output_path": tmp_path / "batch.json",
        # Worst case: speech-only resolution AND the no-voter reviewer.
        # Both guards empty must still hit the structural code gate (N09-2).
        "skip_gram_backresolve": skip_backresolve,
    }
    result = run_batch(
        spec,
        expander=expand,
        judge=lambda _food, _grams: "ok",
        reviewer=pass_through_reviewer,
        catalog=catalog,
    )
    assert result.accepted == []
    assert [row.reason for row in result.rejected] == ["code_gate"]


def test_stage_b_leak_drop_skips_stage_b_votes() -> None:
    def ok(_prompt: str) -> str:
        return '{"eatable": true, "reason": "ok"}'

    task = _leftover_rec("lo-leak-drop", plan_windows=None)
    review = make_reviewer(
        stage_a={"a1": ok, "a2": ok, "a3": ok},
        stage_b={"b1": _boom, "b2": _boom, "b3": _boom},
    )([task])
    entry = review["per_candidate"]["lo-leak-drop"]
    assert entry["dropped"] is True
    assert entry["stage_b"]["votes"] == {}
    assert REASON_LEAK_LEFTOVER in entry["stage_b"]["leak_scan"]
    assert task.id in {row["id"] for row in review["dropped"]}
    assert {row["stage"] for row in review["dropped"]} == {"stage_b"}


def test_format_stage_b_prompt_lists_names_without_grams() -> None:
    prompt = format_stage_b_prompt(_TABLE)
    assert "Milk, whole" in prompt
    assert "244" not in prompt


# --- restored coverage deleted with the c328bd0 rewrite (S09-3) -------------


def test_review_candidates_requires_models() -> None:
    with pytest.raises(ValueError, match="requires Stage A models"):
        review_candidates([_TABLE], stage_a={}, stage_b={"b1": _boom})
    with pytest.raises(ValueError, match="requires Stage B models"):
        review_candidates([_TABLE], stage_a={"a1": _boom}, stage_b={})


def test_make_reviewer_rejects_empty_pools() -> None:
    def ok(_prompt: str) -> str:
        return '{"eatable": true, "reason": "ok"}'

    with pytest.raises(ValueError, match="requires Stage A and Stage B models"):
        make_reviewer(stage_a={}, stage_b={"b1": ok, "b2": ok, "b3": ok})
    with pytest.raises(ValueError, match="requires Stage A and Stage B models"):
        make_reviewer(stage_a={"a1": ok, "a2": ok, "a3": ok}, stage_b={})


def test_empty_candidates_return_required_keys() -> None:
    def ok(_prompt: str) -> str:
        return '{"eatable": true, "reason": "ok"}'

    review = review_candidates(
        [], stage_a={"a1": ok, "a2": ok, "a3": ok}, stage_b={"b1": ok, "b2": ok, "b3": ok}
    )
    assert review == {"anomalies": [], "dropped": [], "per_candidate": {}}


def test_resolved_items_and_stage_a_prompt_carry_portion_facts() -> None:
    items = resolved_items(_TABLE)
    assert items[0]["food_id"] == "milk_whole"
    assert items[0]["portion_key"] == "cup"
    assert items[0]["quantity"] == 1.0
    assert items[0]["grams"] == 244.0
    prompt = format_stage_a_prompt(_TABLE)
    assert "Milk, whole" in prompt
    assert "244 g" in prompt
    assert _TABLE.query not in prompt


def test_parse_failure_is_retried_then_parsed() -> None:
    calls: list[str] = []

    def flaky(prompt: str) -> str:
        calls.append(prompt)
        return "still not json" if len(calls) % 2 else '{"eatable": true, "reason": "ok"}'

    entry = make_reviewer(
        stage_a={"a1": flaky, "a2": flaky, "a3": flaky},
        stage_b={"b1": flaky, "b2": flaky, "b3": flaky},
        parse_retries=1,
    )([_TABLE])["per_candidate"][_TABLE.id]
    assert len(calls) == 12  # 6 voter slots × 2 calls: junk retried once, then parsed
    assert entry["anomaly"] is False
    assert entry["stage_a"]["majority"] == "pass"


def test_route_always_uses_dashscope(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-dummy")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    for model_id in (*STAGE_A_MODEL_IDS, *STAGE_B_MODEL_IDS):
        url, key = _route(model_id)
        assert url == DASHSCOPE_CHAT_URL
        assert key == "dash-dummy"


def test_route_requires_dashscope_key(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY is not set"):
        _route("qwen3.8-max")


def test_call_reviewer_posts_to_dashscope(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, payload, api_key, **_kwargs):
        captured["url"] = url
        captured["model"] = payload["model"]
        captured["api_key"] = api_key
        captured["system"] = payload["messages"][0]["content"]
        return '{"eatable": true, "reason": "ok"}'

    monkeypatch.setattr(
        "nutrienv.bench.pipeline.review_harness.post_chat_completion", fake_post
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-dummy")
    text = call_reviewer("deepseek-v4-flash-0731", "prompt")
    assert "eatable" in text
    assert captured["url"] == DASHSCOPE_CHAT_URL
    assert captured["model"] == "deepseek-v4-flash-0731"
    assert captured["api_key"] == "dash-dummy"
    assert captured["system"].startswith("You review a plate")


# --- S09-5 / S09-6 / S09-8 regressions --------------------------------------


def test_macro_free_window_is_not_unpassable() -> None:
    task = _rec_task("rec-kcal-only", plan_windows={"kcal": (540.0, 880.0)})
    assert stage_a_code_gate(task) == []


def test_composite_child_windows_are_gated() -> None:
    good = _rec_task("comp-good", plan_windows=dict(_MEAL))
    bad = _rec_task("comp-bad", plan_windows={"kcal": (900.0, 200.0)})
    oracle = compose_oracles(good.oracle, bad.oracle)
    task = Task("comp-001", "composite", "Plan my day.", good.s0, oracle, (), "everyday")
    assert task.oracle.plan_windows is None
    assert stage_a_code_gate(task) == [REASON_WINDOWS_EMPTY]


def test_out_of_bounds_reason_appended_once() -> None:
    wide = dict(_MEAL)
    wide["kcal"] = (540.0, 5000.0)
    wide["protein_g"] = (0.0, 9999.0)
    task = _rec_task("rec-wide-two-keys", plan_windows=wide)
    reasons = stage_a_code_gate(task)
    assert reasons == [REASON_WINDOWS_OUT_OF_BOUNDS]


def test_named_dish_allergen_leak_with_empty_ledger() -> None:
    s0 = WorldState(
        profile=Profile(user_id="dish", windows=dict(_DAILY), allergies=("milk",)),
        catalog=_PLAN_CATALOG,
    )
    oracle = Oracle(
        last_plan=[{"food_id": "milk_whole", "grams": 244.0}],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=dict(_MEAL),
    )
    task = Task("rec-named-dish", "recommend", "Make me a creamy pasta tonight.",
                s0, oracle, (), "everyday")
    assert stage_a_code_gate(task) == []
    assert REASON_LEAK_ALLERGY in stage_b_leak_scan(task)
