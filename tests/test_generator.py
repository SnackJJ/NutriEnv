from nutrienv.bench import Generator, SITUATIONS, Situation
from nutrienv.world.types import LedgerRow


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
    assert len(task.s0.ledger) == 3
    assert len(task.oracle.ledger_tail) == 3
    assert all(isinstance(row, LedgerRow) for row in task.oracle.ledger_tail)
    assert task.oracle.ledger_tail != task.s0.ledger


def test_update_oracle_normalizes_and_preserves_unmentioned_fields():
    task = Generator().sample(3, "update")
    assert task.oracle.profile.allergies == ("peanut", "shrimp")
    assert task.oracle.profile.medications == task.s0.profile.medications
    assert task.oracle.profile.version == task.s0.profile.version


def test_difficulty_changes_s0_not_action_availability():
    easy = Generator().sample(1, "recommend", {"n_constraints": 1})
    hard = Generator().sample(
        1,
        "recommend",
        {"n_constraints": 6, "ledger_gaps": 4, "name_ambiguity": 3},
    )
    assert len(easy.s0.profile.windows) == 1
    assert len(hard.s0.profile.windows) == 6
    assert len(hard.s0.ledger) == 4
    assert sum("rice" in food["aliases"] for food in hard.s0.catalog.values()) > 1


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
    assert all(len(task.s0.catalog) == 15 for task in tasks)

    condition = generator.sample(7, situation=Situation.CONDITION_SUITABILITY)
    assert condition.family == "constrain"
    assert "shellfish" in condition.s0.profile.allergies
    assert "shrimp" in condition.query.lower()
    assert condition.oracle.allow_empty_plan


def test_situation_realizations_have_concrete_oracles():
    generator = Generator()
    fuzzy = generator.sample(1, situation="fuzzy_portion")
    assert "half a cup" in fuzzy.query
    assert fuzzy.oracle.ledger_tail == [LedgerRow("milk_whole", 122.0, "today-breakfast")]

    converted = generator.sample(1, situation="unit_convert")
    assert converted.oracle.ledger_tail == [LedgerRow("oats", 56.7, "today-snack")]

    split = generator.generate_split(2, 3, situation="near_synonym")
    assert all(task.situations == ("near_synonym",) for task in split)
