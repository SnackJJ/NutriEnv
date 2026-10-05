"""Explicit complete ledger alternatives and their nutrient budgets."""

import copy
import json
from dataclasses import asdict, replace

import pytest

from nutrienv.bench import Oracle, Scorer, load_split
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.daily_windows import SIX_WINDOW_KEYS, plan_windows_for_meal
from nutrienv.world.types import LedgerRow, ledger_totals


@pytest.fixture
def case():
    state = demo_state()
    state.catalog["chicken_alt"] = copy.deepcopy(state.catalog["chicken_breast"])
    state.catalog["chicken_alt"]["name"] = "Chicken breast, another preparation"
    state.catalog["chicken_alt"]["aliases"] = []
    state.catalog["chicken_alt"]["nutrients"]["fat_g"] = 10.0
    earlier = LedgerRow("white_rice", 100.0, "today-breakfast")
    canonical = (earlier, LedgerRow("chicken_breast", 105.0, "today-lunch"))
    alternate = (earlier, LedgerRow("chicken_alt", 130.0, "today-lunch"))
    oracle = Oracle(ledger=canonical, ledger_tail=[canonical[-1]], ledger_variants=(alternate,))
    return state, oracle


def test_complete_alternative_and_its_tail_pass(case):
    state, oracle = case
    for ledger in (oracle.ledger, *oracle.ledger_variants):
        state.ledger = list(ledger)
        assert Scorer().score(state, oracle)["passed"]


@pytest.mark.parametrize("food,grams", [("salmon", 130.0), ("chicken_alt", 105.0)])
def test_unlisted_food_or_other_variants_portion_fails(case, food, grams):
    state, oracle = case
    state.ledger = [oracle.ledger[0], LedgerRow(food, grams, "today-lunch")]
    assert Scorer().score(state, oracle)["tag"] == "log_miss"


def test_untouched_rows_and_meal_stamp_must_match(case):
    state, oracle = case
    alternate = oracle.ledger_variants[0]
    for ledger in (
        [LedgerRow("white_rice", 200.0, "today-breakfast"), alternate[-1]],
        [alternate[0], replace(alternate[-1], eaten_at="today-dinner")],
    ):
        state.ledger = ledger
        assert Scorer().score(state, oracle)["tag"] == "log_miss"


def test_variants_cannot_be_mixed_row_by_row(case):
    state, oracle = case
    alternative = (LedgerRow("oats", 100.0, "today-breakfast"), oracle.ledger_variants[0][-1])
    oracle = replace(oracle, ledger_variants=(alternative,), ledger_tail=None)
    state.ledger = [oracle.ledger[0], alternative[-1]]
    assert Scorer().score(state, oracle)["tag"] == "log_miss"


def test_sub_oracles_still_require_every_child(case):
    state, oracle = case
    state.ledger = list(oracle.ledger_variants[0])
    both = Oracle(sub_oracles=(oracle, Oracle(ledger=oracle.ledger)))
    assert not Scorer().score(state, both)["passed"]


def test_recommendation_uses_matching_gold_not_underlogged_grams(case):
    state, ledger_oracle = case
    windows = {key: (0.0, 10000.0) for key in SIX_WINDOW_KEYS}
    windows["kcal"] = (2000.0, 2000.0)
    windows["fat_g"] = (0.0, 20.0)
    state.profile = replace(state.profile, windows=windows)
    pinned = plan_windows_for_meal(
        windows, ledger_totals(list(ledger_oracle.ledger), state.catalog), "dinner"
    )
    oracle = replace(
        ledger_oracle, profile=state.profile, last_plan=[], plan_windows=pinned,
        plan_must_fit_windows=True,
    )
    # Alternative gold eats 13 g fat, leaving 6.7 g after breakfast. Logging 85%
    # would incorrectly leave 8.65 g if the submitted grams set the budget.
    state.ledger = [oracle.ledger[0], replace(oracle.ledger_variants[0][-1], grams=110.5)]
    state.last_plan = [{"food_id": "white_rice", "grams": 530.0}]
    assert Scorer().score(state, oracle)["passed"]
    meal_windows = Scorer._meal_windows(state, oracle, state.profile)
    assert meal_windows["fat_g"][1] == pytest.approx(6.7)
    # 60 g chicken + 455 g rice is in the dinner energy slot, but 7.365 g fat
    # exceeds the matched gold remainder despite fitting the underlogged one.
    state.last_plan = [
        {"food_id": "chicken_alt", "grams": 60.0},
        {"food_id": "white_rice", "grams": 455.0},
    ]
    assert Scorer().score(state, oracle)["tag"] == "window"
    state.ledger = list(oracle.ledger)
    assert Scorer().score(state, oracle)["passed"]
    state.ledger[-1] = LedgerRow("salmon", 130.0, "today-lunch")
    assert Scorer._meal_windows(state, oracle, state.profile) == pinned
    assert Scorer().score(state, oracle)["tag"] == "log_miss"


