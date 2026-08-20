"""Env step physics: illegal ids, descriptive logs, partial profile writes."""

from __future__ import annotations

import copy
from pathlib import Path

from nutrienv.bench.split import load_split
from nutrienv.env import NutriEnv
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.daily_windows import derive_daily_windows
from nutrienv.world.types import LedgerRow, Profile

V04 = Path("data/splits/v0.4-gold.json")


def test_illegal_food_id_does_not_mutate() -> None:
    env = NutriEnv()
    s0 = demo_state()
    env.reset(s0)
    before = copy.deepcopy(env.state())

    out = env.step({"op": "log_meal", "food_id": "not_a_minted_food", "grams": 50})

    assert out["ok"] is False
    assert out["error"]["code"] == "unknown_food"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan
    assert after.catalog == before.catalog

    # Episode continues after an Illegal Action.
    cont = env.step({"op": "get_profile"})
    assert cont["ok"] is True
    assert env.state().ledger == before.ledger


def test_log_meal_of_allergen_food_is_allowed() -> None:
    env = NutriEnv()
    s0 = demo_state()
    assert "peanut" in s0.profile.allergies
    assert "peanut" in s0.catalog["peanut_butter"]["allergen_tags"]
    env.reset(s0)

    out = env.step(
        {
            "op": "log_meal",
            "food_id": "peanut_butter",
            "grams": 32,
            "eaten_at": "lunch",
        }
    )

    assert out["ok"] is True
    row = env.state().ledger[-1]
    assert row == LedgerRow(food_id="peanut_butter", grams=32.0, eaten_at="lunch")
    assert env.state().profile.allergies == s0.profile.allergies


def test_update_profile_kcal_only_leaves_allergies_unchanged() -> None:
    env = NutriEnv()
    s0 = demo_state()
    env.reset(s0)

    out = env.step(
        {"op": "update_profile", "patch": {"windows": {"kcal": [2100.0, 2500.0]}}}
    )

    assert out["ok"] is True
    profile = env.state().profile
    assert profile.allergies == s0.profile.allergies
    assert profile.medications == s0.profile.medications
    assert profile.windows["kcal"] == (2100.0, 2500.0)
    assert profile.windows["protein_g"] == s0.profile.windows["protein_g"]
    assert profile.plan_preset == s0.profile.plan_preset
    assert profile.version == s0.profile.version


def test_foods_are_found_by_search_not_a_full_listing() -> None:
    env = NutriEnv()
    s0 = demo_state()
    s0.ledger = []
    opening = env.reset(s0)

    assert opening["catalog_size"] == 15
    assert "catalog_ids" not in opening
    assert env.step({"op": "search_foods", "q": "*"})["observation"]["results"] == []
    shrimp = env.step({"op": "search_foods", "q": "prawn"})["observation"]["results"]
    assert shrimp[0]["food_id"] == "shrimp"
    assert env.step({"op": "get_food", "food_id": "shrimp"})["ok"]


def test_wildcard_is_the_only_match_all_query() -> None:
    env = NutriEnv()
    env.reset(demo_state())

    def hits(needle: str) -> int:
        return len(env.step({"op": "search_foods", "q": needle})["observation"]["results"])

    assert hits("*") == 0
    assert hits("oats") == 1
    # A stray character is still a miss, not an accidental catalog dump.
    assert hits("a") == 0
    assert hits("**") == 0


def test_log_meal_rejects_item_above_2000g() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    before = copy.deepcopy(env.state())

    out = env.step({"op": "log_meal", "food_id": "oats", "grams": 2001})

    assert out["ok"] is False
    assert out["error"]["code"] == "implausible_quantity"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan
    assert after.catalog == before.catalog


