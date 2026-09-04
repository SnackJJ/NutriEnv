from dataclasses import replace

from nutrienv.bench import Oracle, Scorer
from nutrienv.env import NutriEnv
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.daily_windows import derive_daily_windows
from nutrienv.world.types import LedgerRow, Profile


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
    # 61 g is inside the ±15% band; 80 g (1.33×) is not.
    assert scorer.score(state, Oracle(ledger_tail=[replace(row, grams=61.0)]))["passed"]
    assert scorer.score(state, Oracle(ledger_tail=[replace(row, grams=80.0)]))["tag"] == "log_miss"

    expected = replace(state.profile, allergies=("peanut", "shellfish"))
    assert scorer.score(state, Oracle(profile=expected))["tag"] == "update_miss"


def test_log_tail_order_independent_passes():
    scorer = Scorer()
    state = demo_state()
    row1 = LedgerRow("beef", 100.0, "today-lunch")
    row2 = LedgerRow("ice_cream", 50.0, "today-lunch")
    # Agent logs [beef, ice_cream]
    state.ledger.extend([row1, row2])
    # Oracle had [ice_cream, beef] in tail
    assert scorer.score(state, Oracle(ledger_tail=[row2, row1]))["passed"]
    # Full ledger check also passes
    assert scorer.score(state, Oracle(ledger=(row2, row1)))["passed"]


def test_log_tail_discrete_portion_tolerance_adr0023():
    scorer = Scorer()
    state = demo_state()
    # "peanut_butter" in demo catalog has portions: {"tbsp": 16.0, "cup": 258.0}
    # Ounce multiples are 14.18, 28.35, 42.52, 56.7
    # 2 tbsp = 32.0g. Gold = 30.0g (ratio 32/30 = 1.067, within [0.85, 1.15])
    gold_row = LedgerRow("peanut_butter", 30.0, "today-breakfast")
    state.catalog = {"peanut_butter": {"portions": {"tbsp": 16.0, "cup": 258.0}}}
    
    # Agent logged 32.0g (2 tbsp), which is in portion table and within [0.85*30, 1.15*30] = [25.5, 34.5]
    state.ledger = [LedgerRow("peanut_butter", 32.0, "today-breakfast")]
    assert scorer.score(state, Oracle(ledger_tail=[gold_row]))["passed"]

    # Agent logged 31.0g: inside the continuous ±15% band (ADR 0029 unbound the
    # discrete portion-table lock), so this is a Pass.
    state.ledger = [LedgerRow("peanut_butter", 31.0, "today-breakfast")]
    assert scorer.score(state, Oracle(ledger_tail=[gold_row]))["passed"]

    # Agent logged 16.0g (1 tbsp, in portion table, but 16.0 < 0.85*30 = 25.5) -> log_miss
    state.ledger = [LedgerRow("peanut_butter", 16.0, "today-breakfast")]
    assert scorer.score(state, Oracle(ledger_tail=[gold_row]))["tag"] == "log_miss"


def test_plan_items_use_ledger_portion_band() -> None:
    catalog = {"peanut_butter": {"portions": {"tbsp": 16.0, "cup": 258.0}}}
    gold = {"food_id": "peanut_butter", "grams": 30.0}
    assert Scorer._plan_item_matches(
        {"food_id": "peanut_butter", "grams": 32.0}, gold, catalog
    )
    assert not Scorer._plan_item_matches(
        {"food_id": "peanut_butter", "grams": 16.0}, gold, catalog
    )


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

    # ADR 0024: Identifying the fatal allergy is sufficient for Pass
    state.last_reasons = ("allergy",)
    assert scorer.score(state, oracle) == {"passed": True, "tag": "pass"}

    # ADR 0024: Extra macro codes along with allergy still pass
    state.last_reasons = ("allergy", "kcal_hi", "fiber_g_lo")
    assert scorer.score(state, oracle) == {"passed": True, "tag": "pass"}

    # ADR 0024: Missing allergy when allergy is in gold is Fatal Fail
    state.last_reasons = ("kcal_hi",)
    assert scorer.score(state, oracle)["passed"] is False

    # Pure macro reject still requires exact match:
    pure_macro_oracle = _reject_oracle(state, reasons=("kcal_hi",))
    state.last_reasons = ("kcal_lo",)
    assert scorer.score(state, pure_macro_oracle)["passed"] is False
    state.last_reasons = ("kcal_hi",)
    assert scorer.score(state, pure_macro_oracle) == {"passed": True, "tag": "pass"}


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


