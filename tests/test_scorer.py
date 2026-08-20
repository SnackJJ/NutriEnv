from dataclasses import replace

from nutrienv.bench import Oracle, Scorer
from nutrienv.env import NutriEnv
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.types import LedgerRow


def test_plan_pass_and_diagnostic_tags():
    scorer = Scorer()
    state = demo_state()
    state.profile = replace(
        state.profile,
        allergies=("peanut",),
        windows={"kcal": (120.0, 140.0)},
    )
    oracle = Oracle(profile=state.profile, last_plan=[], plan_must_fit_windows=True)

    state.last_plan = [{"food_id": "white_rice", "grams": 100.0}]
    assert scorer.score(state, oracle) == {"passed": True, "tag": "pass"}

    state.last_plan = [{"food_id": "peanut_butter", "grams": 25.0}]
    assert scorer.score(state, oracle)["tag"] == "allergy"

    state.last_plan = [{"food_id": "white_rice", "grams": 200.0}]
    assert scorer.score(state, oracle)["tag"] == "window"


def test_log_tail_and_profile_are_exact():
    scorer = Scorer()
    state = demo_state()
    row = LedgerRow("oats", 60.0, "now")
    state.ledger.extend([LedgerRow("banana", 100.0, "earlier"), row])
    assert scorer.score(state, Oracle(ledger_tail=[row]))["passed"]
    assert scorer.score(state, Oracle(ledger_tail=[replace(row, grams=61.0)]))["tag"] == "log_miss"

    expected = replace(state.profile, allergies=("peanut", "shellfish"))
    assert scorer.score(state, Oracle(profile=expected))["tag"] == "update_miss"


def test_exact_evaluation_plan_and_empty_plan_goal():
    state = demo_state()
    expected = [{"food_id": "white_rice", "grams": 100.0}]
    oracle = Oracle(profile=replace(state.profile, windows={}), last_plan=expected)
    state.profile = oracle.profile
    assert Scorer().score(state, oracle)["tag"] == "wrong_goal"
    state.last_plan = expected
    assert Scorer().score(state, oracle)["passed"]


def test_reject_oracle_matching_reject_passes() -> None:
    state = demo_state()
    oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        last_verdict="reject",
        last_reasons=("allergy",),
        ledger=tuple(state.ledger),
    )
    env = NutriEnv()
    env.reset(state)
    out = env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": ["allergy"],
        }
    )
    assert out["ok"] is True
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}
