"""Frozen gold split is the exam; queries must not leak the answer."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from nutrienv.bench.realize import Task
from nutrienv.bench.split import GOLD_SPLIT_PATH, load_split
from nutrienv.world.daily_windows import derive_daily_windows
from nutrienv.world.types import LedgerRow

_WINDOW_LEAK = re.compile(r"\b(?:kcal|protein_g|carb_g|fat_g)\s+\d")
_SLUG = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")


def test_legacy_split_items_load_without_rewriting_windows() -> None:
    path = Path("data/splits/archive/v0.5-gold.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    tasks = {task.id: task for task in load_split(path)}
    for item in raw["items"]:
        stored = item["s0"]["profile"]
        loaded = tasks[item["id"]].s0.profile
        for key, bounds in stored["windows"].items():
            assert loaded.windows[key] == (float(bounds[0]), float(bounds[1])), item["id"]
        assert "sex" not in stored
        assert "age_y" not in stored
        assert "height_cm" not in stored
        assert "weight_kg" not in stored
        assert "activity" not in stored
        assert "phase" not in stored
        assert loaded.sex is None
        assert loaded.age_y is None
        assert loaded.height_cm is None
        assert loaded.weight_kg is None
        assert loaded.activity is None
        assert loaded.phase == "maintain"
    gym = tasks["v0-rec-gym-001"]
    assert gym.persona == "gym"
    assert gym.s0.profile.plan_preset == {"goal": "muscle"}
    assert gym.s0.profile.activity is None
    assert gym.s0.profile.windows["kcal"] == (400.0, 750.0)


def test_roster_complete_s0_round_trips_body_facts_through_load(
    tmp_path: Path,
) -> None:
    from nutrienv.env import NutriEnv
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = {
        "version": "test-roster",
        "items": [
            {
                "id": "roster-s0-001",
                "family": "log",
                "persona": "gym",
                "query": "Please log breakfast.",
                "s0": {
                    "profile": {
                        "user_id": "roster-ada",
                        "allergies": ["peanut"],
                        "windows": {"kcal": [1800, 2200], "protein_g": [90, 140]},
                        "sex": "female",
                        "age_y": 34,
                        "height_cm": 165.0,
                        "weight_kg": 62.0,
                        "activity": "light",
                        "phase": "cut",
                    },
                    "ledger": [],
                },
                "oracle": {"profile": "s0", "ledger": "s0"},
            }
        ],
    }
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    task = load_split(path, catalog=demo_catalog())[0]
    assert task.persona == "gym"
    assert task.s0.profile.sex == "female"
    assert task.s0.profile.age_y == 34
    assert task.s0.profile.height_cm == 165.0
    assert task.s0.profile.weight_kg == 62.0
    assert task.s0.profile.activity == "light"
    assert task.s0.profile.phase == "cut"
    assert task.s0.profile.windows == {"kcal": (1800.0, 2200.0), "protein_g": (90.0, 140.0)}
    assert task.oracle.profile == task.s0.profile

    env = NutriEnv()
    opening = env.reset(task.s0)["profile"]
    observed = env.step({"op": "get_profile"})["observation"]["profile"]
    for profile in (opening, observed):
        assert profile["sex"] == "female"
        assert profile["age_y"] == 34
        assert profile["height_cm"] == 165.0
        assert profile["weight_kg"] == 62.0
        assert profile["activity"] == "light"
        assert profile["phase"] == "cut"
        assert profile["windows"] == {"kcal": [1800.0, 2200.0], "protein_g": [90.0, 140.0]}


def test_oracle_profile_object_keeps_unmentioned_body_facts(tmp_path: Path) -> None:
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = {
        "version": "test-roster",
        "items": [
            {
                "id": "roster-upd-001",
                "family": "update",
                "persona": "everyday",
                "query": "Add a shellfish allergy.",
                "s0": {
                    "profile": {
                        "user_id": "roster-ada",
                        "allergies": ["peanut"],
                        "windows": {"kcal": [1800, 2200], "protein_g": [90, 140]},
                        "sex": "female",
                        "age_y": 34,
                        "height_cm": 165.0,
                        "weight_kg": 62.0,
                        "activity": "light",
                        "phase": "cut",
                    },
                    "ledger": [],
                },
                "oracle": {
                    "profile": {"allergies": ["peanut", "shellfish"]},
                    "ledger": "s0",
                },
            }
        ],
    }
    path = tmp_path / "roster-update.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    task = load_split(path, catalog=demo_catalog())[0]
    assert task.oracle.profile is not None
    assert task.oracle.profile.allergies == ("peanut", "shellfish")
    assert task.oracle.profile.sex == "female"
    assert task.oracle.profile.age_y == 34
    assert task.oracle.profile.height_cm == 165.0
    assert task.oracle.profile.weight_kg == 62.0
    assert task.oracle.profile.activity == "light"
    assert task.oracle.profile.phase == "cut"
    assert task.oracle.profile.windows == task.s0.profile.windows


def test_load_split_reads_allowed_food_ids_from_s0_into_oracle(tmp_path: Path) -> None:
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = {
        "version": "test-inventory",
        "items": [
            {
                "id": "inv-s0-001",
                "family": "recommend",
                "persona": "everyday",
                "query": "Make dinner from the fridge.",
                "s0": {
                    "profile": {
                        "user_id": "inv-ada",
                        "allergies": ["peanut"],
                        "windows": {"kcal": [120, 140]},
                    },
                    "ledger": [],
                    "allowed_food_ids": ["white_rice", "broccoli"],
                },
                "oracle": {
                    "profile": "s0",
                    "last_plan": [],
                    "plan_must_fit_windows": True,
                    "ledger": "s0",
                },
            }
        ],
    }
    path = tmp_path / "inventory-s0.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    task = load_split(path, catalog=demo_catalog())[0]
    assert task.s0.allowed_food_ids == frozenset({"white_rice", "broccoli"})
    assert task.oracle.allowed_food_ids == frozenset({"white_rice", "broccoli"})


def test_load_split_reads_oracle_allowed_food_ids_and_composite_children(
    tmp_path: Path,
) -> None:
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = {
        "version": "test-inventory",
        "items": [
            {
                "id": "inv-comp-001",
                "family": "log",
                "persona": "everyday",
                "query": "Log lunch then plan dinner from these groceries.",
                "s0": {
                    "profile": {
                        "user_id": "inv-ada",
                        "allergies": ["peanut"],
                        "windows": {"kcal": [120, 140]},
                    },
                    "ledger": [],
                },
                "oracle": {
                    "allowed_food_ids": ["white_rice", "broccoli", "chicken_breast"],
                    "sub_oracles": [
                        {"profile": "s0", "ledger": "s0"},
                        {
                            "profile": "s0",
                            "last_plan": [],
                            "plan_must_fit_windows": True,
                            "ledger": "s0",
                        },
                    ],
                },
            }
        ],
    }
    path = tmp_path / "inventory-comp.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    task = load_split(path, catalog=demo_catalog())[0]
    assert task.s0.allowed_food_ids is None
    assert task.oracle.allowed_food_ids == frozenset(
        {"white_rice", "broccoli", "chicken_breast"}
    )
    assert task.oracle.sub_oracles is not None
    assert all(
        child.allowed_food_ids == task.oracle.allowed_food_ids
        for child in task.oracle.sub_oracles
    )


def test_load_split_rejects_invalid_allowed_food_ids(tmp_path: Path) -> None:
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = {
        "version": "test-inventory",
        "items": [
            {
                "id": "inv-bad-001",
                "family": "recommend",
                "persona": "everyday",
                "query": "Make dinner.",
                "s0": {
                    "profile": {"user_id": "inv-ada", "windows": {"kcal": [120, 140]}},
                    "ledger": [],
                    "allowed_food_ids": "white_rice",
                },
                "oracle": {"profile": "s0", "last_plan": [], "ledger": "s0"},
            }
        ],
    }
    path = tmp_path / "inventory-bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="allowed_food_ids"):
        load_split(path, catalog=demo_catalog())


@pytest.mark.parametrize("phase", ["", None, "bulk"])
def test_load_split_rejects_invalid_phase(tmp_path: Path, phase: str | None) -> None:
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = {
        "version": "test-roster",
        "items": [
            {
                "id": "roster-phase-001",
                "family": "log",
                "persona": "everyday",
                "query": "Please log breakfast.",
                "s0": {
                    "profile": {
                        "user_id": "roster-ada",
                        "allergies": ["peanut"],
                        "windows": {"kcal": [1800, 2200], "protein_g": [90, 140]},
                        "phase": phase,
                    },
                    "ledger": [],
                },
                "oracle": {"profile": "s0", "ledger": "s0"},
            }
        ],
    }
    path = tmp_path / "bad-phase.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="phase"):
        load_split(path, catalog=demo_catalog())


def test_oracle_profile_can_carry_patched_weight(tmp_path: Path) -> None:
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = {
        "version": "test-roster",
        "items": [
            {
                "id": "roster-upd-body-001",
                "family": "update",
                "persona": "everyday",
                "query": "I now weigh 80 kilograms.",
                "s0": {
                    "profile": {
                        "user_id": "roster-ada",
                        "allergies": ["peanut"],
                        "windows": {"kcal": [1800, 2200], "protein_g": [90, 140]},
                        "sex": "female",
                        "age_y": 34,
                        "height_cm": 165.0,
                        "weight_kg": 62.0,
                        "activity": "light",
                        "phase": "cut",
                    },
                    "ledger": [],
                },
                "oracle": {
                    "profile": {
                        "allergies": ["peanut"],
                        "weight_kg": 80.0,
                    },
                    "ledger": "s0",
                },
            }
        ],
    }
    path = tmp_path / "roster-body-override.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    task = load_split(path, catalog=demo_catalog())[0]
    assert task.oracle.profile is not None
    assert task.oracle.profile.weight_kg == 80.0
    assert task.oracle.profile.sex == "female"
    assert task.oracle.profile.phase == "cut"
    assert task.oracle.profile.windows == derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=80.0,
        activity="light",
        phase="cut",
    )
    assert task.oracle.profile.windows != task.s0.profile.windows


def test_fact_only_weight_patch_matches_loaded_oracle(tmp_path: Path) -> None:
    from nutrienv.bench.scorer import Scorer
    from nutrienv.env import NutriEnv
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = {
        "version": "test-roster",
        "items": [
            {
                "id": "roster-upd-body-001",
                "family": "update",
                "persona": "everyday",
                "query": "I now weigh 80 kilograms.",
                "s0": {
                    "profile": {
                        "user_id": "roster-ada",
                        "allergies": ["peanut"],
                        "windows": {"kcal": [1800, 2200], "protein_g": [90, 140]},
                        "sex": "female",
                        "age_y": 34,
                        "height_cm": 165.0,
                        "weight_kg": 62.0,
                        "activity": "light",
                        "phase": "cut",
                    },
                    "ledger": [],
                },
                "oracle": {
                    "profile": {"weight_kg": 80.0},
                    "ledger": "s0",
                },
            }
        ],
    }
    path = tmp_path / "roster-weight.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    task = load_split(path, catalog=demo_catalog())[0]
    env = NutriEnv()
    env.reset(task.s0)
    out = env.step({"op": "update_profile", "patch": {"weight_kg": 80.0}})
    assert out["ok"] is True
    assert Scorer().score(env.state(), task.oracle) == {"passed": True, "tag": "pass"}


def test_load_split_reads_implicit_update_band(tmp_path: Path) -> None:
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = {
        "version": "test-roster",
        "items": [
            {
                "id": "roster-upd-cut-001",
                "family": "update",
                "persona": "everyday",
                "query": "I'm cutting now.",
                "s0": {
                    "profile": {
                        "user_id": "roster-ada",
                        "allergies": ["peanut"],
                        "windows": {"kcal": [1800, 2200], "protein_g": [90, 140]},
                        "sex": "female",
                        "age_y": 34,
                        "height_cm": 165.0,
                        "weight_kg": 62.0,
                        "activity": "light",
                    },
                    "ledger": [],
                },
                "oracle": {
                    "profile": {"allergies": ["peanut"]},
                    "ledger": "s0",
                    "update_band": "cut",
                },
            }
        ],
    }
    path = tmp_path / "implicit-cut.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    task = load_split(path, catalog=demo_catalog())[0]
    assert task.oracle.update_band == "cut"
    assert task.oracle.profile is not None
    assert task.oracle.profile.allergies == ("peanut",)
    assert task.oracle.profile.weight_kg == 62.0


def test_freezer_round_trips_roster_body_facts(tmp_path: Path) -> None:
    from nutrienv.bench.pipeline.freezer import task_to_item
    from nutrienv.bench.realize import Oracle, Task
    from nutrienv.world.catalog_fixture import demo_catalog
    from nutrienv.world.types import Profile, WorldState

    catalog = demo_catalog()
    profile = Profile(
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
    task = Task(
        "roster-s0-001",
        "log",
        "Please log breakfast.",
        WorldState(profile=profile, catalog=catalog),
        Oracle(profile=profile, ledger=()),
        (),
        "gym",
    )
    item = task_to_item(task)
    stored = item["s0"]["profile"]
    assert stored["sex"] == "female"
    assert stored["age_y"] == 34
    assert stored["height_cm"] == 165.0
    assert stored["weight_kg"] == 62.0
    assert stored["activity"] == "light"
    assert stored["phase"] == "cut"
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps({"version": "test", "items": [item]}), encoding="utf-8")
    loaded = load_split(path, catalog=catalog)[0]
    assert loaded.s0.profile == profile
    assert loaded.oracle.profile == profile


def test_freezer_round_trips_phase_cut_oracle_so_fact_only_update_passes(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from nutrienv.bench.pipeline.freezer import task_to_item
    from nutrienv.bench.realize import Oracle, Task
    from nutrienv.bench.scorer import Scorer
    from nutrienv.env import NutriEnv
    from nutrienv.world.catalog_fixture import demo_catalog
    from nutrienv.world.daily_windows import derive_daily_windows
    from nutrienv.world.types import Profile, WorldState

    catalog = demo_catalog()
    maintain = derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="maintain",
    )
    cut = derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="cut",
    )
    s0_profile = Profile(
        user_id="roster-ada",
        allergies=("peanut",),
        windows=maintain,
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="maintain",
    )
    oracle_profile = replace(s0_profile, phase="cut", windows=cut)
    task = Task(
        "roster-upd-cut-001",
        "update",
        "I'm cutting now.",
        WorldState(profile=s0_profile, catalog=catalog),
        Oracle(profile=oracle_profile, ledger=()),
        (),
        "everyday",
    )
    item = task_to_item(task)
    assert item["oracle"]["profile"] != "s0"
    assert item["oracle"]["profile"]["phase"] == "cut"
    path = tmp_path / "frozen-cut.json"
    path.write_text(json.dumps({"version": "test", "items": [item]}), encoding="utf-8")
    loaded = load_split(path, catalog=catalog)[0]
    assert loaded.oracle.profile is not None
    assert loaded.oracle.profile.phase == "cut"
    assert loaded.oracle.profile.windows == cut

    env = NutriEnv()
    env.reset(loaded.s0)
    out = env.step({"op": "update_profile", "patch": {"phase": "cut"}})
    assert out["ok"] is True
    assert Scorer().score(env.state(), loaded.oracle) == {"passed": True, "tag": "pass"}


def test_load_split_v05_is_the_240() -> None:
    tasks = load_split(Path("data/splits/archive/v0.5-gold.json"))
    assert len(tasks) == 240
    assert len({task.id for task in tasks}) == 240


def test_load_split_default_loads_v2_2_gold() -> None:
    from nutrienv.bench.split import EXAM_SPLIT_PATH, load_exam

    assert EXAM_SPLIT_PATH.name == "v2.2-gold.json"
    tasks = load_split()
    assert len(tasks) == 100
    exam_tasks = load_exam()
    assert len(exam_tasks) == 100


def test_v2_3_gold_curation_size_and_adversarial_coverage() -> None:
    v23 = load_split(Path("data/splits/v2.3-gold.json"))
    assert len(v23) == 120
    v23_ids = {task.id for task in v23}
    purged = {
        "adr20-log-5003",
        "adr20-log-5008",
        "adr20-comp-5041",
        "adr20-comp-5052",
        "adr24-comp-8237",
        "adr24-comp-8238",
        "adr24-comp-9111",
        "adr24-comp-8263",
    }
    assert not (v23_ids & purged)
    adversarial = {
        "adr25-eval-1201",
        "adr25-eval-1202",
        "adr25-eval-1203",
        "adr25-eval-1204",
        "adr25-comp-1205",
        "adr25-comp-1206",
        "adr25-comp-1207",
        "adr25-comp-1208",
        "adr25-rec-1209",
        "adr25-rec-1210",
    }
    assert adversarial <= v23_ids


def test_v2_3_eval_accepts_keep_kcal_margin_off_the_window_edge() -> None:
    from nutrienv.world.types import LedgerRow, ledger_totals

    tight = {
        "adr25-eval-1005",
        "adr25-eval-1008",
        "adr25-eval-1009",
    }
    tasks = {
        task.id: task
        for task in load_split(Path("data/splits/v2.3-gold.json"))
        if task.id in tight
    }
    assert set(tasks) == tight
    for task in tasks.values():
        rows = [
            LedgerRow(item["food_id"], item["grams"], "eval")
            for item in task.oracle.evaluated_plan
        ]
        kcal = ledger_totals(rows, task.s0.catalog)["kcal"]
        lo, hi = task.oracle.plan_windows["kcal"]
        assert kcal - lo >= 50.0
        assert hi - kcal >= 50.0


def test_v2_3_new_eval_accepts_span_multiple_roster_people() -> None:
    tasks = [
        task
        for task in load_split(Path("data/splits/v2.3-gold.json"))
        if task.id.startswith("adr25-eval-")
    ]
    users = {task.s0.profile.user_id for task in tasks}
    assert len(tasks) == 14
    assert len(users) >= 7


def test_v2_3_mini_covers_multi_item_eval_accept_and_unfit_recommend() -> None:
    tasks = load_split(Path("data/splits/v2.3-mini.json"))
    ids = {task.id for task in tasks}
    assert "adr25-eval-1001" in ids
    assert "adr25-eval-1008" in ids
    assert "adr25-comp-1101" in ids
    assert "adr25-comp-1108" in ids
    multi = next(task for task in tasks if task.id == "adr25-eval-1008")
    assert len(multi.oracle.evaluated_plan) >= 3


def test_v2_3_hygiene_composites_keep_child_ledgers_aligned() -> None:
    tasks = {
        task.id: task
        for task in load_split(Path("data/splits/v2.3-gold.json"))
    }
    for task_id, food_id, grams in (
        ("adr24-comp-8310", "2709715", 130.0),
    ):
        children = tasks[task_id].oracle.sub_oracles
        log = children[0]
        assert any(row.food_id == food_id and row.grams == grams for row in log.ledger_tail)


def test_v2_6_gold_disambiguates_queries_and_matches_public_release() -> None:
    gold = load_split(Path("data/splits/v2.6-gold.json"))
    assert len(gold) == 128
    assert Counter(task.family for task in gold) == {
        "update": 5,
        "log": 14,
        "evaluate": 39,
        "recommend": 23,
        "composite": 47,
    }
    by_id = {task.id: task for task in gold}
    assert "adr20-log-8205" not in by_id
    assert "adr20-log-5004" not in by_id
    log_1309 = by_id["adr26-log-1309"]
    assert log_1309.query == (
        "I had two hard-boiled eggs and an apple for breakfast."
    )
    assert {(row.food_id, row.grams, row.eaten_at) for row in log_1309.oracle.ledger_tail} == {
        ("2707154", 100.0, "today-breakfast"),
        ("2709215", 165.0, "today-breakfast"),
    }
    log_1310 = by_id["adr26-log-1310"]
    assert log_1310.query == (
        "I had a glass of whole milk and a banana for breakfast."
    )
    assert {(row.food_id, row.grams, row.eaten_at) for row in log_1310.oracle.ledger_tail} == {
        ("2705385", 244.0, "today-breakfast"),
        ("2709224", 126.0, "today-breakfast"),
    }
    assert by_id["adr24-comp-8301"].query.startswith("I had a serving of tripe")
    assert by_id["adr24-comp-8303"].query.startswith("I had a serving of cooked fresh carrots")
    assert by_id["adr20-log-5005"].query.startswith("I had a standard plate of fish")
    assert "prepared with added fat" in by_id["adr24-comp-9402"].query
    assert any(
        row.food_id == "2707421" and row.grams == 185.0
        for row in by_id["adr24-comp-9402"].oracle.sub_oracles[0].ledger_tail
    )
    assert "made with no added fat" in by_id["adr24-comp-9403"].query
    assert any(
        row.food_id == "2709123" and row.grams == 288.0
        for row in by_id["adr24-comp-9403"].oracle.sub_oracles[0].ledger_tail
    )
    assert "made with no added fat" in by_id["adr24-comp-9503"].query
    assert any(
        row.food_id == "2709123" and row.grams == 288.0
        for row in by_id["adr24-comp-9503"].oracle.sub_oracles[1].ledger_tail
    )
    for task_id in (
        "adr25-eval-1003",
        "adr25-eval-1005",
        "adr25-eval-1006",
        "adr25-eval-1007",
    ):
        task = by_id[task_id]
        assert "planned" in task.query
        assert task.oracle.last_verdict == "accept"
        assert task.oracle.ledger == ()


def test_v2_5_nutrienv_v1_splits_exist_and_cover_all_requirements() -> None:
    v25_tasks = load_split(Path("data/splits/v2.5-gold.json"))
    assert len(v25_tasks) == 128

    gold_ids = {t.id for t in v25_tasks}
    # Check 6 dietary myth tasks
    for i in range(1301, 1307):
        assert f"adr26-eval-{i}" in gold_ids
    # Check ledger amend task
    assert "adr26-log-1307" in gold_ids
    # Check multi-meal recommendation task
    assert "adr26-rec-1308" in gold_ids

    # Check mini splits
    mini_tasks = load_split(Path("data/splits/nutrienv-mini.json"))
    v25_mini_tasks = load_split(Path("data/splits/v2.5-mini.json"))
    assert len(mini_tasks) == 24
    assert len(v25_mini_tasks) == 24


def test_v2_8_lite_gold_is_63_and_mirrors_public_release() -> None:
    gold = load_split(Path("data/splits/v2.8-gold.json"))
    public = load_split(Path("data/splits/nutrienv-gold.json"))
    assert len(gold) == 63
    assert len(public) == 63
    assert Counter(task.family for task in gold) == {
        "update": 2,
        "log": 6,
        "evaluate": 8,
        "recommend": 11,
        "composite": 36,
    }
    by_id = {task.id: task for task in gold}
    assert "adr20-upd-5026" in by_id
    assert "adr25-eval-1201" not in by_id
    assert "adr29-fridge-01" not in by_id
    assert "adr29-fridge-03" in by_id
    assert "adr29-starve-04" in by_id
    assert {task.id for task in gold} == {task.id for task in public}


def test_gold_split_exists_and_loads() -> None:
    tasks = load_split(GOLD_SPLIT_PATH)
    assert 38 <= len(tasks) <= 42
    assert len({task.id for task in tasks}) == len(tasks)
    families = {task.family for task in tasks}
    assert {"log", "update", "recommend", "evaluate", "constrain"}.issubset(families)
    assert "lookup" not in families
    assert all(task.s0.catalog for task in tasks)
    assert all(task.persona for task in tasks)


def test_gold_queries_do_not_leak_ids_or_windows() -> None:
    for task in load_split(GOLD_SPLIT_PATH):
        assert "catalog id" not in task.query.lower()
        assert "food_id" not in task.query.lower()
        if task.family != "evaluate":
            leaked = [token for token in _SLUG.findall(task.query.lower()) if token in task.s0.catalog]
            assert leaked == [], f"{task.id} leaks catalog slugs {leaked}"
        if task.family == "recommend":
            assert _WINDOW_LEAK.search(task.query) is None, f"{task.id} leaks windows"


def test_gold_oracles_are_query_scoped() -> None:
    for task in load_split(GOLD_SPLIT_PATH):
        if task.family == "log":
            assert task.oracle.ledger_tail
            assert all(isinstance(row, LedgerRow) for row in task.oracle.ledger_tail)
            assert task.oracle.profile == task.s0.profile
            assert task.s0.ledger, f"{task.id} must seed eaten_at vocabulary"
            assert task.oracle.ledger == (*task.s0.ledger, *task.oracle.ledger_tail)
            s0_slots = {row.eaten_at for row in task.s0.ledger}
            if "ledger_gap" in task.situations:
                assert any(slot.startswith("today-") for slot in s0_slots), task.id
                missing = {row.eaten_at for row in task.oracle.ledger_tail}
                assert missing.isdisjoint(s0_slots), task.id
            else:
                needed = {row.eaten_at for row in task.oracle.ledger_tail}
                assert needed <= s0_slots, (task.id, needed, s0_slots)
        if task.family == "update":
            assert task.oracle.profile is not None
            assert task.oracle.profile.user_id == task.s0.profile.user_id
            assert task.oracle.profile.version == task.s0.profile.version
            assert task.oracle.profile != task.s0.profile
            assert task.oracle.ledger == tuple(task.s0.ledger)
            assert "shrimp" not in task.oracle.profile.allergies
        if task.family == "recommend":
            assert task.oracle.last_plan == []
            assert task.oracle.plan_must_be_safe
            assert task.oracle.plan_must_fit_windows
            assert "kcal" in task.s0.profile.windows
            assert task.oracle.ledger == tuple(task.s0.ledger)
        if task.family == "constrain" and "condition_suitability" in task.situations:
            assert task.oracle.plan_windows is None, task.id
            assert task.s0.profile.windows["kcal"][1] <= 800, task.id
            assert task.oracle.profile == task.s0.profile


def test_gold_oracles_are_achievable() -> None:
    from nutrienv.bench import check_achievable

    report = check_achievable(load_split(GOLD_SPLIT_PATH))
    assert report.unreachable == ()


_CANDIDATE_PLANS = (
    [
        {"food_id": "chicken_breast", "grams": 150.0},
        {"food_id": "olive_oil", "grams": 20.0},
    ],
    [{"food_id": "greek_yogurt", "grams": 200.0}],
    [{"food_id": "chicken_breast", "grams": 80.0}],
    [{"food_id": "chicken_breast", "grams": 100.0}],
    [
        {"food_id": "chicken_breast", "grams": 120.0},
        {"food_id": "broccoli", "grams": 100.0},
    ],
    [
        {"food_id": "chicken_breast", "grams": 180.0},
        {"food_id": "broccoli", "grams": 80.0},
    ],
    [
        {"food_id": "chicken_breast", "grams": 120.0},
        {"food_id": "white_rice", "grams": 150.0},
        {"food_id": "broccoli", "grams": 80.0},
    ],
    [
        {"food_id": "chicken_breast", "grams": 120.0},
        {"food_id": "white_rice", "grams": 200.0},
        {"food_id": "broccoli", "grams": 100.0},
    ],
    [
        {"food_id": "oats", "grams": 60.0},
        {"food_id": "milk_whole", "grams": 244.0},
        {"food_id": "banana", "grams": 118.0},
    ],
    [
        {"food_id": "chicken_breast", "grams": 170.0},
        {"food_id": "white_rice", "grams": 100.0},
        {"food_id": "broccoli", "grams": 80.0},
    ],
    [
        {"food_id": "chicken_breast", "grams": 150.0},
        {"food_id": "white_rice", "grams": 200.0},
        {"food_id": "broccoli", "grams": 100.0},
    ],
    [
        {"food_id": "chicken_breast", "grams": 180.0},
        {"food_id": "white_rice", "grams": 250.0},
        {"food_id": "broccoli", "grams": 100.0},
    ],
    [
        {"food_id": "chicken_breast", "grams": 200.0},
        {"food_id": "white_rice", "grams": 300.0},
        {"food_id": "broccoli", "grams": 150.0},
        {"food_id": "olive_oil", "grams": 20.0},
    ],
)


def _fitting_plan(task) -> list[dict]:
    windows = task.oracle.plan_windows or task.s0.profile.windows
    allergies = set(task.s0.profile.allergies)
    for items in _CANDIDATE_PLANS:
        if _plan_fits(items, task.s0.catalog, windows, allergies):
            return items
    raise AssertionError(f"no fitting plan for {task.id}")


def _plan_fits(
    items: list[dict],
    catalog: dict,
    windows: dict,
    allergies: set[str],
) -> bool:
    allergens: set[str] = set()
    totals: dict[str, float] = {}
    for item in items:
        food = catalog[item["food_id"]]
        allergens.update(food.get("allergen_tags") or [])
        grams = float(item["grams"])
        for key, amount in food["nutrients"].items():
            totals[key] = totals.get(key, 0.0) + float(amount) * grams / 100.0
    if allergens & allergies:
        return False
    for nutrient, (lo, hi) in windows.items():
        amount = totals.get(nutrient, 0.0)
        if amount < lo or amount > hi:
            return False
    return True


_UNUSED_FULL_MEAL = [
    {"food_id": "chicken_breast", "grams": 200.0},
    {"food_id": "white_rice", "grams": 300.0},
    {"food_id": "broccoli", "grams": 150.0},
    {"food_id": "olive_oil", "grams": 20.0},
]


def test_leftover_recommend_rejects_a_full_unused_meal() -> None:
    from nutrienv.bench.scorer import Scorer
    from nutrienv.env import NutriEnv

    leftovers = [
        task
        for task in load_split(GOLD_SPLIT_PATH)
        if task.persona == "leftover" and task.family == "recommend"
    ]
    assert leftovers
    scorer = Scorer()
    for task in leftovers:
        env = NutriEnv()
        env.reset(task.s0)
        env.step({"op": "submit_plan", "items": _UNUSED_FULL_MEAL})
        score = scorer.score(env.state(), task.oracle)
        assert score["passed"] is False, task.id
        assert score["tag"] == "window", (task.id, score)


def test_leftover_opening_observation_has_ledger_totals() -> None:
    from nutrienv.env import NutriEnv

    leftovers = [
        task
        for task in load_split(GOLD_SPLIT_PATH)
        if task.persona == "leftover" and task.family == "recommend"
    ]
    assert leftovers
    for task in leftovers:
        env = NutriEnv()
        opening = env.reset(task.s0)
        assert opening["ledger"], task.id
        assert "kcal" in opening["ledger"][0]["nutrients"], task.id
        assert "kcal" in opening["ledger_totals"], task.id
        eaten = opening["ledger_totals"]["kcal"]
        daily = task.s0.profile.windows["kcal"]
        remain = (max(0.0, daily[0] - eaten), max(0.0, daily[1] - eaten))
        got = task.oracle.plan_windows["kcal"]
        assert (round(remain[0], 2), round(remain[1], 2)) == got, (task.id, remain, got)


def test_leftover_plan_windows_match_ledger_remainder() -> None:
    for task in load_split(GOLD_SPLIT_PATH):
        if task.persona != "leftover" or task.family != "recommend":
            continue
        assert task.oracle.plan_windows, task.id
        expected = _remainder_windows(task)
        for key, (lo, hi) in expected.items():
            got = task.oracle.plan_windows[key]
            expected_pair = (round(lo, 2), round(hi, 2))
            assert got == expected_pair, (task.id, key, got, expected_pair, (lo, hi))


def _remainder_windows(task) -> dict[str, tuple[float, float]]:
    eaten: dict[str, float] = {}
    for row in task.s0.ledger:
        food = task.s0.catalog[row.food_id]
        for key, amount in food["nutrients"].items():
            eaten[key] = eaten.get(key, 0.0) + float(amount) * row.grams / 100.0
    remain: dict[str, tuple[float, float]] = {}
    for key, (lo, hi) in task.s0.profile.windows.items():
        used = eaten.get(key, 0.0)
        remain[key] = (max(0.0, lo - used), max(0.0, hi - used))
    return remain


def test_update_oracle_rejects_a_junk_log() -> None:
    from nutrienv.bench.scorer import Scorer
    from nutrienv.env import NutriEnv

    task = next(
        item
        for item in load_split(GOLD_SPLIT_PATH)
        if item.family == "update" and item.oracle.profile is not None
    )
    env = NutriEnv()
    env.reset(task.s0)
    patch: dict = {}
    if task.oracle.profile.allergies != task.s0.profile.allergies:
        patch["allergies"] = list(task.oracle.profile.allergies)
    if task.oracle.profile.windows != task.s0.profile.windows:
        patch["windows"] = {
            key: list(bounds) for key, bounds in task.oracle.profile.windows.items()
        }
    env.step({"op": "update_profile", "patch": patch})
    env.step(
        {
            "op": "log_meal",
            "food_id": "peanut",
            "grams": 500.0,
            "eaten_at": "today-junk",
        }
    )
    score = Scorer().score(env.state(), task.oracle)
    assert score["passed"] is False
    assert score["tag"] == "log_miss"


def test_one_leftover_still_owes_protein() -> None:
    floors = [
        task.oracle.plan_windows["protein_g"][0]
        for task in load_split(GOLD_SPLIT_PATH)
        if task.persona == "leftover" and task.oracle.plan_windows
    ]
    assert any(floor > 0 for floor in floors)


def test_gold_personas_are_mostly_everyday() -> None:
    tasks = load_split(GOLD_SPLIT_PATH)
    counts: dict[str, int] = {}
    for task in tasks:
        counts[task.persona] = counts.get(task.persona, 0) + 1
    assert counts.get("everyday", 0) > len(tasks) / 2
    assert counts.get("htn", 0) == 1
    assert {"cut", "gym", "leftover", "flex"} <= set(counts)
    assert counts["leftover"] >= 2
    assert not {"diabetes", "meds", "vegetarian", "vegan"} & set(counts)
    banned = ("medication", "metformin", "insulin", "diabetes", "vegetarian", "vegan")
    for task in tasks:
        assert task.s0.profile.medications == ()
        lower = task.query.lower()
        assert all(word not in lower for word in banned), task.id


def test_gold_spoken_food_phrases_are_searchable() -> None:
    from nutrienv.env import NutriEnv

    task = load_split(GOLD_SPLIT_PATH)[0]
    env = NutriEnv()
    env.reset(task.s0)
    cases = {
        "chicken breast": "chicken_breast",
        "greek yogurt": "greek_yogurt",
        "white rice": "white_rice",
        "olive oil": "olive_oil",
        "peanut butter": "peanut_butter",
    }
    def mentions(query: str, slug: str) -> bool:
        for row in env.step({"op": "search_foods", "q": query})["observation"]["results"]:
            if row["food_id"] == slug or slug in (row.get("aliases") or []):
                return True
        return False

    for query, food_id in cases.items():
        assert mentions(query, food_id), query
    assert mentions("oil", "olive_oil")
    oil_ids = [
        row["food_id"]
        for row in env.step({"op": "search_foods", "q": "oil"})["observation"]["results"]
    ]
    assert "beef" not in oil_ids
    assert "chicken_breast" not in oil_ids


def test_load_split_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_split(tmp_path / "missing.json")


def _fatigue_split(oracle: dict) -> dict:
    """A cut person who says the deficit is exhausting. S0 windows are the band floor."""
    body = {
        "sex": "female",
        "age_y": 34,
        "height_cm": 165.0,
        "weight_kg": 62.0,
        "activity": "light",
    }
    cut_windows = derive_daily_windows(**body, phase="cut")
    return {
        "version": "test-roster",
        "items": [
            {
                "id": "roster-upd-fatigue-001",
                "family": "update",
                "persona": "cut",
                "query": "This deficit is leaving me exhausted.",
                "s0": {
                    "profile": {
                        "user_id": "roster-ada",
                        "allergies": ["peanut"],
                        "windows": {k: list(v) for k, v in cut_windows.items()},
                        "phase": "cut",
                        **body,
                    },
                    "ledger": [],
                },
                "oracle": oracle,
            }
        ],
    }


def test_band_oracle_keeps_s0_windows_through_a_phase_change(tmp_path: Path) -> None:
    """A fatigue oracle that names the target phase must not re-derive windows.

    Deriving them would make ``expected.windows`` the maintain windows, and the
    fatigue band ("higher than S0, at most maintain EER") would then compare the
    end state against itself and never Pass.
    """
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = _fatigue_split(
        {"profile": {"phase": "maintain"}, "ledger": "s0", "update_band": "fatigue"}
    )
    path = tmp_path / "fatigue-phase.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    task = load_split(path, catalog=demo_catalog())[0]
    assert task.oracle.update_band == "fatigue"
    assert task.oracle.profile is not None
    assert task.oracle.profile.phase == "maintain"
    assert task.oracle.profile.windows == task.s0.profile.windows


def test_band_oracle_rejects_named_windows(tmp_path: Path) -> None:
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = _fatigue_split(
        {
            "profile": {"windows": {"kcal": [1400.0, 1600.0]}},
            "ledger": "s0",
            "update_band": "fatigue",
        }
    )
    path = tmp_path / "fatigue-named-windows.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="band baseline"):
        load_split(path, catalog=demo_catalog())


def test_band_oracle_requires_a_profile(tmp_path: Path) -> None:
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = _fatigue_split({"ledger": "s0", "update_band": "fatigue"})
    path = tmp_path / "fatigue-no-profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="requires oracle.profile"):
        load_split(path, catalog=demo_catalog())


def test_fatigue_band_survives_a_freeze_load_round_trip(tmp_path: Path) -> None:
    """The published exam is frozen JSON, so a band that only works in memory is broken."""
    from nutrienv.bench.pipeline.freezer import task_to_item
    from nutrienv.bench.scorer import Scorer
    from nutrienv.env import NutriEnv
    from nutrienv.world.catalog_fixture import demo_catalog

    payload = _fatigue_split(
        {"profile": {"phase": "maintain"}, "ledger": "s0", "update_band": "fatigue"}
    )
    path = tmp_path / "fatigue.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    task = load_split(path, catalog=demo_catalog())[0]

    frozen = tmp_path / "fatigue-refrozen.json"
    frozen.write_text(
        json.dumps({"version": "test-roster", "items": [task_to_item(task)]}),
        encoding="utf-8",
    )
    reloaded = load_split(frozen, catalog=demo_catalog())[0]
    assert reloaded.oracle.profile.windows == reloaded.s0.profile.windows

    env = NutriEnv()
    env.reset(reloaded.s0)
    env.step({"op": "update_profile", "patch": {"phase": "maintain"}})
    assert Scorer().score(env.state(), reloaded.oracle) == {"passed": True, "tag": "pass"}


def test_load_split_keeps_declared_tiers(tmp_path: Path) -> None:
    payload = {
        "items": [
            {
                "id": "ev-tiered",
                "family": "evaluate",
                "query": "Is this dinner okay?",
                "tier": "pair",
                "s0": {"profile": {"windows": {"kcal": [400, 700]}}},
                "oracle": {
                    "last_plan": [{"food_id": "egg", "grams": 50.0}],
                    "evaluated_plan": [{"food_id": "egg", "grams": 50.0}],
                    "last_verdict": "accept",
                },
            },
            {
                "id": "log-untiered",
                "family": "log",
                "query": "I ate an egg.",
                "s0": {},
                "oracle": {"ledger_tail": [{"food_id": "egg", "grams": 50.0, "eaten_at": "lunch"}]},
            },
        ]
    }
    path = tmp_path / "tiers.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    tasks = load_split(path)
    assert [task.tier for task in tasks] == ["pair", ""]

    payload["items"][0]["tier"] = 7
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="tier"):
        load_split(path)


def test_task_tier_round_trips_through_the_freezer(tmp_path: Path) -> None:
    from nutrienv.bench.pipeline.freezer import task_to_item
    from nutrienv.bench.realize import Oracle
    from nutrienv.world.catalog_fixture import demo_catalog
    from nutrienv.world.types import Profile, WorldState

    def _state():
        return WorldState(profile=Profile(user_id="u"), catalog=demo_catalog())

    tiered = Task("ev-pair", "evaluate", "Okay?", _state(), Oracle(), (), "everyday", "pair")
    plain = Task("log-x", "log", "I ate.", _state(), Oracle())
    assert task_to_item(tiered)["tier"] == "pair"
    assert "tier" not in task_to_item(plain)

    item = task_to_item(tiered)
    path = tmp_path / "rt.json"
    path.write_text(json.dumps({"items": [item]}), encoding="utf-8")
    assert load_split(path)[0].tier == "pair"


def test_load_split_whitelists_declared_tiers(tmp_path: Path) -> None:
    payload = {
        "items": [
            {
                "id": "ev-mystery",
                "family": "evaluate",
                "query": "Okay?",
                "tier": "mystery",
                "s0": {},
                "oracle": {"last_plan": []},
            }
        ]
    }
    path = tmp_path / "mystery.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="tier"):
        load_split(path)


def _tier_item(tier: object) -> dict:
    item = {
        "id": "ev-tier-kind",
        "family": "evaluate",
        "query": "Okay?",
        "s0": {},
        "oracle": {"last_plan": []},
    }
    if tier is not ...:
        item["tier"] = tier
    return item


@pytest.mark.parametrize("bad", [0, False, [], 3.2])
def test_load_split_rejects_non_string_declared_tiers(
    tmp_path: Path, bad: object
) -> None:
    payload = {"items": [_tier_item(bad)]}
    path = tmp_path / "bad-tier.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="tier must be empty or one of"):
        load_split(path)


@pytest.mark.parametrize("untiered", [..., None, ""])
def test_load_split_loads_absent_null_and_empty_tiers_untiered(
    tmp_path: Path, untiered: object
) -> None:
    payload = {"items": [_tier_item(untiered)]}
    path = tmp_path / "untiered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_split(path)[0].tier == ""


def test_load_split_still_rejects_unknown_declared_tiers(tmp_path: Path) -> None:
    payload = {"items": [_tier_item("mystery")]}
    path = tmp_path / "mystery.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="tier must be empty or one of"):
        load_split(path)
