import pytest

from nutrienv.bench import Generator, SITUATIONS, Situation
from nutrienv.bench.realizations import FUZZY_ROWS, UPDATE_ROWS
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, ledger_totals


def test_sample_is_deterministic_and_uses_all_families():
    generator = Generator()
    assert generator.sample(42, "update") == generator.sample(42, "update")
    tasks = generator.generate_split(9, 12)
    assert {task.family for task in tasks} == {
        "lookup", "log", "recommend", "evaluate", "update", "constrain"
    }
    assert len({task.id for task in tasks}) == len(tasks)


def test_log_oracle_contains_only_new_rows():
    task = Generator().sample(5, "log", {"ledger_gaps": 3})
    assert any(row.eaten_at == "yesterday-snack" for row in task.s0.ledger)
    assert len(task.oracle.ledger_tail) == 3
    assert all(isinstance(row, LedgerRow) for row in task.oracle.ledger_tail)
    assert task.oracle.ledger_tail != task.s0.ledger


def test_update_oracle_normalizes_and_preserves_unmentioned_fields():
    task = Generator().sample(3, "update")
    row = next(item for item in UPDATE_ROWS if item.query == task.query)
    added = set(task.oracle.profile.allergies) - set(task.s0.profile.allergies)
    assert added == set(row.add_allergens)
    for key, delta in (row.window_shifts or {}).items():
        s0_lo, s0_hi = task.s0.profile.windows[key]
        ora_lo, ora_hi = task.oracle.profile.windows[key]
        assert (ora_lo, ora_hi) == (s0_lo + delta, s0_hi + delta)
    for key, bounds in task.s0.profile.windows.items():
        if key in (row.window_shifts or {}):
            continue
        assert task.oracle.profile.windows[key] == bounds
    assert task.oracle.profile.medications == task.s0.profile.medications
    assert task.oracle.profile.version == task.s0.profile.version
    assert task.oracle.profile.user_id == task.s0.profile.user_id
    assert "shrimp" not in task.oracle.profile.allergies


def test_difficulty_changes_s0_not_action_availability():
    easy = Generator().sample(1, "log", {"ledger_gaps": 1})
    hard = Generator().sample(
        1,
        "log",
        {"ledger_gaps": 4, "name_ambiguity": 3},
    )
    assert len(hard.s0.ledger) >= 4
    assert sum("rice" in food["aliases"] for food in hard.s0.catalog.values()) > 1
    assert easy.s0.catalog is not None


def test_same_seed_and_situation_is_deterministic():
    generator = Generator()
    for situation in SITUATIONS:
        assert generator.sample(21, situation=situation) == generator.sample(
            21, situation=situation
        )


def test_every_situation_has_a_fixture_backed_task():
    generator = Generator()
    tasks = [generator.sample(100 + index, situation=name) for index, name in enumerate(SITUATIONS)]
    assert {task.situations[0] for task in tasks} == set(SITUATIONS)
    assert all(len(task.s0.catalog) >= 15 for task in tasks)

    condition = generator.sample(7, situation=Situation.CONDITION_SUITABILITY)
    assert condition.family == "constrain"
    assert condition.s0.profile.allergies
    assert condition.oracle.last_plan == []
    assert condition.oracle.allow_empty_plan is False
    assert condition.oracle.plan_must_be_safe
    assert condition.oracle.plan_must_fit_windows
    assert condition.s0.profile.windows["kcal"][1] <= 800


def test_situation_realizations_have_concrete_oracles():
    generator = Generator()
    fuzzy = generator.sample(1, situation="fuzzy_portion")
    spec = next(row for row in FUZZY_ROWS if row.utterance == fuzzy.query)
    food = fuzzy.s0.catalog.canonical_id(spec.food_id)
    grams = resolve_portion(spec.food_id, spec.phrase, fuzzy.s0.catalog)
    assert fuzzy.oracle.ledger_tail == [LedgerRow(food, grams, spec.slot)]

    converted = generator.sample(1, situation="unit_convert")
    oats = converted.s0.catalog.canonical_id("oats")
    assert converted.oracle.ledger_tail == [LedgerRow(oats, 56.7, "today-snack")]

    split = generator.generate_split(2, 3, situation="near_synonym")
    assert all(task.situations == ("near_synonym",) for task in split)
    assert all(task.family == "log" for task in split)


def test_log_drafts_pin_profile_and_full_ledger():
    for kwargs in (
        {"family": "log"},
        {"situation": "fuzzy_portion"},
        {"situation": "multi_item_log"},
        {"situation": "unit_convert"},
        {"situation": "ledger_gap"},
    ):
        task = Generator().sample(5, **kwargs)
        assert task.oracle.profile == task.s0.profile, kwargs
        assert task.oracle.ledger_tail
        assert task.oracle.ledger == (*task.s0.ledger, *task.oracle.ledger_tail), kwargs
        assert task.s0.ledger, kwargs
        slots = {row.eaten_at for row in task.s0.ledger}
        needed = {row.eaten_at for row in task.oracle.ledger_tail}
        if "ledger_gap" in task.situations:
            assert any(slot.startswith("today-") for slot in slots)
            assert needed.isdisjoint(slots)
        else:
            assert needed <= slots, (kwargs, needed, slots)
            assert any(slot.endswith("-snack") or slot.startswith("yesterday-") for slot in slots)