def _ada_state(*, phase: str = "maintain"):
    state = demo_state()
    windows = derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase=phase,
    )
    state.profile = Profile(
        user_id="roster-ada",
        allergies=("peanut",),
        windows=windows,
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase=phase,
    )
    return state


def test_implicit_cut_band_passes_phase_patch_and_rejects_allergy_drift() -> None:
    """I'm cutting (no number): windows in [EER−500, EER−100]; allergies stay."""
    s0 = _ada_state()
    env = NutriEnv()
    env.reset(s0)
    env.step({"op": "update_profile", "patch": {"phase": "cut"}})
    oracle = Oracle(
        profile=replace(s0.profile, phase="cut"),
        update_band="cut",
        ledger=tuple(s0.ledger),
    )
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}

    env.step({"op": "update_profile", "patch": {"allergies": ["peanut", "milk"]}})
    assert Scorer().score(env.state(), oracle)["tag"] == "update_miss"


def test_implicit_cut_rejects_unmentioned_sodium_corruption() -> None:
    s0 = _ada_state()
    env = NutriEnv()
    env.reset(s0)
    env.step({"op": "update_profile", "patch": {"phase": "cut"}})
    oracle = Oracle(
        profile=replace(s0.profile, phase="cut"),
        update_band="cut",
        ledger=tuple(s0.ledger),
    )
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}

    env.step(
        {"op": "update_profile", "patch": {"windows": {"sodium_mg": [0.0, 100.0]}}}
    )
    assert Scorer().score(env.state(), oracle)["tag"] == "update_miss"


def test_implicit_cut_band_rejects_kcal_hi_outside_published_range() -> None:
    eer = 1815.34375
    s0 = _ada_state()
    oracle = Oracle(
        profile=replace(s0.profile, phase="cut"),
        update_band="cut",
        ledger=tuple(s0.ledger),
    )
    env = NutriEnv()
    env.reset(s0)
    env.step({"op": "update_profile", "patch": {"phase": "cut"}})
    env.step(
        {
            "op": "update_profile",
            "patch": {"windows": {"kcal": [eer - 50.0, eer - 50.0]}},
        }
    )
    assert Scorer().score(env.state(), oracle)["tag"] == "update_miss"


def test_implicit_fatigue_band_raises_kcal_toward_maintain() -> None:
    eer = 1815.34375
    s0 = _ada_state(phase="cut")
    s0_hi = s0.profile.windows["kcal"][1]
    oracle = Oracle(profile=s0.profile, update_band="fatigue", ledger=tuple(s0.ledger))
    env = NutriEnv()
    env.reset(s0)
    eased = (s0_hi + eer) / 2.0
    env.step({"op": "update_profile", "patch": {"windows": {"kcal": [eased, eased]}}})
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}

    env.step({"op": "update_profile", "patch": {"windows": {"kcal": [eer + 1.0, eer + 1.0]}}})
    assert Scorer().score(env.state(), oracle)["tag"] == "update_miss"


def test_implicit_fatigue_keeps_unmentioned_allergies_exact() -> None:
    s0 = _ada_state(phase="cut")
    s0_hi = s0.profile.windows["kcal"][1]
    oracle = Oracle(profile=s0.profile, update_band="fatigue", ledger=tuple(s0.ledger))
    env = NutriEnv()
    env.reset(s0)
    env.step(
        {
            "op": "update_profile",
            "patch": {
                "windows": {"kcal": [s0_hi + 100.0, s0_hi + 100.0]},
                "allergies": ["peanut", "milk"],
            },
        }
    )
    assert Scorer().score(env.state(), oracle)["tag"] == "update_miss"


