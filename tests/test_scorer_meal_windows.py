"""Plan windows: re-derived from the gold ledger, stored rounding absorbed, nothing wider.

The recorded cases are the 2026-09-23 runs on the frozen exam (``.scratch/runs``); their end
states are rebuilt here from the split so the tests do not depend on the run files.
"""

from __future__ import annotations

import copy

import pytest

from nutrienv.bench import EXAM_SPLIT_PATH, Oracle, Scorer, load_split
from nutrienv.bench.realize import scored_oracles
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.types import LedgerRow, ledger_totals


@pytest.fixture(scope="module")
def exam() -> dict:
    return {task.id: task for task in load_split(EXAM_SPLIT_PATH)}


@pytest.fixture(scope="module")
def exam_v1_0() -> dict:
    # v1.0's DV windows hold the recorded rounding case; v1.1's AMDR protein cap is far above it.
    return {task.id: task for task in load_split(EXAM_SPLIT_PATH.with_name("nutrienv-v1.0.json"))}


def _end_state(task, ledger, plan):
    state = copy.deepcopy(task.s0)
    state.ledger = list(ledger)
    state.last_plan = [dict(item) for item in plan]
    return state


def _recommend_child(task) -> Oracle:
    return next(o for o in scored_oracles(task.oracle) if o.plan_windows is not None)


def test_stored_rounding_is_absorbed_but_a_real_overage_is_not() -> None:
    # Sodium's ceiling is a health limit: exact but for the 2 dp storage rounding.
    state = demo_state()
    plan = [{"food_id": "chicken_breast", "grams": 100.0}]
    sodium = ledger_totals(
        [LedgerRow("chicken_breast", 100.0, "p")], state.catalog
    )["sodium_mg"]
    state.last_plan = plan

    def score(hi: float) -> str:
        oracle = Oracle(
            profile=state.profile,
            last_plan=[],
            plan_must_fit_windows=True,
            plan_windows={"sodium_mg": (0.0, hi)},
        )
        return Scorer().score(state, oracle)["tag"]

    assert score(sodium - 0.004) == "pass"
    assert score(sodium - 0.006) == "window"
    assert score(sodium * 0.99) == "window"


def test_only_the_fiber_ceiling_carries_slack() -> None:
    # Fiber's hi is a scaled Daily Value, not a limit: 15% over is inside, 16% is not. The AMDR
    # ceilings (protein, carb, fat) are the edge of a range and sodium's is a health limit, so
    # they stay exact, as does kcal's (the meal-share band is its give) and every floor.
    state = demo_state()
    state.last_plan = [{"food_id": "oats", "grams": 100.0}]
    totals = ledger_totals([LedgerRow("oats", 100.0, "p")], state.catalog)

    def score(key: str, lo: float, hi: float) -> str:
        oracle = Oracle(
            profile=state.profile,
            last_plan=[],
            plan_must_fit_windows=True,
            plan_windows={key: (lo, hi)},
        )
        return Scorer().score(state, oracle)["tag"]

    fiber = totals["fiber_g"]
    assert score("fiber_g", 0.0, fiber / 1.14) == "pass"
    assert score("fiber_g", 0.0, fiber / 1.16) == "window"
    for key in ("protein_g", "carb_g", "fat_g", "sodium_mg", "kcal"):
        assert score(key, 0.0, totals[key] / 1.01) == "window", key
    assert score("protein_g", totals["protein_g"] * 1.01, 1e6) == "window"