def test_submit_plan_rejects_item_above_2000g() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    before = copy.deepcopy(env.state())

    out = env.step(
        {"op": "submit_plan", "items": [{"food_id": "oats", "grams": 2001}]}
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "implausible_quantity"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan
    assert after.catalog == before.catalog


def test_submit_plan_rejects_total_above_4000g() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    before = copy.deepcopy(env.state())

    out = env.step(
        {
            "op": "submit_plan",
            "items": [
                {"food_id": "oats", "grams": 2000},
                {"food_id": "egg", "grams": 2000},
                {"food_id": "banana", "grams": 2000},
            ],
        }
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "implausible_quantity"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan
    assert after.catalog == before.catalog


def test_quantity_bounds_are_inclusive() -> None:
    env = NutriEnv()
    env.reset(demo_state())

    logged = env.step({"op": "log_meal", "food_id": "oats", "grams": 2000})
    assert logged["ok"] is True
    assert env.state().ledger[-1].grams == 2000.0

    single = env.step(
        {"op": "submit_plan", "items": [{"food_id": "egg", "grams": 2000}]}
    )
    assert single["ok"] is True
    assert env.state().last_plan == [{"food_id": "egg", "grams": 2000.0}]

    total = env.step(
        {
            "op": "submit_plan",
            "items": [
                {"food_id": "oats", "grams": 2000},
                {"food_id": "egg", "grams": 2000},
            ],
        }
    )
    assert total["ok"] is True
    assert env.state().last_plan == [
        {"food_id": "oats", "grams": 2000.0},
        {"food_id": "egg", "grams": 2000.0},
    ]


def test_zero_kcal_coffee_exploit_is_rejected() -> None:
    task = next(item for item in load_split(V04) if item.id == "v0-rec-conflict-001")
    coffee = task.s0.catalog["2710376"]
    assert coffee["nutrients"]["kcal"] == 0.0
    assert coffee["nutrients"]["protein_g"] > 0

    env = NutriEnv()
    env.reset(task.s0)
    before = copy.deepcopy(env.state())

    out = env.step(
        {"op": "submit_plan", "items": [{"food_id": "2710376", "grams": 90909}]}
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "implausible_quantity"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan


def test_nonempty_submit_plan_without_verdict_sets_accept() -> None:
    env = NutriEnv()
    env.reset(demo_state())

    out = env.step(
        {"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]}
    )

    assert out["ok"] is True
    state = env.state()
    assert state.last_verdict == "accept"
    assert state.last_plan == [{"food_id": "egg", "grams": 100.0}]
    assert state.last_reasons == ()


def test_empty_submit_plan_without_verdict_is_silence_not_leftover_accept() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})
    assert env.state().last_verdict == "accept"

    out = env.step({"op": "submit_plan", "items": []})

    assert out["ok"] is True
    state = env.state()
    assert state.last_verdict is None
    assert state.last_plan == []
    assert state.last_reasons == ()


def test_reject_with_empty_items_sets_reasons_and_clears_plan() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})

    out = env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": ["kcal_hi", "allergy", "kcal_hi"],
        }
    )

    assert out["ok"] is True
    state = env.state()
    assert state.last_verdict == "reject"
    assert state.last_plan == []
    assert state.last_reasons == ("allergy", "kcal_hi")


def test_reject_with_nonempty_plan_is_illegal_and_leaves_world_unchanged() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})
    before = copy.deepcopy(env.state())

    out = env.step(
        {
            "op": "submit_plan",
            "items": [{"food_id": "oats", "grams": 50}],
            "verdict": "reject",
            "reasons": ["kcal_hi"],
        }
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "bad_schema"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan
    assert after.last_verdict == before.last_verdict
    assert after.last_reasons == before.last_reasons
    assert after.catalog == before.catalog


def test_accept_with_reasons_is_illegal_and_leaves_world_unchanged() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": ["kcal_hi"],
        }
    )
    before = copy.deepcopy(env.state())

    out = env.step(
        {
            "op": "submit_plan",
            "items": [{"food_id": "egg", "grams": 100}],
            "verdict": "accept",
            "reasons": ["kcal_hi"],
        }
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "bad_schema"
    after = env.state()
    assert after.last_verdict == "reject"
    assert after.last_plan == []
    assert after.last_reasons == ("kcal_hi",)
    assert after.ledger == before.ledger
    assert after.profile == before.profile


def test_accept_with_empty_reasons_is_illegal_and_leaves_world_unchanged() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": ["kcal_hi"],
        }
    )
    before = copy.deepcopy(env.state())

    out = env.step(
        {
            "op": "submit_plan",
            "items": [{"food_id": "egg", "grams": 100}],
            "verdict": "accept",
            "reasons": [],
        }
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "bad_schema"
    after = env.state()
    assert after.last_verdict == "reject"
    assert after.last_plan == []
    assert after.last_reasons == ("kcal_hi",)
    assert after.ledger == before.ledger
    assert after.profile == before.profile


def test_reasons_without_verdict_are_illegal_and_leave_world_unchanged() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})
    before = copy.deepcopy(env.state())

    out = env.step(
        {
            "op": "submit_plan",
            "items": [{"food_id": "oats", "grams": 40}],
            "reasons": ["kcal_hi"],
        }
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "bad_schema"
    after = env.state()
    assert after.last_verdict == "accept"
    assert after.last_plan == before.last_plan
    assert after.last_reasons == ()
    assert after.ledger == before.ledger
    assert after.profile == before.profile


def test_reject_with_empty_reasons_is_legal_physics() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})

    omitted = env.step({"op": "submit_plan", "items": [], "verdict": "reject"})
    assert omitted["ok"] is True
    assert env.state().last_verdict == "reject"
    assert env.state().last_plan == []
    assert env.state().last_reasons == ()

    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})
    empty = env.step(
        {"op": "submit_plan", "items": [], "verdict": "reject", "reasons": []}
    )
    assert empty["ok"] is True
    assert env.state().last_verdict == "reject"
    assert env.state().last_plan == []
    assert env.state().last_reasons == ()


