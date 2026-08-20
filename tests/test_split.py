"""Frozen gold split is the exam; queries must not leak the answer."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nutrienv.bench.split import GOLD_SPLIT_PATH, load_split
from nutrienv.world.types import LedgerRow

_WINDOW_LEAK = re.compile(r"\b(?:kcal|protein_g|carb_g|fat_g)\s+\d")
_SLUG = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")


def test_legacy_split_items_load_without_rewriting_windows() -> None:
    path = Path("data/splits/v0.5-gold.json")
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


def test_oracle_profile_cannot_override_body_facts(tmp_path: Path) -> None:
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
    with pytest.raises(ValueError, match="body"):
        load_split(path, catalog=demo_catalog())


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


def test_load_split_v05_is_the_240() -> None:
    tasks = load_split(Path("data/splits/v0.5-gold.json"))
    assert len(tasks) == 240
    assert len({task.id for task in tasks}) == 240


def test_load_split_default_is_v05() -> None:
    from nutrienv.bench.split import EXAM_SPLIT_PATH

    assert EXAM_SPLIT_PATH.name == "v0.5-gold.json"
    tasks = load_split()
    assert len(tasks) == 240
    assert len({task.id for task in tasks}) == 240


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
    from nutrienv.bench.scorer import Scorer
    from nutrienv.env import NutriEnv

    scorer = Scorer()
    for task in load_split(GOLD_SPLIT_PATH):
        env = NutriEnv()
        env.reset(task.s0)
        if task.oracle.ledger_tail:
            for row in task.oracle.ledger_tail:
                stepped = env.step(
                    {
                        "op": "log_meal",
                        "food_id": row.food_id,
                        "grams": row.grams,
                        "eaten_at": row.eaten_at,
                    }
                )
                assert stepped["ok"], (task.id, stepped)
        elif task.oracle.last_plan:
            stepped = env.step({"op": "submit_plan", "items": task.oracle.last_plan})
            assert stepped["ok"], (task.id, stepped)
        elif task.oracle.last_plan == []:
            plan = _fitting_plan(task)
            assert plan, task.id
            stepped = env.step({"op": "submit_plan", "items": plan})
            assert stepped["ok"], (task.id, stepped)
        elif task.oracle.allow_empty_plan:
            stepped = env.step({"op": "submit_plan", "items": []})
            assert stepped["ok"], (task.id, stepped)
        elif task.family == "update":
            patch: dict = {}
            assert task.oracle.profile is not None
            if task.oracle.profile.allergies != task.s0.profile.allergies:
                patch["allergies"] = list(task.oracle.profile.allergies)
            if task.oracle.profile.windows != task.s0.profile.windows:
                patch["windows"] = {
                    key: list(bounds) for key, bounds in task.oracle.profile.windows.items()
                }
            stepped = env.step({"op": "update_profile", "patch": patch})
            assert stepped["ok"], (task.id, stepped)
        score = scorer.score(env.state(), task.oracle)
        assert score["passed"], (task.id, score)


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
