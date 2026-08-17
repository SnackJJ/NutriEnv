"""Composite Scorer: Pass ⇔ every sub-oracle matches. Single-family shape unchanged."""

from __future__ import annotations

from dataclasses import replace

from nutrienv.bench import Oracle, Scorer
from nutrienv.bench.realize import compose_oracles
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.types import LedgerRow, ledger_totals


def _remainder(state, extra) -> dict[str, tuple[float, float]]:
    eaten = ledger_totals([*state.ledger, *extra], state.catalog)
    remain: dict[str, tuple[float, float]] = {}
    for key, (lo, hi) in state.profile.windows.items():
        used = eaten.get(key, 0.0)
        remain[key] = (round(max(0.0, lo - used), 2), round(max(0.0, hi - used), 2))
    return remain


def _log_recommend_pair(state, lunch: LedgerRow):
    final = (*state.ledger, lunch)
    log_oracle = Oracle(
        profile=state.profile,
        ledger_tail=[lunch],
        ledger=final,
    )
    rec_oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        ledger_tail=[lunch],
        ledger=final,
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=_remainder(state, [lunch]),
    )
    return log_oracle, rec_oracle


def _tight_state():
    state = demo_state()
    state.profile = replace(
        state.profile,
        windows={"kcal": (200.0, 400.0), "protein_g": (20.0, 80.0)},
    )
    return state


def test_single_oracle_result_has_no_sub_tags():
    state = demo_state()
    result = Scorer().score(state, Oracle(profile=state.profile))
    assert result == {"passed": True, "tag": "pass"}
    assert "sub_tags" not in result


def test_composite_all_match_passes():
    state = _tight_state()
    lunch = LedgerRow("oats", 60.0, "today-lunch")
    log_oracle, rec_oracle = _log_recommend_pair(state, lunch)
    state.ledger.append(lunch)
    state.last_plan = [{"food_id": "chicken_breast", "grams": 80.0}]
    result = Scorer().score(state, compose_oracles(log_oracle, rec_oracle))
    assert result["passed"] is True
    assert result["tag"] == "pass"
    assert result["sub_tags"] == ("pass", "pass")


def test_composite_log_miss_is_first_failing_tag():
    state = _tight_state()
    lunch = LedgerRow("oats", 60.0, "today-lunch")
    log_oracle, rec_oracle = _log_recommend_pair(state, lunch)
    state.last_plan = [{"food_id": "chicken_breast", "grams": 80.0}]
    result = Scorer().score(state, compose_oracles(log_oracle, rec_oracle))
    assert result["passed"] is False
    assert result["tag"] == "log_miss"
    assert result["sub_tags"][0] == "log_miss"


def test_composite_recommend_miss_keeps_log_pass():
    state = _tight_state()
    lunch = LedgerRow("oats", 60.0, "today-lunch")
    log_oracle, rec_oracle = _log_recommend_pair(state, lunch)
    state.ledger.append(lunch)
    state.last_plan = [{"food_id": "peanut_butter", "grams": 25.0}]
    result = Scorer().score(state, compose_oracles(log_oracle, rec_oracle))
    assert result["passed"] is False
    assert result["tag"] == "allergy"
    assert result["sub_tags"] == ("pass", "allergy")


def test_composite_mixed_families_log_and_recommend():
    state = _tight_state()
    lunch = LedgerRow("oats", 60.0, "today-lunch")
    log_oracle, rec_oracle = _log_recommend_pair(state, lunch)
    assert log_oracle.last_plan is None
    assert log_oracle.ledger_tail == [lunch]
    assert rec_oracle.last_plan == []
    assert rec_oracle.plan_must_fit_windows
    state.ledger.append(lunch)
    state.last_plan = [{"food_id": "chicken_breast", "grams": 80.0}]
    composite = compose_oracles(log_oracle, rec_oracle)
    assert composite.sub_oracles is not None
    assert len(composite.sub_oracles) == 2
    assert Scorer().score(state, composite)["passed"] is True


def test_compose_oracles_rejects_one_or_nested():
    import pytest

    lone = Oracle()
    with pytest.raises(ValueError, match="at least two"):
        compose_oracles(lone)
    pair = compose_oracles(Oracle(ledger_tail=[]), Oracle(last_plan=[]))
    with pytest.raises(ValueError, match="nested"):
        compose_oracles(pair, Oracle())
