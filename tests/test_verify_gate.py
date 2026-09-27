"""Verify-then-revise gate (DESIGN_v2 2026-09-25). No network."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nutrienv.harness.buddy import (
    VERIFY_PLACEBO_BODY,
    BuddyHarness,
    ObservationCache,
    build_scaffold,
    track_ledger,
    verify_plan,
)

ROOT = Path(__file__).resolve().parents[1]

# Per 100 g. One protein-dense food, one near-empty one.
FOODS = {
    "chicken": {"nutrients": {"kcal": 165.0, "protein_g": 31.0, "carb_g": 0.0, "fat_g": 3.6,
                              "fiber_g": 0.0, "sodium_mg": 74.0}, "allergen_tags": []},
    "rice": {"nutrients": {"kcal": 130.0, "protein_g": 2.7, "carb_g": 28.0, "fat_g": 0.3,
                           "fiber_g": 0.4, "sodium_mg": 1.0}, "allergen_tags": []},
}
DAILY = {"kcal": [2000.0, 2000.0], "protein_g": [60.0, 100.0], "carb_g": [250.0, 300.0],
         "fat_g": [60.0, 70.0], "fiber_g": [25.0, 30.0], "sodium_mg": [0.0, 2300.0]}


def _cache(rows=()) -> ObservationCache:
    cache = ObservationCache(profile={"allergies": [], "windows": DAILY}, foods=dict(FOODS))
    track_ledger(cache, {"op": "reset", "ledger": [dict(r) for r in rows]})
    return cache


def _plan(*items) -> dict:
    return {"op": "submit_plan", "items": [{"food_id": f, "grams": g} for f, g in items]}


def test_track_ledger_follows_log_amend_and_ignores_refusals() -> None:
    cache = _cache([{"food_id": "chicken", "grams": 100.0, "nutrients": {"protein_g": 31.0}}])
    assert cache.ledger_rows == [{"food_id": "chicken", "grams": 100.0}]
    track_ledger(cache, {"op": "log_meal", "row": {"food_id": "rice", "grams": 200.0}})
    track_ledger(cache, {"op": "amend_meal", "index": 0, "row": {"food_id": "chicken", "grams": 50.0}})
    track_ledger(cache, {"error": {"code": "bad_schema"}})
    track_ledger(cache, {"op": "amend_meal", "index": 9, "row": {"food_id": "rice", "grams": 1.0}})
    assert cache.ledger_rows == [
        {"food_id": "chicken", "grams": 50.0},
        {"food_id": "rice", "grams": 200.0},
    ]


def test_ceiling_uses_the_scorers_slack_not_the_raw_hi() -> None:
    # Protein has no meal share, so its dinner cap is the daily remainder, 100 g. 330 g chicken
    # is 102.3 g protein: over hi, under 1.15 * hi -> the Scorer passes it, so the gate must too.
    near = verify_plan(_plan(("chicken", 330.0)), _cache(), query="what for dinner?")
    assert all(not line.startswith("protein_g") for line in near.lines)
    over = verify_plan(_plan(("chicken", 400.0)), _cache(), query="what for dinner?")
    assert not over.ok
    assert any(line.startswith("protein_g: plan 124.0 g exceeds the dinner ceiling 100.0 g")
               for line in over.lines)


def test_amended_ledger_moves_the_remaining_window() -> None:
    cache = _cache([{"food_id": "chicken", "grams": 250.0}])  # 77.5 g protein eaten
    plan = _plan(("chicken", 150.0), ("rice", 300.0))          # 54.6 g protein
    assert any(l.startswith("protein_g") for l in verify_plan(plan, cache, "dinner?").lines)
    track_ledger(cache, {"op": "amend_meal", "index": 0, "row": {"food_id": "chicken", "grams": 100.0}})
    assert not any(l.startswith("protein_g") for l in verify_plan(plan, cache, "dinner?").lines)


def test_evaluate_hand_ins_are_never_checked() -> None:
    for verdict in ("accept", "reject"):
        action = {**_plan(("chicken", 900.0)), "verdict": verdict}
        assert verify_plan(action, _cache(), "dinner?").status == "not_applicable"


def test_no_meal_named_has_no_energy_floor() -> None:
    small = verify_plan(_plan(("rice", 50.0)), _cache(), query="a lower-fat combo please")
    assert small.ok
    dinner = verify_plan(_plan(("rice", 50.0)), _cache(), query="what for dinner?")
    assert any(line.startswith("kcal") and "below" in line for line in dinner.lines)


def test_unknown_food_skips_instead_of_refusing() -> None:
    result = verify_plan(_plan(("mystery", 500.0)), _cache(), query="dinner?")
    assert result.ok and result.status == "skipped"


class _Scripted:
    def __init__(self, actions):
        self._actions = list(actions)
        self.messages = [{"role": "system", "content": "manual"}]
        self.revisions: list[str] = []

    def clone(self):
        return _Scripted(self._actions)

    def act(self, observation, query, history):
        return self._actions.pop(0)

    def revise(self, feedback):
        self.revisions.append(feedback)
        return self._actions.pop(0)


def _reset_obs() -> dict:
    return {"op": "reset", "profile": {"allergies": [], "windows": DAILY}, "ledger": []}


def test_verify_records_the_bounced_plan_before_revise_and_quotes_numbers() -> None:
    bad, good = _plan(("chicken", 400.0)), _plan(("chicken", 150.0), ("rice", 300.0))
    inner = _Scripted([bad, good])
    gate = BuddyHarness(inner, verify=True, food_lookup=FOODS.get)
    action = gate.act(_reset_obs(), "what for dinner?", history=[{}, {}])
    assert action == good
    assert len(gate.verify_events) == 1
    event = gate.verify_events[0]
    assert event["action"] == bad and event["env_steps_before"] == 2
    assert "exceeds the dinner ceiling" in inner.revisions[0]
    assert "124.0" in inner.revisions[0]


def test_placebo_fires_on_the_same_plan_without_numbers() -> None:
    bad, good = _plan(("chicken", 400.0)), _plan(("chicken", 150.0), ("rice", 300.0))
    inner = _Scripted([bad, good])
    gate = BuddyHarness(inner, verify=True, placebo=True, food_lookup=FOODS.get)
    gate.act(_reset_obs(), "what for dinner?", history=[])
    assert VERIFY_PLACEBO_BODY in inner.revisions[0]
    assert not any(ch.isdigit() for ch in inner.revisions[0])
    assert gate.verify_events[0]["lines"]  # what verify would have said is still recorded


def test_bounces_stop_after_max_regen_and_the_plan_goes_through() -> None:
    bad = _plan(("chicken", 400.0))
    inner = _Scripted([bad, bad, bad])
    gate = BuddyHarness(inner, verify=True, food_lookup=FOODS.get)
    assert gate.act(_reset_obs(), "dinner?", history=[]) == bad
    assert len(gate.verify_events) == 2 and gate.gate_exhausted == 1


def test_verify_scaffolds_carry_their_flags_through_clone() -> None:
    from nutrienv.harness.react import ReActHarness

    for name, placebo in (("verify", False), ("verify-placebo", True)):
        built = build_scaffold(name, inner=ReActHarness(api_key="k", version="v2"))
        copy = built.clone()
        assert copy.verify and copy.placebo is placebo
        # No system line is added: before the first bounce the model sees the baseline prompt.
        assert copy.inner.messages[0]["content"] == ReActHarness(api_key="k", version="v2").messages[0]["content"]


def _counterfactual():
    path = ROOT / "scripts" / "verify_counterfactual.py"
    spec = importlib.util.spec_from_file_location("verify_counterfactual_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_counterfactual_classification() -> None:
    cf = _counterfactual()
    assert cf.classify({"resolved": True, "passed": False}, True) == "rescued"
    assert cf.classify({"resolved": True, "passed": True}, False) == "broken"
    assert cf.classify({"resolved": True, "passed": True}, True) == "false_reject_harmless"
    assert cf.classify({"resolved": False}, True) == "unresolved"


def _task(task_id: str):
    from nutrienv.bench import load_split

    return next(t for t in load_split(ROOT / "data" / "splits" / "nutrienv-v1.0.json")
                if t.id == task_id)


def test_score_pairs_replays_the_prefix_and_submits_the_first_bounced_plan() -> None:
    cf = _counterfactual()
    task = _task("adr20-rec-5018")
    bounced = _plan(("2705956", 1000.0))            # a kilo of chicken breast: over every cap
    row = {
        "id": task.id, "passed": True, "tag": "pass",
        "steps": [{"action": {"op": "get_profile"}}, {"action": {"op": "get_ledger"}},
                  {"action": _plan(("2705956", 150.0))}],
        "verify_events": [
            {"env_steps_before": 2, "action": bounced},
            {"env_steps_before": 2, "action": _plan(("2705956", 900.0))},
        ],
    }
    [rec] = cf.score_pairs([row], {task.id: task}, arm="verify", run="r1")
    assert rec["cf"]["resolved"] and not rec["cf"]["passed"]
    assert rec["outcome"] == "rescued" and rec["window_only"]
    assert rec["arm"] == "verify" and rec["run"] == "r1" and rec["bounces"] == 2


def test_a_plan_env_would_refuse_is_unresolved_not_a_failure() -> None:
    cf = _counterfactual()
    task = _task("adr20-rec-5018")
    row = {"id": task.id, "passed": True, "tag": "pass", "steps": [],
           "verify_events": [{"env_steps_before": 0, "action": _plan(("2705956", 0.0))}]}
    [rec] = cf.score_pairs([row], {task.id: task})
    assert rec["outcome"] == "unresolved"
    assert cf.counts([rec])["false_reject_rate"] == 0.0


def test_window_only_excludes_a_counterfactual_that_also_failed_elsewhere() -> None:
    cf = _counterfactual()
    assert cf.failing_tags({"resolved": True, "passed": False, "tag": "log_miss",
                            "sub_tags": ["log_miss", "window"]}) == ["log_miss", "window"]
    assert cf.failing_tags({"resolved": True, "passed": False, "tag": "window",
                            "sub_tags": ["pass", "window"]}) == ["window"]


def _rec(arm, task, outcome):
    return {"arm": arm, "run": "r", "id": task, "outcome": outcome, "window_only": True,
            "window_anywhere": True, "drift": 0}


def test_decide_applies_the_preregistered_rules() -> None:
    cf = _counterfactual()
    universe = [f"t{i}" for i in range(51)]
    strong = {
        "records": [_rec("verify", f"t{i}", "rescued") for i in range(12)]
        + [_rec("verify-placebo", f"t{i}", "still_failed") for i in range(12)],
        "runs": {"verify": ["r"], "verify-placebo": ["r"]},
        "universe": universe,
    }
    out = cf.decide(strong)
    assert out["claim_a"]["verdict"] == "effective" and out["claim_a"]["ci95"][0] > 0
    assert out["claim_b"]["verdict"] == "effective"
    null = {
        "records": [_rec("verify", f"t{i}", "still_failed") for i in range(12)]
        + [_rec("verify-placebo", f"t{i}", "still_failed") for i in range(12)],
        "runs": {"verify": ["r"], "verify-placebo": ["r"]},
        "universe": universe,
    }
    out = cf.decide(null)
    assert out["claim_a"]["verdict"] == "no effect"
    assert out["claim_b"]["verdict"] == "inconclusive"
    unsafe = dict(strong, records=strong["records"] + [_rec("verify", "t40", "broken")] * 2
                  + [_rec("verify", "t41", "false_reject_harmless")])
    assert cf.decide(unsafe)["verify"]["false_reject_rate"] > cf.MAX_FALSE_REJECT_RATE
    assert cf.decide(unsafe)["claim_a"]["effective"] is False


def test_the_bounce_cap_is_per_episode_not_per_step() -> None:
    bad, read = _plan(("chicken", 400.0)), {"op": "get_food", "food_id": "rice"}
    # Step 1: bounce, the model answers with a read. Step 2: bounce again, then the cap is spent
    # and the next out-of-window plan goes through untouched.
    inner = _Scripted([bad, read, bad, bad])
    gate = BuddyHarness(inner, verify=True, food_lookup=FOODS.get)
    assert gate.act(_reset_obs(), "dinner?", history=[]) == read
    assert gate.act({"op": "get_food"}, "dinner?", history=[{}]) == bad
    assert len(gate.verify_events) == 2 and len(inner.revisions) == 2
    assert gate.verify_drift == 1 and gate.gate_exhausted == 1
    gate.reset()
    assert gate.verify_events == [] and gate.verify_drift == 0


# --- submit preview (DESIGN_v3.1) -------------------------------------------------------------

from nutrienv.harness.buddy import plan_key, plan_preview, preview_text  # noqa: E402

_JUDGMENT = ("exceed", "below", "over", "under", "violat", "ok", "fail", "pass", "wrong")


def test_preview_shows_numbers_and_the_graded_range_without_judging() -> None:
    shown = plan_preview(_plan(("chicken", 400.0)), _cache(), query="what for dinner?")
    text = preview_text(shown)
    assert "protein_g 124.0 g" in text
    # The graded protein ceiling is 1.15 x the 100 g remainder: a passing plan never reads as over.
    assert "protein_g <= 115.0 g" in text and "kcal 600.0-800.0" in text
    lowered = text.lower().replace("not submitted", "")
    assert not any(word in lowered for word in _JUDGMENT)


def test_plan_key_ignores_order_split_rows_number_format_and_accept_reasons() -> None:
    a = {"op": "submit_plan", "items": [{"food_id": "rice", "grams": 100}, {"food_id": "chicken", "grams": 150}]}
    b = {"op": "submit_plan", "verdict": "accept", "reasons": ["kcal_hi"],
         "items": [{"food_id": "chicken", "grams": 100.0}, {"food_id": "rice", "grams": 100.0},
                   {"food_id": "chicken", "grams": 50}]}
    assert plan_key(a) == plan_key(b)
    r1 = {"op": "submit_plan", "verdict": "reject", "items": [], "reasons": ["kcal_hi"]}
    r2 = {"op": "submit_plan", "verdict": "reject", "items": [], "reasons": ["protein_g_hi"]}
    assert plan_key(r1) != plan_key(r2)


def test_repeating_the_previewed_plan_commits_the_stored_one() -> None:
    first = {**_plan(("chicken", 150.0), ("rice", 300.0))}
    restated = {"op": "submit_plan", "items": [{"food_id": "rice", "grams": 300}, {"food_id": "chicken", "grams": 150}]}
    inner = _Scripted([first, restated])
    gate = BuddyHarness(inner, preview=True, food_lookup=FOODS.get)
    assert gate.act(_reset_obs(), "what for dinner?", history=[]) == first
    assert len(gate.verify_events) == 1 and gate.verify_events[0]["kind"] == "preview"
    assert gate.verify_status == {"previewed": 1, "confirmed": 1}


def test_a_changed_plan_is_previewed_again_until_the_episode_cap() -> None:
    p1, p2, p3 = _plan(("chicken", 400.0)), _plan(("chicken", 300.0)), _plan(("chicken", 200.0))
    inner = _Scripted([p1, p2, p3])
    gate = BuddyHarness(inner, preview=True, food_lookup=FOODS.get)
    assert gate.act(_reset_obs(), "dinner?", history=[]) == p3
    assert len(gate.verify_events) == 2 and gate.verify_status["cap_reached"] == 1


def test_a_read_after_a_preview_is_a_normal_step_and_a_later_repeat_confirms() -> None:
    plan, read = _plan(("chicken", 150.0), ("rice", 300.0)), {"op": "get_food", "food_id": "rice"}
    inner = _Scripted([plan, read, plan])
    gate = BuddyHarness(inner, preview=True, food_lookup=FOODS.get)
    assert gate.act(_reset_obs(), "dinner?", history=[]) == read
    assert gate.verify_drift == 1
    assert gate.act({"op": "get_food"}, "dinner?", history=[{}]) == plan
    assert len(gate.verify_events) == 1  # the repeat confirmed, no second preview


def test_evaluate_accept_is_previewed_and_an_empty_reject_is_not() -> None:
    accept = {**_plan(("chicken", 150.0), ("rice", 300.0)), "verdict": "accept"}
    assert plan_preview(accept, _cache(), "dinner?") is not None
    reject = {"op": "submit_plan", "verdict": "reject", "items": [], "reasons": ["kcal_hi"]}
    inner = _Scripted([reject])
    gate = BuddyHarness(inner, preview=True, food_lookup=FOODS.get)
    assert gate.act(_reset_obs(), "dinner?", history=[]) == reject
    assert gate.verify_events == []


def test_preview_scaffold_survives_clone() -> None:
    from nutrienv.harness.react import ReActHarness

    built = build_scaffold("preview", inner=ReActHarness(api_key="k", version="v2"))
    assert built.clone().preview is True


def test_preview_outcomes_separate_confirmation_from_change() -> None:
    cf = _counterfactual()
    ok, bad = {"resolved": True, "passed": True}, {"resolved": True, "passed": False}
    assert cf.classify_preview(ok, True, unchanged=True) == "confirmed_pass"
    assert cf.classify_preview(bad, False, unchanged=True) == "confirmed_fail"
    assert cf.classify_preview(ok, False, unchanged=False) == "broken"
    assert cf.classify_preview(bad, True, unchanged=False) == "rescued"
    assert cf.classify_preview(ok, True, unchanged=False) == "changed_still_pass"


def test_score_pairs_marks_a_confirmed_preview() -> None:
    cf = _counterfactual()
    task = _task("adr20-rec-5018")
    plan = _plan(("2705956", 1000.0))
    row = {"id": task.id, "passed": False, "tag": "window",
           "steps": [{"action": {"op": "get_profile"}}, {"action": plan}],
           "verify_events": [{"kind": "preview", "env_steps_before": 1, "action": plan}]}
    [rec] = cf.score_pairs([row], {task.id: task})
    assert rec["outcome"] == "confirmed_fail"


def test_decide_preview_applies_claim_c() -> None:
    cf = _counterfactual()
    recs = [dict(_rec("preview", f"t{i}", "rescued"), cf_tag="window", actual_tag="pass")
            for i in range(10)]
    recs += [dict(_rec("preview", f"t{i}", "confirmed_pass"), cf_tag="pass", actual_tag="pass")
             for i in range(10, 40)]
    out = cf.decide({"records": recs, "runs": {"preview": ["a", "b"]},
                     "universe": [f"t{i}" for i in range(51)]})
    assert out["claim_c"]["verdict"] == "effective"
    harm = [dict(_rec("preview", f"t{i}", "broken"), cf_tag="pass", actual_tag="window")
            for i in range(12)]
    out = cf.decide({"records": harm, "runs": {"preview": ["a", "b"]},
                     "universe": [f"t{i}" for i in range(51)]})
    assert out["claim_c"]["verdict"] == "harmful"


def test_rounds_without_a_window_id_are_told_apart_by_directory() -> None:
    cf = _counterfactual()
    name = "ablation_m_preview.json"
    r1 = cf.run_id({"config": {}}, Path("runs/r1") / name)
    r2 = cf.run_id({"config": {}}, Path("runs/r2") / name)
    assert r1 != r2
    assert cf.run_id({"config": {"run_window_id": "20260925T173744"}}, Path(name)) == "20260925T173744"