def test_rounded_ceiling_no_longer_fails_a_plan_inside_the_true_one(exam_v1_0) -> None:
    # adr29-buy-04 on v1.0, deepseek-v4-pro: protein 14.934 g against a ceiling stored as
    # 14.93 g; the ceiling the gold lunch leaves is 48.8 - 33.8655 = 14.9345 g. Protein is judged
    # exactly (AMDR), so only the 2 dp tolerance passes it.
    task = exam_v1_0["adr29-buy-04"]
    state = _end_state(
        task,
        [
            LedgerRow("2705877", 135.0, "today-lunch"),
            LedgerRow("2709778", 120.0, "today-lunch"),
        ],
        [
            {"food_id": "2708408", "grams": 492.0},
            {"food_id": "2709719", "grams": 180.0},
            {"food_id": "2709789", "grams": 35.0},
        ],
    )
    assert Scorer().score(state, task.oracle)["tag"] == "pass"


def _under_logged(task, factor: float) -> list[LedgerRow]:
    tail = [row for o in scored_oracles(task.oracle) for row in (o.ledger_tail or ())]
    return [
        *task.s0.ledger,
        *(LedgerRow(r.food_id, r.grams * factor, r.eaten_at) for r in tail),
    ]


def test_an_in_band_under_log_does_not_widen_the_remainder(exam) -> None:
    task = exam["adr24-comp-8241"]
    child = _recommend_child(task)
    canonical = Scorer._meal_windows(
        _end_state(task, _under_logged(task, 1.0), []), child, task.s0.profile
    )
    underlogged = _under_logged(task, 0.85)
    state = _end_state(task, underlogged, [])
    # Tolerated logging errors must not buy extra dinner nutrients.
    assert Scorer._meal_windows(state, child, task.s0.profile) == canonical
    log_child = next(o for o in scored_oracles(task.oracle) if o.ledger_tail)
    assert Scorer().score(state, log_child)["passed"]


def test_amending_a_given_row_does_not_move_the_windows(exam) -> None:
    # adr20-rec-5018 asks only for a dinner; S0 already holds lunch. Amending that row to
    # 0.851 x its grams keeps the ledger inside the band, and must not buy protein room.
    task = exam["adr20-rec-5018"]
    child = _recommend_child(task)
    (row,) = task.s0.ledger
    amended = [LedgerRow(row.food_id, round(row.grams * 0.851, 1), row.eaten_at)]
    windows = {
        tuple(ledger): Scorer._meal_windows(
            _end_state(task, ledger, []), child, task.s0.profile
        )
        for ledger in (task.s0.ledger, amended)
    }
    assert windows[tuple(task.s0.ledger)] == windows[tuple(amended)]


def test_a_high_protein_dinner_inside_the_amdr_passes_and_energy_still_binds(exam) -> None:
    # adr25-comp-1208: v1.0 capped this dinner's protein at the 46.05 g the 0.8 g/kg RDA left
    # after lunch, so 160 g of chicken (59.8 g) failed. v1.1's cap is 35% of energy (155 g left):
    # it passes. 240 g takes energy past dinner's share and fails.
    task = exam["adr25-comp-1208"]
    plan = [
        {"food_id": "2705956", "grams": 160.0},
        {"food_id": "2708414", "grams": 300.0},
        {"food_id": "2709645", "grams": 155.0},
    ]
    ledger = [LedgerRow("2707537", 16.0, "today-lunch")]
    assert Scorer().score(_end_state(task, ledger, plan), task.oracle)["tag"] == "pass"
    plan[0] = {"food_id": "2705956", "grams": 240.0}
    assert Scorer().score(_end_state(task, ledger, plan), task.oracle)["tag"] == "window"


def test_an_amended_ledger_sets_the_remaining_budget(exam) -> None:
    # adr29-amend-01 asks for dinner "with the updated remaining budget" after whole milk
    # is corrected to almond milk. v1.0 pinned windows authored on the uncorrected row; v1.1
    # authors them on the corrected ledger, so the pin is what the Scorer re-derives.
    task = exam["adr29-amend-01"]
    child = _recommend_child(task)
    state = _end_state(task, list(child.ledger), [])
    windows = Scorer._meal_windows(state, child, task.s0.profile)
    assert windows["sodium_mg"][1] == pytest.approx(2153.6, abs=0.005)
    for key, bounds in child.plan_windows.items():
        assert windows[key] == pytest.approx(bounds, abs=0.005), key


