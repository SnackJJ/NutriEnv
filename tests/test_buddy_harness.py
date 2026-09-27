"""Buddy policy plugins: pin, sandbox calc, pre-submit bounce. No network."""

from __future__ import annotations

import json

from nutrienv.bench import Oracle, Scorer
from nutrienv.env import NutriEnv
from nutrienv.harness.buddy import (
    SCAFFOLDS,
    BuddyHarness,
    ObservationCache,
    build_scaffold,
    check_write,
    ingest_observation,
    occasion_from_query,
    sandbox_sheet,
    scale_items,
)
from nutrienv.harness.react import ReActHarness, context_messages
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.types import Profile


class ScriptedInner:
    def __init__(self, actions: list[dict]) -> None:
        self._actions = list(actions)
        self.messages: list[dict] = [{"role": "system", "content": "manual"}]
        self.revisions: list[str] = []
        self.observations: list[dict] = []

    def reset(self, task: object | None = None) -> None:
        self.messages = [{"role": "system", "content": "manual"}]

    def clone(self) -> "ScriptedInner":
        return ScriptedInner(list(self._actions))

    def ensure_task(self, query: str) -> None:
        if len(self.messages) == 1:
            self.messages.append({"role": "user", "content": f"Task:\n{query}"})

    def act(self, observation: dict, query: str, history: list) -> dict:
        self.ensure_task(query)
        self.observations.append(observation)
        self.messages.append(
            {"role": "user", "content": "Observation:\n" + json.dumps(observation)[:400]}
        )
        action = self._actions.pop(0)
        self.messages.append({"role": "assistant", "content": json.dumps(action)})
        return action

    def revise(self, feedback: str) -> dict:
        self.revisions.append(feedback)
        self.messages.append({"role": "user", "content": feedback})
        action = self._actions.pop(0)
        self.messages.append({"role": "assistant", "content": json.dumps(action)})
        return action


def _peanut_obs() -> dict:
    return {
        "op": "reset",
        "profile": {
            "allergies": ["peanut"],
            "windows": {"kcal": [120.0, 140.0]},
        },
        "ledger_totals": {},
        "food_id": "peanut_butter",
        "nutrients": {"kcal": 588.0, "protein_g": 25.1},
        "allergen_tags": ["peanut"],
    }


def test_check_write_blocks_allergen_plan_not_log() -> None:
    cache = ObservationCache()
    ingest_observation(cache, _peanut_obs())
    ingest_observation(
        cache,
        {
            "food_id": "white_rice",
            "nutrients": {"kcal": 130.0},
            "allergen_tags": [],
        },
    )
    blocked = check_write(
        {"op": "submit_plan", "items": [{"food_id": "peanut_butter", "grams": 25.0}]},
        cache,
    )
    assert blocked.ok is False
    assert any(reason.startswith("allergy") for reason in blocked.reasons)

    logged = check_write(
        {"op": "log_meal", "food_id": "peanut_butter", "grams": 25.0},
        cache,
    )
    assert logged.ok is True

    reject = check_write({"op": "submit_plan", "verdict": "reject", "items": []}, cache)
    assert reject.ok is True


def test_check_write_reports_what_it_did_not_just_ok() -> None:
    """`ok` alone conflates four different outcomes, and the not_applicable ones are the
    majority of calls because every non-submit_plan action lands there. Counting them as
    approvals would overstate the gate by an order of magnitude, and a gate that could not
    check would be indistinguishable from one that checked and found nothing."""
    cache = ObservationCache()

    assert check_write("garbage", cache).status == "not_applicable"
    assert (
        check_write({"op": "log_meal", "food_id": "x", "grams": 100}, cache).status
        == "not_applicable"
    )
    assert (
        check_write({"op": "submit_plan", "verdict": "reject", "items": []}, cache).status
        == "not_applicable"
    )

    # A plan whose nutrients cannot be scaled is a *skip*, not an approval: the window half of
    # the check cannot be trusted. The skip reason travels in `reasons` (this used to be dropped
    # by the caller) and the status keeps it separable.
    unverifiable = check_write(
        {"op": "submit_plan", "items": [{"food_id": "unknown", "grams": 100}]}, cache
    )
    assert unverifiable.ok is True
    assert unverifiable.status == "skipped"
    assert any("unverifiable" in reason for reason in unverifiable.reasons)