def _load(tmp_path, case, variant_spec, *, with_base=True, base=None):
    state, oracle = case
    raw = {"ledger_variants": variant_spec}
    if with_base:
        raw["ledger"] = base if base is not None else [asdict(row) for row in oracle.ledger]
    path = tmp_path / "split.json"
    path.write_text(json.dumps({"items": [{
        "id": "variants", "family": "log", "query": "Correct my lunch.",
        "s0": {"profile": asdict(state.profile), "ledger": []}, "oracle": raw,
    }]}))
    return load_split(path, catalog=state.catalog)[0]


def test_loader_preserves_explicit_complete_variants(tmp_path, case):
    expected = case[1].ledger_variants
    task = _load(tmp_path, case, [[asdict(row) for row in expected[0]]])
    assert task.oracle.ledger_variants == expected
    task.s0.ledger = list(expected[0])
    assert Scorer().score(task.s0, task.oracle)["passed"]


def test_matched_variant_without_meal_energy_space_cannot_use_canonical_caps(case):
    state, ledger_oracle = case
    windows = {key: (0.0, 10000.0) for key in SIX_WINDOW_KEYS}
    windows["kcal"] = (2000.0, 2000.0)
    state.profile = replace(state.profile, windows=windows)
    pinned = plan_windows_for_meal(
        windows, ledger_totals(list(ledger_oracle.ledger), state.catalog), "dinner"
    )
    # This explicitly allowed ledger eats 1450 kcal at lunch plus 130 at
    # breakfast. Its 420 kcal remainder cannot meet dinner's 600 kcal floor.
    alternate = (
        ledger_oracle.ledger[0], LedgerRow("chicken_alt", 1450.0 / 1.65, "today-lunch")
    )
    oracle = replace(
        ledger_oracle, profile=state.profile, last_plan=[], plan_windows=pinned,
        plan_must_fit_windows=True, ledger_variants=(alternate,),
    )
    state.last_plan = [{"food_id": "white_rice", "grams": 530.0}]
    state.ledger = list(oracle.ledger)
    assert Scorer().score(state, oracle)["passed"]
    state.ledger = list(alternate)
    assert Scorer._meal_windows(state, oracle, state.profile) is None
    assert Scorer().score(state, oracle)["tag"] == "window"


@pytest.mark.parametrize("canonical_g,submitted_g,variant_g", [
    (100.0, 104.0, 120.0),   # 104 g is inside both bands
    (116.0, 100.0, 100.0),   # 116 g's band contains 100 g, but not vice versa
    (100.0, 112.0, 130.0),   # bands overlap at 112 g; neither centre is in the other
])
def test_ambiguous_variant_submission_fails_instead_of_underreporting(
    case, canonical_g, submitted_g, variant_g
):
    state, oracle = case
    breakfast = oracle.ledger[0]
    canonical = (breakfast, replace(oracle.ledger[-1], grams=canonical_g))
    variant = (breakfast, replace(oracle.ledger[-1], grams=variant_g))
    oracle = replace(oracle, ledger=canonical, ledger_variants=(variant,), ledger_tail=None)
    state.ledger = [breakfast, replace(canonical[-1], grams=submitted_g)]
    assert Scorer._matched_ledger(state, oracle) is None
    assert Scorer().score(state, oracle)["tag"] == "log_miss"


@pytest.mark.parametrize("canonical_g,variant_g", [
    (100.0, 105.0),   # tamer overlap
    (116.0, 100.0),   # asymmetric: only the larger band contains the smaller
    (100.0, 130.0),   # partial band overlap, neither centre inside the other
])
def test_loader_rejects_tolerance_overlapping_variants(
    tmp_path, case, canonical_g, variant_g
):
    state, oracle = case
    base = [asdict(row) for row in oracle.ledger]
    base[-1]["grams"] = canonical_g
    variant = [dict(row) for row in base]
    variant[-1]["grams"] = variant_g
    with pytest.raises(ValueError, match="not distinguishable"):
        _load(tmp_path, case, [variant], base=base)