def test_fuzzy_and_unit_grams_come_from_resolve_portion():
    fuzzy = Generator().sample(1, situation="fuzzy_portion")
    spec = next(row for row in FUZZY_ROWS if row.utterance == fuzzy.query)
    assert fuzzy.oracle.ledger_tail[0].food_id == fuzzy.s0.catalog.canonical_id(
        spec.food_id
    )
    assert fuzzy.oracle.ledger_tail[0].grams == resolve_portion(
        spec.food_id, spec.phrase, fuzzy.s0.catalog
    )

    converted = Generator().sample(1, situation="unit_convert")
    assert converted.oracle.ledger_tail[0].grams == resolve_portion(
        "oats", "2 ounces", converted.s0.catalog
    )


def test_non_log_drafts_pin_unchanged_ledger():
    for family in ("update", "recommend", "evaluate"):
        task = Generator().sample(3, family)
        assert task.oracle.ledger == tuple(task.s0.ledger), family
        assert task.oracle.profile is not None
    update = Generator().sample(3, "update")
    assert update.oracle.profile != update.s0.profile
    assert "shrimp" not in update.oracle.profile.allergies
    recommend = Generator().sample(3, "recommend")
    assert recommend.oracle.last_plan == []
    assert recommend.oracle.plan_must_be_safe
    assert recommend.oracle.plan_must_fit_windows
    assert recommend.persona == "everyday"


def test_conflict_windows_starts_with_a_violating_plan():
    task = Generator().sample(8, situation="conflict_windows")
    assert task.s0.last_plan
    assert task.oracle.ledger == tuple(task.s0.ledger)
    assert task.oracle.allow_empty_plan
    assert task.oracle.plan_must_fit_windows
    assert task.oracle.profile == task.s0.profile


def test_near_synonym_logs_the_catalog_food():
    task = Generator().sample(1, situation="near_synonym")
    assert task.family == "log"
    assert "prawn" in task.query.lower()
    shrimp = task.s0.catalog.canonical_id("shrimp")
    assert task.oracle.ledger_tail == [LedgerRow(shrimp, 150.0, "today-dinner")]
    assert task.oracle.profile == task.s0.profile
    assert task.oracle.ledger == (*task.s0.ledger, *task.oracle.ledger_tail)
    assert "today-dinner" in {row.eaten_at for row in task.s0.ledger}


def test_generated_update_rejects_a_junk_log():
    from nutrienv.bench.scorer import Scorer
    from nutrienv.env import NutriEnv

    task = Generator().sample(3, "update")
    env = NutriEnv()
    env.reset(task.s0)
    env.step(
        {
            "op": "update_profile",
            "patch": {
                "allergies": list(task.oracle.profile.allergies),
                "windows": {
                    key: list(bounds)
                    for key, bounds in task.oracle.profile.windows.items()
                },
            },
        }
    )
    env.step(
        {
            "op": "log_meal",
            "food_id": "oats",
            "grams": 50.0,
            "eaten_at": "today-junk",
        }
    )
    score = Scorer().score(env.state(), task.oracle)
    assert score["passed"] is False
    assert score["tag"] == "log_miss"


def test_leftover_persona_only_pairs_with_recommend():
    with pytest.raises(ValueError, match="leftover"):
        Generator().sample(1, family="log", persona="leftover")
    cut = Generator().sample(1, family="recommend", persona="cut")
    assert cut.persona == "cut"
    assert cut.family == "recommend"
    implied = Generator().sample(4, persona="leftover")
    assert implied.family == "recommend"
    assert implied.persona == "leftover"


def test_leftover_recommend_uses_remainder_plan_windows():
    task = Generator().sample(11, family="recommend", persona="leftover")
    assert task.persona == "leftover"
    assert task.family == "recommend"
    assert task.s0.ledger
    assert task.oracle.ledger == tuple(task.s0.ledger)
    assert task.oracle.last_plan == []
    assert task.oracle.plan_must_be_safe
    assert task.oracle.plan_must_fit_windows
    assert task.oracle.profile == task.s0.profile
    assert task.oracle.plan_windows
    eaten = ledger_totals(task.s0.ledger, task.s0.catalog)
    for key, (lo, hi) in task.s0.profile.windows.items():
        used = eaten.get(key, 0.0)
        expected = (round(max(0.0, lo - used), 2), round(max(0.0, hi - used), 2))
        assert task.oracle.plan_windows[key] == expected, (key, expected)