def test_buddy_harness_forwards_the_step_budget_to_the_prompt_builder() -> None:
    """The wrapper renders no budget of its own: the inner harness does. It has to receive the
    Runner's per-task number, or the model is told the inner constructor default (12) on the
    30-step composite/recommend tasks."""
    inner = ReActHarness(api_key="dummy", version="v2")
    wrapper = BuddyHarness(inner, label="gate", check=True)

    wrapper.set_step_budget(30)

    assert inner.max_steps == 30


def test_check_write_blocks_plan_over_daily_kcal_hi() -> None:
    cache = ObservationCache()
    ingest_observation(cache, _peanut_obs())
    ingest_observation(
        cache,
        {
            "food_id": "white_rice",
            "nutrients": {"kcal": 130.0, "protein_g": 2.7},
            "allergen_tags": [],
        },
    )
    # No meal word → snack/remainder. 200 g rice = 260 kcal > 140 daily hi.
    blocked = check_write(
        {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 200.0}]},
        cache,
    )
    assert blocked.ok is False
    assert any("kcal_hi" in reason for reason in blocked.reasons)

    ok = check_write(
        {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 100.0}]},
        cache,
    )
    assert ok.ok is True


def test_check_write_uses_dinner_share_not_daily_hi() -> None:
    cache = ObservationCache()
    ingest_observation(
        cache,
        {
            "profile": {
                "allergies": [],
                "windows": {"kcal": [2000.0, 2000.0], "protein_g": [0.0, 200.0]},
            },
            "ledger_totals": {},
        },
    )
    ingest_observation(
        cache,
        {
            "op": "get_food",
            "food": {
                "food_id": "white_rice",
                "nutrients": {"kcal": 130.0, "protein_g": 2.7},
                "allergen_tags": [],
            },
        },
    )
    # 800 g rice = 1040 kcal: under daily 2000, over dinner 40% = 800.
    over = check_write(
        {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 800.0}]},
        cache,
        query="Recommend a dinner that fits my daily targets.",
    )
    assert over.ok is False
    assert any("kcal_hi" in reason for reason in over.reasons)

    # 500 g = 650 kcal sits in dinner 30–40% of 2000.
    ok = check_write(
        {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 500.0}]},
        cache,
        query="Recommend a dinner that fits my daily targets.",
    )
    assert ok.ok is True


def test_ingest_reads_env_get_food_and_ledger_totals() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    food_obs = env.step({"op": "get_food", "food_id": "white_rice"})["observation"]
    cache = ObservationCache()
    ingest_observation(cache, food_obs)
    assert "white_rice" in cache.foods
    assert cache.foods["white_rice"]["nutrients"]["kcal"] == 130.0

    logged = env.step({"op": "log_meal", "food_id": "white_rice", "grams": 200.0})
    ingest_observation(cache, logged["observation"])
    assert cache.ledger_totals["kcal"] == 260.0

    ledger_obs = env.step({"op": "get_ledger"})["observation"]
    other = ObservationCache()
    ingest_observation(other, ledger_obs)
    assert other.ledger_totals["kcal"] == 260.0


def test_occasion_from_query_uses_last_meal_word() -> None:
    assert occasion_from_query("I had granola for lunch, so what should I eat for dinner?") == "dinner"
    assert occasion_from_query("What are some good breakfast options?") == "breakfast"
    assert occasion_from_query("Add a milk allergy.") is None


def test_check_bounces_dinner_over_share_from_real_get_food() -> None:
    env = NutriEnv()
    reset_obs = env.reset(demo_state())
    food_obs = env.step({"op": "get_food", "food_id": "white_rice"})["observation"]
    inner = ScriptedInner(
        [
            {"op": "get_food", "food_id": "white_rice"},
            {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 800.0}]},
            {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 500.0}]},
        ]
    )
    harness = BuddyHarness(inner, check=True)
    query = "What do you recommend for dinner?"
    harness.act(reset_obs, query, [])
    action = harness.act(food_obs, query, [])
    assert action["items"][0]["grams"] == 500.0
    assert harness.regen_fired == 1
    assert inner.revisions
    assert "kcal_hi" in inner.revisions[0]