def test_band_gap_inside_matcher_slack_is_rejected_at_load(tmp_path, case):
    # 0.85 * 135.29... - 115 = 1.5e-5: the bands miss each other by less than the matcher's
    # two-sided 1e-5 slack, so 115.000008 g matches both interpretations.
    canonical_g, variant_g, submitted_g = 100.0, (115.0 + 1.5e-5) / 0.85, 115.000008
    state, oracle = case
    breakfast = oracle.ledger[0]
    canonical = (breakfast, replace(oracle.ledger[-1], grams=canonical_g))
    variant = (breakfast, replace(oracle.ledger[-1], grams=variant_g))
    submitted = [breakfast, replace(canonical[-1], grams=submitted_g, eaten_at="now")]
    assert Scorer._match_ledger_multiset(submitted, canonical, None)
    assert Scorer._match_ledger_multiset(submitted, variant, None)
    assert Scorer._interpretations_overlap(canonical, variant)

    base = [asdict(row) for row in canonical]
    with pytest.raises(ValueError, match="not distinguishable"):
        _load(tmp_path, case, [[asdict(row) for row in variant]], base=base)


def test_slot_only_variants_are_ambiguous_because_now_bridges(case):
    state, oracle = case
    breakfast = oracle.ledger[0]
    canonical = (breakfast, replace(oracle.ledger[-1], eaten_at="today-lunch"))
    variant = (breakfast, replace(oracle.ledger[-1], eaten_at="today-dinner"))
    oracle = replace(oracle, ledger=canonical, ledger_variants=(variant,), ledger_tail=None)
    state.ledger = [breakfast, replace(canonical[-1], eaten_at="now")]
    assert Scorer._matched_ledger(state, oracle) is None
    assert Scorer().score(state, oracle)["tag"] == "log_miss"


def test_loader_rejects_slot_only_variants(tmp_path, case):
    state, oracle = case
    base = [asdict(row) for row in oracle.ledger]
    variant = [dict(row) for row in base]
    variant[-1]["eaten_at"] = "today-dinner"
    with pytest.raises(ValueError, match="not distinguishable"):
        _load(tmp_path, case, [variant], base=base)


@pytest.mark.parametrize("kind", [
    "missing_base", "empty_list", "empty_variant", "short_variant", "duplicate",
    "canonical_duplicate", "zero", "negative", "nan", "bool", "unknown_food",
    "missing_food", "missing_time", "non_list",
])
def test_loader_rejects_invalid_variant_data(tmp_path, case, kind):
    oracle = case[1]
    variant = [asdict(row) for row in oracle.ledger_variants[0]]
    spec = [variant]
    if kind == "empty_list":
        spec = []
    elif kind == "empty_variant":
        spec = [[]]
    elif kind == "short_variant":
        spec = [variant[-1:]]
    elif kind == "duplicate":
        spec = [variant, list(reversed(variant))]
    elif kind == "canonical_duplicate":
        spec = [[asdict(row) for row in oracle.ledger]]
    elif kind in {"zero", "negative", "nan", "bool"}:
        variant[-1]["grams"] = {"zero": 0, "negative": -1, "nan": float("nan"), "bool": True}[kind]
    elif kind == "unknown_food":
        variant[-1]["food_id"] = "unknown"
    elif kind == "missing_food":
        variant[-1].pop("food_id")
    elif kind == "missing_time":
        variant[-1].pop("eaten_at")
    elif kind == "non_list":
        spec = {"ledger": variant}
    with pytest.raises(ValueError):
        _load(tmp_path, case, spec, with_base=kind != "missing_base")


def test_static_and_replay_gates_reject_an_unreachable_alternative(case):
    from nutrienv.bench.achievable import check_achievable
    from nutrienv.bench.realize import Task
    from nutrienv.bench.validator import validate_ledger_variants

    state, ledger_oracle = case
    windows = {key: (0.0, 10000.0) for key in SIX_WINDOW_KEYS}
    windows["kcal"] = (2000.0, 2000.0)
    state.profile = replace(state.profile, windows=windows)
    pinned = plan_windows_for_meal(
        windows, ledger_totals(list(ledger_oracle.ledger), state.catalog), "dinner"
    )
    bad = (ledger_oracle.ledger[0], LedgerRow("white_rice", 2000.0, "today-lunch"))
    oracle = replace(ledger_oracle, last_plan=[], plan_windows=pinned,
                     plan_must_fit_windows=True, ledger_variants=(bad,))
    task = Task("unreachable-variant", "recommend", "What should I eat for dinner?", state, oracle)
    assert check_achievable([replace(task, oracle=replace(oracle, ledger_variants=()))]).unreachable == ()
    assert check_achievable([task]).unreachable == (task.id,)
    assert any("no feasible recommendation" in issue for issue in validate_ledger_variants(task))