def test_unknown_reason_token_is_illegal_and_leaves_world_unchanged() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})
    before = copy.deepcopy(env.state())

    out = env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": ["not_a_reason"],
        }
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "bad_schema"
    after = env.state()
    assert after.last_verdict == before.last_verdict
    assert after.last_plan == before.last_plan
    assert after.last_reasons == before.last_reasons


def test_accept_with_empty_items_is_illegal_and_leaves_world_unchanged() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})
    before = copy.deepcopy(env.state())

    out = env.step({"op": "submit_plan", "items": [], "verdict": "accept"})

    assert out["ok"] is False
    assert out["error"]["code"] == "bad_schema"
    after = env.state()
    assert after.last_verdict == "accept"
    assert after.last_plan == before.last_plan
    assert after.last_reasons == ()


def test_unknown_verdict_is_illegal_and_leaves_world_unchanged() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})
    before = copy.deepcopy(env.state())

    out = env.step(
        {
            "op": "submit_plan",
            "items": [{"food_id": "oats", "grams": 40}],
            "verdict": "maybe",
        }
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "bad_schema"
    after = env.state()
    assert after.last_verdict == "accept"
    assert after.last_plan == before.last_plan


def test_roster_complete_s0_round_trips_body_facts_through_reset_and_get_profile() -> None:
    s0 = demo_state()
    s0.profile = Profile(
        user_id="roster-ada",
        allergies=("peanut",),
        windows={"kcal": (1800.0, 2200.0), "protein_g": (90.0, 140.0)},
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="cut",
    )
    env = NutriEnv()
    opening = env.reset(s0)["profile"]
    observed = env.step({"op": "get_profile"})["observation"]["profile"]
    for profile in (opening, observed):
        assert profile["sex"] == "female"
        assert profile["age_y"] == 34
        assert profile["height_cm"] == 165.0
        assert profile["weight_kg"] == 62.0
        assert profile["activity"] == "light"
        assert profile["phase"] == "cut"
        assert profile["windows"] == {"kcal": [1800.0, 2200.0], "protein_g": [90.0, 140.0]}


def _ada_state(*, phase: str = "maintain", weight_kg: float = 62.0) -> object:
    s0 = demo_state()
    windows = derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=weight_kg,
        activity="light",
        phase=phase,
    )
    s0.profile = Profile(
        user_id="roster-ada",
        allergies=("peanut",),
        windows=windows,
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=weight_kg,
        activity="light",
        phase=phase,
    )
    return s0


def test_patching_weight_rederives_daily_windows() -> None:
    env = NutriEnv()
    s0 = _ada_state()
    env.reset(s0)
    before = env.state().profile.windows

    out = env.step({"op": "update_profile", "patch": {"weight_kg": 80.0}})

    assert out["ok"] is True
    profile = env.state().profile
    assert profile.weight_kg == 80.0
    assert profile.allergies == ("peanut",)
    assert profile.windows != before
    assert profile.windows == derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=80.0,
        activity="light",
        phase="maintain",
    )