def test_reset_clears_the_gate_tally() -> None:
    """The tally belongs to one episode. `run_ablation` reads it after an episode, but the runner
    reuses a harness when `fresh=False` with k > 1, so a tally left over from the previous episode
    would be attributed to this one -- the same shape as counting not_applicable calls as
    approvals."""
    env = NutriEnv()
    reset_obs = env.reset(demo_state())
    food_obs = env.step({"op": "get_food", "food_id": "white_rice"})["observation"]
    inner = ScriptedInner(
        [
            {"op": "get_food", "food_id": "white_rice"},
            {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 800.0}]},
            {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 500.0}]},
        ]
    )
    harness = BuddyHarness(inner, check=True)
    query = "What do you recommend for dinner?"
    harness.act(reset_obs, query, [])
    harness.act(food_obs, query, [])
    # get_food is not checkable, the oversized plan violates, the bounce is re-checked and passes.
    assert harness.gate_status == {"not_applicable": 1, "violation": 1, "approved": 1}
    # A recommendation hand-in, not an evaluate one: the shape is what the status cannot show.
    assert harness.gate_fired_shapes == {"submit_plan": 1}

    harness.reset()

    assert harness.gate_status == {}
    assert harness.regen_fired == 0


def test_gate_records_that_it_refused_an_evaluate_hand_in() -> None:
    """`check_write` also judges a `submit_plan` that carries a verdict, and that shape is scored
    against an exact candidate plan rather than "any plan that fits". So a bounce costs more
    there, and its rate has to be separable from the recommendation rate."""
    env = NutriEnv()
    reset_obs = env.reset(demo_state())
    food_obs = env.step({"op": "get_food", "food_id": "white_rice"})["observation"]
    inner = ScriptedInner(
        [
            {"op": "get_food", "food_id": "white_rice"},
            {
                "op": "submit_plan",
                "verdict": "accept",
                "items": [{"food_id": "white_rice", "grams": 800.0}],
            },
            {
                "op": "submit_plan",
                "verdict": "accept",
                "items": [{"food_id": "white_rice", "grams": 500.0}],
            },
        ]
    )
    harness = BuddyHarness(inner, check=True)
    query = "Is this a good dinner?"
    harness.act(reset_obs, query, [])
    harness.act(food_obs, query, [])

    assert harness.gate_fired_shapes == {"submit_plan:verdict": 1}


def test_sandbox_sheet_scales_and_reports_remaining() -> None:
    cache = ObservationCache()
    ingest_observation(
        cache,
        {
            "profile": {"allergies": ["peanut"], "windows": {"kcal": [400.0, 800.0]}},
            "ledger_totals": {"kcal": 100.0},
            "food_id": "white_rice",
            "nutrients": {"kcal": 130.0},
            "allergen_tags": [],
        },
    )
    sheet = sandbox_sheet(cache)
    # The sheet is arithmetic only: constraint recall belongs to the pin layer, and
    # duplicating it here made the calc and pin arms impossible to tell apart.
    assert "allergies" not in sheet and "windows" not in sheet
    # Without a query there is no meal slot, so the sheet falls back and says so.
    assert sheet["windows_basis"] == "daily_minus_ledger"
    assert sheet["plan_windows"]["kcal"] == [300.0, 700.0]
    assert sheet["foods"]["white_rice"]["nutrients_per_100g"]["kcal"] == 130.0
    totals, _tags, complete = scale_items(
        [{"food_id": "white_rice", "grams": 50.0}], cache.foods
    )
    assert complete is True
    assert totals["kcal"] == 65.0


def test_pin_survives_context_slide() -> None:
    inner = ScriptedInner([{"op": "get_profile"}] * 20)
    harness = BuddyHarness(inner, pin=True)
    observation = _peanut_obs()
    harness.act(observation, "plan dinner", [])
    for index in range(18):
        inner.messages.append({"role": "user", "content": f"Observation:\n{index}"})
        inner.messages.append({"role": "assistant", "content": '{"op": "get_profile"}'})
    sent = context_messages(inner.messages, limit=12)
    assert sent[0]["role"] == "system"
    assert sent[1]["content"].startswith("Task:")
    assert sent[2]["content"].startswith("Pinned constraints:")
    assert "peanut" in sent[2]["content"]


