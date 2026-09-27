"""Ticket 08 freeze gate: implicit-band Update items survive freeze→load replay.

04-fix defect (a) regression gate: a new implicit-band item must reload
via ``load_split`` and replay the Oracle's Env actions to score==pass,
with at least one cut, one fatigue, and one muscle item.
"""

from __future__ import annotations

from pathlib import Path

from nutrienv.bench.achievable import check_achievable
from nutrienv.bench.pipeline.freezer import freeze_tasks
from nutrienv.bench.pipeline.generate_one import generate_one
from nutrienv.bench.pipeline.roster import ROSTER
from nutrienv.bench.scorer import Scorer
from nutrienv.bench.split import load_split
from nutrienv.bench.validator import validate_draft
from nutrienv.env import NutriEnv


def _food(name, portions, aliases=(), allergen_tags=()):
    return {
        "name": name,
        "portions": dict(portions),
        "aliases": list(aliases),
        "allergen_tags": list(allergen_tags),
        "nutrients": {},
    }


def _catalog() -> dict:
    return {
        "shrimp": _food("Shrimp, cooked", {"piece": 25.0}, ("shrimp",), ("shellfish",)),
        "milk_whole": _food("Milk, whole", {"cup": 244.0}, ("milk",), ("milk",)),
        "peanut": _food("Peanuts, raw", {"piece": 5.0}, ("peanut",), ("peanut",)),
        "egg": _food("Egg, whole", {"piece": 50.0}, ("egg",), ("egg",)),
    }


def _band_tasks():
    maintainer = ROSTER[3]
    cutter = ROSTER[2]
    specs = [
        (maintainer, "upd-phase-cut"),
        (maintainer, "upd-phase-muscle"),
        (cutter, "upd-fatigue"),
    ]
    tasks = []
    for seed, (person, shell) in enumerate(specs, start=21):
        result = generate_one(
            catalog=_catalog(),
            family="update",
            seed=seed,
            person=person,
            shell=shell,
        )
        assert result.rejected is None
        assert result.accepted is not None
        tasks.append(result.accepted)
    return tasks


def _replay_action(task):
    band = task.oracle.update_band
    if band == "fatigue":
        return {"op": "update_profile", "patch": {"phase": "maintain"}}
    return {"op": "update_profile", "patch": {"phase": task.oracle.profile.phase}}


def test_implicit_band_items_survive_freeze_load_and_replay_to_pass(
    tmp_path: Path,
) -> None:
    tasks = _band_tasks()
    assert {task.oracle.update_band for task in tasks} >= {
        "cut",
        "fatigue",
        "muscle",
    }
    for task in tasks:
        assert validate_draft(task) == []

    catalog = tasks[0].s0.catalog
    _, target = freeze_tasks(tasks, catalog=catalog, output_path=tmp_path / "bands.json")

    loaded = load_split(target, catalog=catalog)
    assert [task.id for task in loaded] == [task.id for task in tasks]
    assert {task.oracle.update_band for task in loaded} >= {
        "cut",
        "fatigue",
        "muscle",
    }

    scorer = Scorer()
    for task in loaded:
        env = NutriEnv()
        env.reset(task.s0)
        out = env.step(_replay_action(task))
        assert out.get("ok") is True, task.id
        result = scorer.score(env.state(), task.oracle)
        assert result == {"passed": True, "tag": "pass"}, task.id

    report = check_achievable(loaded)
    assert report.unreachable == ()
