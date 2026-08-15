"""The v0.3 increment: v0.2's 100 items kept, evaluate completes its allocation."""

import collections
import json
from pathlib import Path

from nutrienv.bench.realizations import EVALUATE_ROWS
from nutrienv.bench.scorer import Scorer
from nutrienv.bench.split import load_split
from nutrienv.bench.validator import validate_draft
from nutrienv.env import NutriEnv
from tests.test_v02_split import _fitting_plan

V02 = Path("data/splits/v0.2-gold.json")
V03 = Path("data/splits/v0.3-gold.json")


def test_v03_keeps_v02_items_and_completes_evaluate():
    v02 = json.loads(V02.read_text())
    v03 = json.loads(V03.read_text())
    assert v03["items"][:100] == v02["items"]
    assert v03["parent"] == "v0.2-gold"
    assert v03["catalog_sha256"] == v02["catalog_sha256"]

    tasks = load_split(V03)
    assert len(tasks) == len(v03["items"])
    assert len({task.id for task in tasks}) == len(tasks)
    new = tasks[100:]
    assert all(task.id.startswith("v03-") for task in new)
    assert all(validate_draft(task) == [] for task in new)

    families = collections.Counter(task.family for task in tasks)
    # ADR 0009 allocates evaluate 48 of the 240. This is the increment that
    # lands it exactly, so an accidental over- or under-admission is a failure,
    # not a rounding detail.
    assert families["evaluate"] == 48
    assert families["log"] == 29
    assert families["update"] == 22
    assert families["constrain"] == 16
    assert families["recommend"] == 41


def test_v03_evaluate_covers_every_difficulty_tier():
    """The 48 slots are only worth having if they differ on a declared axis."""
    ids = {task.id for task in load_split(V03) if task.family == "evaluate"}
    tiers = collections.Counter()
    for row in EVALUATE_ROWS:
        if f"v03-eval-{row.seed_id.removeprefix('ev-')}" in ids:
            tiers[getattr(row, "tier", "untiered")] += 1
    for tier, least in (
        ("single", 7), ("pair", 11), ("triple", 11),
        ("long", 5), ("forced_grams", 4), ("synonym", 3),
    ):
        assert tiers[tier] >= least, (tier, tiers[tier], dict(tiers))


def test_v03_evaluate_plans_are_passable_under_their_own_profile():
    """An evaluate item is passed by submitting its exact plan, so a profile
    allergy that the plan itself trips makes the item unpassable."""
    for task in load_split(V03):
        if task.family != "evaluate":
            continue
        allergies = set(task.s0.profile.allergies)
        for item in task.oracle.last_plan:
            tags = set(task.s0.catalog[item["food_id"]].get("allergen_tags") or [])
            assert not tags & allergies, (task.id, item["food_id"], tags & allergies)


def test_v03_new_oracles_are_achievable():
    scorer = Scorer()
    for task in load_split(V03)[100:]:
        env = NutriEnv()
        env.reset(task.s0)
        if task.family == "log":
            for row in task.oracle.ledger_tail:
                env.step({
                    "op": "log_meal",
                    "food_id": row.food_id,
                    "grams": row.grams,
                    "eaten_at": row.eaten_at,
                })
        elif task.family == "update":
            profile = task.oracle.profile
            env.step({
                "op": "update_profile",
                "patch": {
                    "allergies": list(profile.allergies),
                    "windows": {k: list(v) for k, v in profile.windows.items()},
                },
            })
        elif task.family == "evaluate":
            env.step({"op": "submit_plan", "items": task.oracle.last_plan})
        elif task.oracle.allow_empty_plan:
            env.step({"op": "submit_plan", "items": []})
        else:
            windows = task.oracle.plan_windows or task.s0.profile.windows
            plan = _fitting_plan(
                task.s0.catalog, windows, set(task.s0.profile.allergies)
            )
            assert plan is not None, (task.id, windows)
            env.step({"op": "submit_plan", "items": plan})
        score = scorer.score(env.state(), task.oracle)
        assert score["passed"], (task.id, score)