def test_implicit_fatigue_rejects_unmentioned_fiber_corruption() -> None:
    s0 = _ada_state(phase="cut")
    s0_hi = s0.profile.windows["kcal"][1]
    oracle = Oracle(profile=s0.profile, update_band="fatigue", ledger=tuple(s0.ledger))
    env = NutriEnv()
    env.reset(s0)
    env.step(
        {"op": "update_profile", "patch": {"windows": {"kcal": [s0_hi + 100.0, s0_hi + 100.0]}}}
    )
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}
    env.step(
        {"op": "update_profile", "patch": {"windows": {"fiber_g": [0.0, 1.0]}}}
    )
    assert Scorer().score(env.state(), oracle)["tag"] == "update_miss"


def test_implicit_muscle_band_requires_protein_above_rda() -> None:
    s0 = _ada_state()
    env = NutriEnv()
    env.reset(s0)
    env.step({"op": "update_profile", "patch": {"phase": "muscle"}})
    oracle = Oracle(
        profile=replace(s0.profile, phase="muscle"),
        update_band="muscle",
        ledger=tuple(s0.ledger),
    )
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}

    env.step(
        {"op": "update_profile", "patch": {"windows": {"protein_g": [49.6, 49.6]}}}
    )
    assert Scorer().score(env.state(), oracle)["tag"] == "update_miss"

    env.reset(s0)
    env.step({"op": "update_profile", "patch": {"phase": "muscle"}})
    env.step(
        {"op": "update_profile", "patch": {"windows": {"carb_g": [0.0, 1.0]}}}
    )
    assert Scorer().score(env.state(), oracle)["tag"] == "update_miss"


def test_implicit_fatigue_accepts_either_route_the_handbook_offers() -> None:
    """The manual offers a phase patch or a direct window move; both satisfy the band.

    phase is the means, not the verdict. A wrong phase still fails, because the
    windows Env derives from it miss the band.
    """
    eer = 1815.34375
    oracle_s0 = _ada_state(phase="cut")
    oracle = Oracle(
        profile=oracle_s0.profile, update_band="fatigue", ledger=tuple(oracle_s0.ledger)
    )
    s0_hi = oracle_s0.profile.windows["kcal"][1]

    env = NutriEnv()
    env.reset(_ada_state(phase="cut"))
    env.step({"op": "update_profile", "patch": {"phase": "maintain"}})
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}

    env.reset(_ada_state(phase="cut"))
    eased = (s0_hi + eer) / 2.0
    env.step({"op": "update_profile", "patch": {"windows": {"kcal": [eased, eased]}}})
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}

    # Staying in cut is not a rise: the derived windows are S0's, not above them.
    env.reset(_ada_state(phase="cut"))
    env.step({"op": "update_profile", "patch": {"phase": "cut"}})
    assert Scorer().score(env.state(), oracle)["tag"] == "update_miss"


def test_specific_allergen_reason_alias_passes_scoped() -> None:
    catalog = {
        "shrimp": {
            "name": "Shrimp",
            "allergen_tags": ["shellfish"],
            "nutrients": {"kcal": 100.0},
        }
    }
    state = replace(
        demo_state(),
        catalog=catalog,
        profile=replace(demo_state().profile, allergies=("shellfish",)),
    )
    evaluated_plan = [{"food_id": "shrimp", "grams": 100.0}]
    oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        last_verdict="reject",
        last_reasons=("allergy",),
        evaluated_plan=evaluated_plan,
        ledger=tuple(state.ledger),
    )

    # Model reports specific allergen "shellfish" -> Pass
    env = NutriEnv()
    env.reset(state)
    env.step({"op": "submit_plan", "items": [], "verdict": "reject", "reasons": ["shellfish"]})
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}

    # Model hallucinates "peanut" -> Fail (wrong_goal)
    env.reset(state)
    env.step({"op": "submit_plan", "items": [], "verdict": "reject", "reasons": ["peanut"]})
    assert Scorer().score(env.state(), oracle)["tag"] == "wrong_goal"

    # Model misses allergy, reports "kcal_hi" -> Fail (wrong_goal)
    env.reset(state)
    env.step({"op": "submit_plan", "items": [], "verdict": "reject", "reasons": ["kcal_hi"]})
    assert Scorer().score(env.state(), oracle)["tag"] == "wrong_goal"


