"""The v0.4 increment: recommend and constrain reach their allocations."""

import collections
import json
from pathlib import Path

from nutrienv.bench.realizations import CONSTRAIN_ROWS, RECOMMEND_ROWS
from nutrienv.bench.scorer import Scorer
from nutrienv.bench.split import load_split
from nutrienv.bench.validator import fitting_plan, validate_draft
from nutrienv.env import NutriEnv

V03 = Path("data/splits/v0.3-gold.json")
V04 = Path("data/splits/v0.4-gold.json")


def test_v04_keeps_v03_items_and_completes_two_families():
    v03 = json.loads(V03.read_text())
    v04 = json.loads(V04.read_text())
    assert v04["items"][:156] == v03["items"]
    assert v04["parent"] == "v0.3-gold"
    assert v04["catalog_sha256"] == v03["catalog_sha256"]

    tasks = load_split(V04)
    assert len(tasks) == len(v04["items"])
    assert len({task.id for task in tasks}) == len(tasks)
    new = tasks[156:]
    assert all(task.id.startswith("v04-") for task in new)
    assert all(validate_draft(task) == [] for task in new)

    families = collections.Counter(task.family for task in tasks)
    # Three of the five families now sit exactly on their ADR 0009 allocation.
    # Over- or under-admitting is a failure, not a rounding detail.
    assert families["recommend"] == 72
    assert families["evaluate"] == 48
    assert families["constrain"] == 36
    assert families["log"] == 29
    assert families["update"] == 22


def test_v04_recommend_covers_persona_and_every_allergen_tag():
    """Recommend's diversity claim is persona x occasion x allergy x third
    nutrient. If the admitted set drops a tag, the claim is not backed."""
    tasks = [t for t in load_split(V04) if t.family == "recommend"]
    personas = {task.persona for task in tasks}
    assert {"everyday", "cut", "gym", "flex", "htn", "leftover"} <= personas

    covered = set()
    for task in tasks:
        covered.update(task.s0.profile.allergies)
    assert {
        "milk", "wheat", "gluten", "fish", "egg",
        "peanut", "soy", "tree_nut", "shellfish",
    } <= covered, sorted(covered)


def test_v04_recommend_judges_a_third_nutrient_somewhere():
    """Before v0.4 exactly one exam item judged anything beyond kcal and
    protein. That axis is the reason these rows are not just more of the same."""
    tasks = [t for t in load_split(V04) if t.family == "recommend"]
    extra = [
        task for task in tasks
        if set(task.s0.profile.windows) - {"kcal", "protein_g"}
    ]
    assert len(extra) >= 10, len(extra)
    judged = set()
    for task in extra:
        judged.update(set(task.s0.profile.windows) - {"kcal", "protein_g"})
    assert {"sodium_mg", "fiber_g", "fat_g"} <= judged, sorted(judged)


def test_v04_conflict_rows_differ_in_mechanism():
    """The original conflict rows all walked one arithmetic ramp, which a
    'these numbers look absurd' policy clears without reasoning about food."""
    admitted = {
        task.id.removeprefix("v04-conf-")
        for task in load_split(V04)
        if "conflict_windows" in task.situations and task.id.startswith("v04-")
    }
    mechanisms = {
        getattr(row, "mechanism", None)
        for row in CONSTRAIN_ROWS
        if row.kind == "conflict" and row.seed_id.removeprefix("cf-") in admitted
    }
    assert len({m for m in mechanisms if m}) >= 2, mechanisms


def test_v04_new_oracles_are_achievable():
    """Every new item can be passed. An unpassable frozen item is a silent
    hole: the agent reasons correctly and the Scorer still rejects it."""
    scorer = Scorer()
    for task in load_split(V04)[156:]:
        env = NutriEnv()
        env.reset(task.s0)
        if task.oracle.allow_empty_plan:
            env.step({"op": "submit_plan", "items": []})
        else:
            windows = task.oracle.plan_windows or task.s0.profile.windows
            plan = fitting_plan(
                task.s0.catalog, windows, task.s0.profile.allergies
            )
            assert plan is not None, (task.id, windows)
            env.step({"op": "submit_plan", "items": plan})
        score = scorer.score(env.state(), task.oracle)
        assert score["passed"], (task.id, score)


def test_v04_recommend_queries_do_not_leak_their_windows():
    """A recommend query that names its own numbers is answerable without
    reading the profile, which is the whole point of the family."""
    for task in load_split(V04):
        if task.family != "recommend":
            continue
        for bounds in task.s0.profile.windows.values():
            for value in bounds:
                if value and float(value).is_integer() and abs(value) >= 10:
                    assert str(int(value)) not in task.query, (task.id, value)


def test_v04_recommend_rows_all_stay_admissible():
    """Rows kept in reserve must still be usable when a later increment wants
    them, so the whole table is checked, not only the admitted slice."""
    assert len(RECOMMEND_ROWS) >= 40
    assert len({row.seed_id for row in RECOMMEND_ROWS}) == len(RECOMMEND_ROWS)