def test_validator_authors_amend_windows_from_the_corrected_ledger(exam) -> None:
    # The authoring gate derived composite windows from S0 + tail; an amend has no tail, so
    # windows authored on the uncorrected rows passed it. It now reads the child's ledger.
    from dataclasses import replace

    from nutrienv.bench.realize import compose_oracles
    from nutrienv.bench.validator import validate_draft
    from nutrienv.world.daily_windows import plan_windows_for_meal

    task = exam["adr29-amend-01"]
    amend_child, rec_child = scored_oracles(task.oracle)

    def authored_on(ledger) -> list[str]:
        eaten = ledger_totals(list(ledger), task.s0.catalog)
        windows = plan_windows_for_meal(task.s0.profile.windows, eaten, "dinner")
        rounded = {k: (round(lo, 2), round(hi, 2)) for k, (lo, hi) in windows.items()}
        child = replace(rec_child, plan_windows=rounded)
        draft = replace(task, oracle=compose_oracles(amend_child, child))
        return [issue for issue in validate_draft(draft) if "plan_windows" in issue]

    assert authored_on(rec_child.ledger) == []
    assert authored_on(task.s0.ledger)


def test_authored_reasons_use_the_judged_ceiling() -> None:
    # An authored reject must never name an overage the Scorer accepts.
    from nutrienv.bench.realize import bind_evaluate_reasons

    state = demo_state()
    meal = [{"food_id": "oats", "grams": 100.0}]
    totals = ledger_totals([LedgerRow("oats", 100.0, "p")], state.catalog)
    reasons = lambda key, hi: bind_evaluate_reasons(meal, {key: (0.0, hi)}, state.catalog, ())
    assert reasons("fiber_g", totals["fiber_g"] / 1.10) == ()
    assert reasons("fiber_g", totals["fiber_g"] / 1.20) == ("fiber_g_hi",)
    assert reasons("protein_g", totals["protein_g"] / 1.01) == ("protein_g_hi",)


def test_an_evaluated_meal_is_not_subtracted_from_its_own_budget() -> None:
    # Log lunch, then "is this lunch okay?": the Evaluate child's ledger holds the named meal,
    # and its windows were bound on the day before it. Re-deriving from that ledger would judge
    # the meal against a budget that already spent it, failing the gold accept.
    from dataclasses import replace

    from nutrienv.world.daily_windows import derive_daily_windows, plan_windows_for_meal
    from nutrienv.world.types import Profile

    state = demo_state()
    daily = derive_daily_windows(
        sex="female", age_y=34, height_cm=165.0, weight_kg=62.0, activity="light"
    )
    state.profile = Profile(user_id="u", windows=daily)
    # ~576 kcal and ~40 g protein: inside the lunch slot on an empty day.
    meal = [{"food_id": "chicken_breast", "grams": 100.0}, {"food_id": "white_rice", "grams": 316.0}]
    rows = [LedgerRow(i["food_id"], i["grams"], "today-lunch") for i in meal]
    before = plan_windows_for_meal(daily, {}, "lunch")
    pinned = {k: (round(lo, 2), round(hi, 2)) for k, (lo, hi) in before.items()}
    oracle = Oracle(
        profile=state.profile,
        last_plan=meal,
        last_verdict="accept",
        plan_windows=pinned,
        evaluated_plan=meal,
        ledger=tuple(rows),
    )
    state.ledger = list(rows)
    state.last_plan = [dict(i) for i in meal]
    state.last_verdict = "accept"
    assert Scorer._meal_windows(state, oracle, state.profile) == pinned
    assert Scorer().score(state, oracle)["passed"] is True
    # The same windows on a free recommendation do follow the ledger.
    free = replace(oracle, last_plan=[], last_verdict=None, evaluated_plan=None)
    assert Scorer._meal_windows(state, free, state.profile) != pinned