def test_non_allergy_reject_reasons_valid_subset_passes() -> None:
    """If food violates multiple non-allergy constraints, identifying any true subset passes."""
    state = demo_state()
    oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        last_verdict="reject",
        last_reasons=("fat_g_hi", "kcal_hi", "protein_g_hi"),
        ledger=tuple(state.ledger),
    )
    env = NutriEnv()
    env.reset(state)
    # Agent identifies primary violation kcal_hi without listing all secondary violations
    env.step({"op": "submit_plan", "items": [], "verdict": "reject", "reasons": ["kcal_hi"]})
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}

    # Agent identifies an irrelevant or false reason -> Fail
    env.reset(state)
    env.step({"op": "submit_plan", "items": [], "verdict": "reject", "reasons": ["sodium_mg_hi"]})
    assert Scorer().score(env.state(), oracle)["tag"] == "wrong_goal"


def test_scorer_reject_anti_cheating() -> None:
    """Anti-cheating firewall: contradictory reasons or phantom allergy must fail."""
    state = demo_state()
    oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        last_verdict="reject",
        last_reasons=("kcal_hi",),
        ledger=tuple(state.ledger),
    )
    env = NutriEnv()
    env.reset(state)

    # 1. Contradictory reasons: reporting both kcal_hi and kcal_lo
    env.step({
        "op": "submit_plan",
        "items": [],
        "verdict": "reject",
        "reasons": ["kcal_hi", "kcal_lo"],
    })
    assert Scorer().score(env.state(), oracle)["tag"] == "wrong_goal"

    # 2. Phantom allergy accusation when gold has no allergy
    env.reset(state)
    env.step({
        "op": "submit_plan",
        "items": [],
        "verdict": "reject",
        "reasons": ["kcal_hi", "allergy"],
    })
    assert Scorer().score(env.state(), oracle)["tag"] == "wrong_goal"


def test_off_inventory_food_is_inventory_miss() -> None:
    scorer = Scorer()
    state = demo_state()
    state.profile = replace(
        state.profile,
        allergies=("peanut",),
        windows={"kcal": (120.0, 140.0)},
    )
    oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        plan_must_fit_windows=True,
        allowed_food_ids=frozenset({"white_rice", "broccoli"}),
    )
    state.last_plan = [{"food_id": "white_rice", "grams": 100.0}]
    assert scorer.score(state, oracle) == {"passed": True, "tag": "pass"}

    state.last_plan = [{"food_id": "chicken_breast", "grams": 80.0}]
    assert scorer.score(state, oracle)["tag"] == "inventory_miss"


def test_worldstate_allowed_food_ids_apply_when_oracle_omits_them() -> None:
    scorer = Scorer()
    state = demo_state()
    state.profile = replace(state.profile, windows={"kcal": (120.0, 140.0)})
    state.allowed_food_ids = frozenset({"white_rice"})
    oracle = Oracle(profile=state.profile, last_plan=[], plan_must_fit_windows=True)
    state.last_plan = [{"food_id": "chicken_breast", "grams": 80.0}]
    assert scorer.score(state, oracle)["tag"] == "inventory_miss"
    state.last_plan = [{"food_id": "white_rice", "grams": 100.0}]
    assert scorer.score(state, oracle)["passed"] is True


def test_composite_plan_leg_inherits_parent_allowed_food_ids() -> None:
    state = demo_state()
    state.profile = replace(state.profile, windows={"kcal": (120.0, 140.0)})
    log_oracle = Oracle(profile=state.profile, ledger=tuple(state.ledger))
    rec_oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        plan_must_fit_windows=True,
        ledger=tuple(state.ledger),
    )
    parent = Oracle(
        sub_oracles=(log_oracle, rec_oracle),
        allowed_food_ids=frozenset({"white_rice"}),
    )
    state.last_plan = [{"food_id": "chicken_breast", "grams": 80.0}]
    result = Scorer().score(state, parent)
    assert result["passed"] is False
    assert result["tag"] == "inventory_miss"
    assert result["sub_tags"][-1] == "inventory_miss"