def test_check_regenerates_before_env_step() -> None:
    inner = ScriptedInner(
        [
            {"op": "submit_plan", "items": [{"food_id": "peanut_butter", "grams": 25.0}]},
            {"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 100.0}]},
        ]
    )
    harness = BuddyHarness(inner, calc=True, check=True)
    observation = _peanut_obs()
    ingest_observation(harness.cache, {
        "food_id": "white_rice",
        "nutrients": {"kcal": 130.0},
        "allergen_tags": [],
    })
    action = harness.act(observation, "what should I eat?", [])
    assert action["items"][0]["food_id"] == "white_rice"
    assert inner.revisions
    assert "allergy" in inner.revisions[0]
    assert harness.regen_fired == 1

    env = NutriEnv()
    state = demo_state()
    state.profile = Profile(
        user_id="u",
        allergies=("peanut",),
        windows={"kcal": (120.0, 140.0)},
    )
    env.reset(state)
    result = env.step(action)
    assert result["ok"] is True
    scored = Scorer().score(
        env.state(),
        Oracle(profile=state.profile, last_plan=[], plan_must_fit_windows=True),
    )
    assert scored["passed"] is True
    assert env.state().last_plan[0]["food_id"] == "white_rice"


def test_calc_enriches_observation_without_rewriting_grams() -> None:
    from nutrienv.harness.buddy import SANDBOX_LINE

    inner = ScriptedInner(
        [{"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 200.0}]}]
    )
    harness = BuddyHarness(inner, calc=True)
    action = harness.act(_peanut_obs(), "plan", [])
    assert action["items"][0]["grams"] == 200.0
    sandbox = inner.observations[0]["sandbox"]
    assert "allergies" not in sandbox, "constraint recall is pin's job, not calc's"
    assert "allergen_tags" not in sandbox["foods"]["peanut_butter"]
    assert "peanut_butter" in sandbox["foods"]
    assert SANDBOX_LINE in inner.messages[0]["content"]


def test_exhausted_regen_still_hands_action_to_env() -> None:
    peanut_plan = {
        "op": "submit_plan",
        "items": [{"food_id": "peanut_butter", "grams": 25.0}],
    }
    inner = ScriptedInner([peanut_plan, peanut_plan, peanut_plan])
    harness = BuddyHarness(inner, check=True, max_regen=2)
    action = harness.act(_peanut_obs(), "plan", [])
    assert action["items"][0]["food_id"] == "peanut_butter"
    assert harness.regen_fired == 2, "two gate rejections were observed"
    assert harness.regen_used == 2, "two extra completions were actually spent"
    assert harness.gate_exhausted == 1, "budget exhaustion is counted separately"
    assert len(inner.revisions) == 2


def test_build_scaffold_labels_and_react_passthrough() -> None:
    react = build_scaffold("none", inner=ReActHarness(api_key="dummy", version="v2"))
    assert isinstance(react, ReActHarness)
    # The scaffold is `none` (no policy layers); the harness it builds is labelled `react-v2`,
    # which is its manual generation. The two names answer different questions -- see SCAFFOLDS.
    assert react.label == "react-v2"
    wrapped = build_scaffold("check", inner=ReActHarness(api_key="dummy", version="v2"))
    assert isinstance(wrapped, BuddyHarness)
    assert wrapped.calc and wrapped.check and not wrapped.pin
    # One scaffold per layer so each effect is attributable, plus the legacy combination.
    assert set(SCAFFOLDS) == {
        "none",
        "pin",
        "calc",
        "gate",
        "check",
        "pin-gate",
        "pin-calc",
        "resample",
        "full",
        "verify",
        "verify-placebo",
        "preview",
    }
    assert SCAFFOLDS["gate"] == {"pin": False, "calc": False, "check": True}
    assert SCAFFOLDS["pin"] == {"pin": True, "calc": False, "check": False}


def test_buddy_clone_is_fresh() -> None:
    inner = ScriptedInner([{"op": "get_profile"}])
    harness = BuddyHarness(inner, pin=True, calc=True)
    harness.act(_peanut_obs(), "q", [])
    clone = harness.clone()
    assert clone is not harness
    assert clone.pin is True
    assert clone.cache.profile == {}
    assert clone._pinned is False


# ---------------------------------------------------------------------------
# Fixes required by the external review (2026-09-17)
# ---------------------------------------------------------------------------


def test_pin_refreshes_after_profile_update() -> None:
    """A pin frozen at step 1 lies about the profile once an update task runs."""
    inner = ScriptedInner([{"op": "get_profile"}, {"op": "get_profile"}])
    harness = BuddyHarness(inner, pin=True)
    harness.act(_peanut_obs(), "plan", [])
    first = [m for m in inner.messages if "Pinned constraints" in str(m.get("content"))]
    assert len(first) == 1
    assert "peanut" in first[0]["content"]

    updated = _peanut_obs()
    updated["profile"] = {"allergies": ["peanut", "egg"], "windows": {"kcal": [400.0, 800.0]}}
    harness.act(updated, "plan", [])

    pins = [m for m in inner.messages if "Pinned constraints" in str(m.get("content"))]
    assert len(pins) == 1, "the pin must be rewritten in place, not duplicated"
    assert "egg" in pins[0]["content"], "the pin must track the live profile"


def test_gate_uses_catalog_lookup_for_unfetched_foods() -> None:
    """The gate must not go inert just because the model never fetched a food."""
    from nutrienv.harness.buddy import ObservationCache, check_write

    cache = ObservationCache()
    cache.profile = {"allergies": ["peanut"], "windows": {}}
    action = {"op": "submit_plan", "items": [{"food_id": "mystery", "grams": 30.0}]}

    silent = check_write(action, cache, query="plan")
    assert silent.ok, "unknown food cannot be judged without a lookup"

    def lookup(food_id: str):
        return {"nutrients": {"kcal": 10.0}, "allergen_tags": ["peanut"]}

    judged = check_write(action, cache, query="plan", lookup=lookup)
    assert not judged.ok, "with a lookup the allergen conflict must be caught"


def test_resample_control_spends_completions_without_a_verdict() -> None:
    """The control scaffold must add sampling without adding semantics."""
    inner = ScriptedInner([{"op": "get_profile"}, {"op": "get_profile"}, {"op": "get_profile"}])
    harness = BuddyHarness(inner, resample=2)
    harness.act(_peanut_obs(), "plan", [])
    assert harness.regen_used == 2
    assert harness.regen_fired == 0 and harness.gate_exhausted == 0


def test_clone_carries_lookup_and_resample(monkeypatch) -> None:
    """run_ablation clones one template per task; a dropped field silently disables a fix.

    This is the bug an external review caught: food_lookup and resample were not copied,
    so the catalog-aware gate and the resample control were inert in every real episode.
    """
    monkeypatch.setenv("COMMANDCODE_API_KEY", "dummy")  # resolved at build time; never sent
    def lookup(food_id: str):
        return {"nutrients": {"kcal": 1.0}, "allergen_tags": []}

    for scaffold in ("gate", "resample", "full"):
        template = build_scaffold(scaffold, model="commandcode/inclusionai/ling-3.0-flash-sante:free", version="v2", food_lookup=lookup)
        clone = template.clone()
        assert clone.food_lookup is lookup, scaffold
        assert clone.resample == template.resample, scaffold


def test_lookup_helps_even_when_the_food_was_only_searched() -> None:
    """A search hit carries tags but no nutrients — the common path — so the catalog must
    still supply the numbers the window check needs."""
    from nutrienv.harness.buddy import ObservationCache, check_write

    cache = ObservationCache()
    cache.profile = {"allergies": [], "windows": {"kcal": [100.0, 200.0]}}
    cache.foods = {"mystery": {"allergen_tags": []}}  # seen in search, never fetched
    action = {"op": "submit_plan", "items": [{"food_id": "mystery", "grams": 100.0}]}

    def lookup(food_id: str):
        return {"nutrients": {"kcal": 500.0}, "allergen_tags": []}

    without = check_write(action, cache, query="what should I eat for dinner?")
    with_lookup = check_write(action, cache, query="what should I eat for dinner?", lookup=lookup)
    assert without.ok, "no numbers, no verdict"
    assert not with_lookup.ok, "with the catalog the window violation is visible"