def test_patching_phase_rederives_daily_windows() -> None:
    env = NutriEnv()
    env.reset(_ada_state())

    out = env.step({"op": "update_profile", "patch": {"phase": "cut"}})

    assert out["ok"] is True
    profile = env.state().profile
    assert profile.phase == "cut"
    assert profile.weight_kg == 62.0
    assert profile.windows == derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="cut",
    )


def test_body_plus_windows_patch_rederives_fully() -> None:
    """A weight patch is not windows-only; stale window keys in the same
    patch do not survive (ticket 04)."""
    env = NutriEnv()
    s0 = _ada_state()
    env.reset(s0)
    stale = {key: list(bounds) for key, bounds in s0.profile.windows.items()}

    out = env.step(
        {"op": "update_profile", "patch": {"weight_kg": 80.0, "windows": stale}}
    )

    assert out["ok"] is True
    profile = env.state().profile
    assert profile.weight_kg == 80.0
    expected = derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=80.0,
        activity="light",
        phase="maintain",
    )
    assert profile.windows == expected
    assert profile.windows != s0.profile.windows


def test_windows_only_patch_does_not_rederive() -> None:
    env = NutriEnv()
    s0 = _ada_state()
    env.reset(s0)
    custom = [2100.0, 2500.0]

    out = env.step({"op": "update_profile", "patch": {"windows": {"kcal": custom}}})

    assert out["ok"] is True
    profile = env.state().profile
    assert profile.weight_kg == 62.0
    assert profile.phase == "maintain"
    assert profile.windows["kcal"] == (2100.0, 2500.0)
    assert profile.windows["protein_g"] == s0.profile.windows["protein_g"]
    assert profile.windows["sodium_mg"] == s0.profile.windows["sodium_mg"]


def test_incomplete_body_patch_does_not_invent_windows() -> None:
    env = NutriEnv()
    s0 = demo_state()
    env.reset(s0)
    before = dict(s0.profile.windows)

    out = env.step({"op": "update_profile", "patch": {"weight_kg": 80.0}})

    assert out["ok"] is True
    profile = env.state().profile
    assert profile.weight_kg == 80.0
    assert profile.sex is None
    assert profile.windows == before


def test_invalid_body_patch_is_atomic() -> None:
    env = NutriEnv()
    env.reset(_ada_state())
    before = copy.deepcopy(env.state())

    out = env.step(
        {"op": "update_profile", "patch": {"weight_kg": 80.0, "windows": {"kcal": [2500, 2100]}}}
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "bad_schema"
    after = env.state()
    assert after.profile == before.profile
    assert after.ledger == before.ledger


def test_reset_and_get_profile_expose_verdict_and_reasons() -> None:
    env = NutriEnv()
    opening = env.reset(demo_state())
    assert opening["last_verdict"] is None
    assert opening["last_reasons"] == []

    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})
    accepted = env.step({"op": "get_profile"})["observation"]
    assert accepted["last_verdict"] == "accept"
    assert accepted["last_reasons"] == []
    assert accepted["last_plan"] == [{"food_id": "egg", "grams": 100.0}]

    env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": ["fiber_g_lo", "allergy"],
        }
    )
    rejected = env.step({"op": "get_profile"})["observation"]
    assert rejected["last_verdict"] == "reject"
    assert rejected["last_reasons"] == ["allergy", "fiber_g_lo"]
    assert rejected["last_plan"] == []

    seeded = demo_state()
    seeded.last_verdict = "reject"
    seeded.last_reasons = ("kcal_hi",)
    seeded_obs = NutriEnv().reset(seeded)
    assert seeded_obs["last_verdict"] == "reject"
    assert seeded_obs["last_reasons"] == ["kcal_hi"]


def test_env_readme_documents_verdict_envelope() -> None:
    text = Path("src/nutrienv/env/README.md").read_text(encoding="utf-8")
    assert "last_verdict" in text
    assert "last_reasons" in text
    assert "verdict?" in text
    assert "reasons?" in text


def test_env_readme_documents_profile_body_facts() -> None:
    text = Path("src/nutrienv/env/README.md").read_text(encoding="utf-8")
    assert "age_y" in text
    assert "height_cm" in text
    assert "weight_kg" in text
    assert "activity" in text
    assert "phase" in text
    assert "maintain" in text
    assert "re-derive" in text
    assert "windows-only" in text

