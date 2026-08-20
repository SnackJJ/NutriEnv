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


def _reject_oracle(state, reasons=("allergy",)):
    return Oracle(
        profile=state.profile,
        last_plan=[],
        last_verdict="reject",
        last_reasons=reasons,
        ledger=tuple(state.ledger),
    )


def test_reject_oracle_matching_reject_passes() -> None:
    state = demo_state()
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
    assert Scorer().score(env.state(), _reject_oracle(state)) == {
        "passed": True,
        "tag": "pass",
    }


def test_reject_oracle_silence_fails() -> None:
    state = demo_state()
    env = NutriEnv()
    env.reset(state)
    assert Scorer().score(env.state(), _reject_oracle(state))["passed"] is False
    env.step({"op": "submit_plan", "items": []})
    assert env.state().last_verdict is None
    assert Scorer().score(env.state(), _reject_oracle(state))["tag"] == "wrong_goal"


def test_reject_oracle_fitting_substitute_fails() -> None:
    state = demo_state()
    substitute = [{"food_id": "white_rice", "grams": 100.0}]
    env = NutriEnv()
    env.reset(state)
    omitted = env.step({"op": "submit_plan", "items": substitute})
    assert omitted["ok"] is True
    assert env.state().last_verdict == "accept"
    assert Scorer().score(env.state(), _reject_oracle(state))["tag"] == "wrong_goal"

    env.reset(state)
    accepted = env.step(
        {"op": "submit_plan", "items": substitute, "verdict": "accept"}
    )
    assert accepted["ok"] is True
    assert env.state().last_verdict == "accept"
    assert Scorer().score(env.state(), _reject_oracle(state))["passed"] is False


def test_reject_reasons_are_compared_as_a_set() -> None:
    state = demo_state()
    gold = ("allergy", "kcal_hi")
    oracle = _reject_oracle(state, reasons=gold)
    scorer = Scorer()

    state.last_verdict = "reject"
    state.last_plan = []
    state.last_reasons = ("kcal_hi", "allergy", "allergy")
    assert scorer.score(state, oracle) == {"passed": True, "tag": "pass"}

    state.last_reasons = ("allergy",)
    assert scorer.score(state, oracle)["tag"] == "wrong_goal"

    state.last_reasons = ("allergy", "kcal_hi", "fiber_g_lo")
    assert scorer.score(state, oracle)["passed"] is False


def test_reject_oracle_missing_last_plan_is_not_empty() -> None:
    state = demo_state()
    state.last_verdict = "reject"
    state.last_plan = None
    state.last_reasons = ("allergy",)
    assert Scorer().score(state, _reject_oracle(state))["tag"] == "wrong_goal"


def test_env_accepts_wrong_legal_reason_scorer_fails() -> None:
    state = demo_state()
    env = NutriEnv()
    env.reset(state)
    out = env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": ["kcal_hi"],
        }
    )
    assert out["ok"] is True
    assert env.state().last_reasons == ("kcal_hi",)
    assert Scorer().score(env.state(), _reject_oracle(state))["passed"] is False


def test_allow_empty_plan_does_not_pass_a_reject_oracle() -> None:
    state = demo_state()
    oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        last_verdict="reject",
        last_reasons=("allergy",),
        allow_empty_plan=True,
        ledger=tuple(state.ledger),
    )
    env = NutriEnv()
    env.reset(state)
    env.step({"op": "submit_plan", "items": []})
    assert env.state().last_verdict is None
    assert env.state().last_plan == []
    assert Scorer().score(env.state(), oracle)["tag"] == "wrong_goal"


def test_accept_oracle_requires_the_exact_adopted_plan() -> None:
    state = demo_state()
    expected = [{"food_id": "white_rice", "grams": 100.0}]
    oracle = Oracle(
        profile=state.profile,
        last_plan=expected,
        last_verdict="accept",
        ledger=tuple(state.ledger),
    )
    env = NutriEnv()
    env.reset(state)
    env.step({"op": "submit_plan", "items": expected})
    assert env.state().last_verdict == "accept"
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}

    env.reset(state)
    env.step(
        {
            "op": "submit_plan",
            "items": [{"food_id": "chicken_breast", "grams": 80.0}],
            "verdict": "accept",
        }
    )
    assert Scorer().score(env.state(), oracle)["tag"] == "wrong_goal"

    env.reset(state)
    env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": ["allergy"],
        }
    )
    assert Scorer().score(env.state(), oracle)["passed"] is False


def test_accept_oracle_allergenic_plan_fails() -> None:
    state = demo_state()
    expected = [{"food_id": "peanut_butter", "grams": 25.0}]
    oracle = Oracle(
        profile=state.profile,
        last_plan=expected,
        last_verdict="accept",
        ledger=tuple(state.ledger),
    )
    env = NutriEnv()
    env.reset(state)
    out = env.step({"op": "submit_plan", "items": expected})
    assert out["ok"] is True
    assert env.state().last_verdict == "accept"
    assert Scorer().score(env.state(), oracle)["tag"] == "allergy"


def test_accept_oracle_out_of_window_plan_fails() -> None:
    state = demo_state()
    state.profile = replace(state.profile, windows={"kcal": (120.0, 140.0)})
    expected = [{"food_id": "white_rice", "grams": 200.0}]
    oracle = Oracle(
        profile=state.profile,
        last_plan=expected,
        last_verdict="accept",
        plan_must_fit_windows=True,
        ledger=tuple(state.ledger),
    )
    env = NutriEnv()
    env.reset(state)
    out = env.step({"op": "submit_plan", "items": expected})
    assert out["ok"] is True
    assert env.state().last_verdict == "accept"
    assert Scorer().score(env.state(), oracle)["tag"] == "window"
