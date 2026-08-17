"""v0.5 is the 240. Every family sits exactly on its ADR 0009 allocation."""

import collections
import hashlib
import json
from pathlib import Path

from nutrienv.bench.scorer import Scorer
from nutrienv.bench.split import load_split
from nutrienv.bench.validator import fitting_plan, validate_draft
from nutrienv.env import NutriEnv

V04 = Path("data/splits/v0.4-gold.json")
V05 = Path("data/splits/v0.5-gold.json")
CATALOG = Path("data/fdc/catalog.sqlite")

ALLOCATION = {
    "log": 48, "recommend": 72, "evaluate": 48, "update": 36, "constrain": 36,
}


def test_v05_is_the_240():
    v04 = json.loads(V04.read_text())
    v05 = json.loads(V05.read_text())
    assert v05["items"][:207] == v04["items"]
    assert v05["parent"] == "v0.4-gold"
    assert v05["catalog_sha256"] == hashlib.sha256(CATALOG.read_bytes()).hexdigest()

    tasks = load_split(V05)
    assert len(tasks) == 240
    assert len({task.id for task in tasks}) == 240
    assert collections.Counter(task.family for task in tasks) == ALLOCATION


def test_v05_every_item_validates():
    """Not only the new slice. The gates tightened repeatedly across five
    increments, and an older item that no longer passes is a regression."""
    bad = [(task.id, validate_draft(task)) for task in load_split(V05)]
    assert not [entry for entry in bad if entry[1]], [e for e in bad if e[1]][:5]


def test_v05_log_is_no_longer_one_situation():
    """log was 23 of 29 fuzzy_portion because its other four situations each
    existed as a single hardcoded instance in the generator."""
    counts = collections.Counter(
        (tuple(task.situations) or ("",))[0]
        for task in load_split(V05)
        if task.family == "log"
    )
    for situation, least in (
        ("fuzzy_portion", 20), ("multi_item_log", 8),
        ("unit_convert", 6), ("near_synonym", 6), ("ledger_gap", 4),
    ):
        assert counts[situation] >= least, (situation, counts[situation], dict(counts))
    assert counts["fuzzy_portion"] / sum(counts.values()) < 0.55


def test_v05_update_covers_the_axes_it_never_had():
    """Before v0.5 every update added an allergen or moved both ends of one
    window by the same amount. Nothing removed, narrowed, or changed a preset."""
    updates = [t for t in load_split(V05) if t.family == "update"]
    removals = one_bound = two_windows = presets = 0
    for task in updates:
        s0, oracle = task.s0.profile, task.oracle.profile
        if set(s0.allergies) - set(oracle.allergies):
            removals += 1
        if oracle.plan_preset != s0.plan_preset:
            presets += 1
        moved = [
            key for key, bounds in oracle.windows.items()
            if s0.windows.get(key) != bounds
        ]
        if len(moved) > 1:
            two_windows += 1
        for key in moved:
            lo0, hi0 = s0.windows[key]
            lo1, hi1 = oracle.windows[key]
            if (lo1 - lo0) != (hi1 - hi0):
                one_bound += 1
                break
    assert removals >= 3, removals
    assert one_bound >= 5, one_bound
    assert two_windows >= 2, two_windows
    assert presets >= 2, presets


def test_v05_ledger_gap_items_really_have_a_hole():
    for task in load_split(V05):
        if "ledger_gap" not in task.situations:
            continue
        occupied = {row.eaten_at for row in task.s0.ledger}
        for row in task.oracle.ledger_tail:
            assert row.eaten_at not in occupied, (task.id, row.eaten_at)


def test_v05_new_oracles_are_achievable():
    scorer = Scorer()
    for task in load_split(V05)[207:]:
        env = NutriEnv()
        env.reset(task.s0)
        if task.family == "log":
            for row in task.oracle.ledger_tail:
                stepped = env.step({
                    "op": "log_meal",
                    "food_id": row.food_id,
                    "grams": row.grams,
                    "eaten_at": row.eaten_at,
                })
                assert stepped.get("ok", True), (task.id, stepped)
        elif task.family == "update":
            s0, oracle = task.s0.profile, task.oracle.profile
            patch: dict = {}
            if oracle.allergies != s0.allergies:
                patch["allergies"] = list(oracle.allergies)
            if oracle.windows != s0.windows:
                patch["windows"] = {k: list(v) for k, v in oracle.windows.items()}
            if oracle.plan_preset != s0.plan_preset:
                patch["plan_preset"] = oracle.plan_preset
            env.step({"op": "update_profile", "patch": patch})
        score = scorer.score(env.state(), task.oracle)
        assert score["passed"], (task.id, score)


def test_v05_whole_exam_is_achievable():
    """The headline claim of the benchmark is that every one of the 240 can be
    passed. Prove it for all of them, not just the newest slice."""
    scorer = Scorer()
    for task in load_split(V05):
        env = NutriEnv()
        env.reset(task.s0)
        if task.oracle.ledger_tail:
            for row in task.oracle.ledger_tail:
                env.step({
                    "op": "log_meal",
                    "food_id": row.food_id,
                    "grams": row.grams,
                    "eaten_at": row.eaten_at,
                })
        elif task.family == "update":
            s0, oracle = task.s0.profile, task.oracle.profile
            patch = {
                "allergies": list(oracle.allergies),
                "windows": {k: list(v) for k, v in oracle.windows.items()},
            }
            if oracle.plan_preset != s0.plan_preset:
                patch["plan_preset"] = oracle.plan_preset
            env.step({"op": "update_profile", "patch": patch})
        elif task.oracle.last_plan:
            env.step({"op": "submit_plan", "items": task.oracle.last_plan})
        elif task.oracle.allow_empty_plan:
            env.step({"op": "submit_plan", "items": []})
        elif task.oracle.last_plan == []:
            windows = task.oracle.plan_windows or task.s0.profile.windows
            plan = fitting_plan(
                task.s0.catalog, windows, task.s0.profile.allergies
            )
            assert plan is not None, (task.id, windows)
            env.step({"op": "submit_plan", "items": plan})
        score = scorer.score(env.state(), task.oracle)
        assert score["passed"], (task.id, score)
