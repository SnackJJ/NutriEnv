"""The v0.2 increment: v0.1's 64 items kept, plus a reviewed 36-item slice."""

import json
from pathlib import Path

from nutrienv.bench.scorer import Scorer
from nutrienv.bench.split import load_split
from nutrienv.bench.validator import fitting_plan as _fitting_plan
from nutrienv.bench.validator import validate_draft
from nutrienv.env import NutriEnv

V01 = Path("data/splits/v0.1-gold.json")
V02 = Path("data/splits/v0.2-gold.json")


def test_v02_keeps_v01_items_and_adds_a_reviewed_slice():
    v01 = json.loads(V01.read_text())
    v02 = json.loads(V02.read_text())
    assert v02["items"][:64] == v01["items"]
    assert 96 <= len(v02["items"]) <= 100
    assert v02["catalog"] == "data/fdc/catalog.sqlite"
    assert v02["catalog_sha256"] == v01["catalog_sha256"]
    assert v02["parent"] == "v0.1-gold"

    tasks = load_split(V02)
    assert len(tasks) == len(v02["items"])
    assert len({task.id for task in tasks}) == len(tasks)
    assert all(task.family != "lookup" for task in tasks)

    new = tasks[64:]
    assert all(task.id.startswith("v02-") for task in new)
    assert len([t for t in new if t.persona == "leftover"]) >= 16
    assert len([t for t in new if t.family == "update"]) >= 8
    assert len([t for t in new if t.family == "constrain"]) >= 8
    assert len([t for t in new if t.family == "evaluate"]) >= 4
    assert all(validate_draft(task) == [] for task in new)


def test_v02_leftover_total_clears_the_adr_floor():
    """ADR 0009 wants at least 24 leftover recommends in the destination exam."""
    tasks = load_split(V02)
    assert len([task for task in tasks if task.persona == "leftover"]) >= 24


def test_v02_constrain_keeps_two_distinct_oracle_contracts():
    new = load_split(V02)[64:]
    condition = [t for t in new if "condition_suitability" in t.situations]
    conflict = [t for t in new if "conflict_windows" in t.situations]
    assert condition and conflict
    for task in condition:
        assert task.oracle.last_plan == []
        assert task.oracle.allow_empty_plan is False
        assert task.oracle.plan_must_be_safe
    for task in conflict:
        assert task.oracle.last_plan is None
        assert task.oracle.allow_empty_plan is True
        assert task.s0.last_plan, task.id


def test_v02_new_oracles_are_achievable():
    """Every new item can actually be passed. An unpassable frozen item is a
    silent hole: the agent does everything right and still fails."""
    scorer = Scorer()
    for task in load_split(V02)[64:]:
        env = NutriEnv()
        env.reset(task.s0)
        if task.family == "update":
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
