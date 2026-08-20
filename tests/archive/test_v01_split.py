import json
from pathlib import Path

from nutrienv.bench.split import GOLD_SPLIT_PATH, load_split
from nutrienv.bench.validator import validate_draft
from nutrienv.bench.scorer import Scorer
from nutrienv.env import NutriEnv

V01 = Path("data/splits/v0.1-gold.json")


def test_v01_keeps_v0_items_and_adds_reviewed_slice():
    v0 = json.loads(GOLD_SPLIT_PATH.read_text())
    v01 = json.loads(V01.read_text())
    assert v01["items"][:40] == v0["items"]
    assert 56 <= len(v01["items"]) <= 64
    assert v01["catalog"] == "data/fdc/catalog.sqlite"
    assert v01["catalog_sha256"]
    tasks = load_split(V01)
    assert len(tasks) == len(v01["items"])
    assert len({task.id for task in tasks}) == len(tasks)
    new = [task for task in tasks if task.id.startswith("v01-")]
    assert 16 <= len(new) <= 24
    assert all(task.family != "lookup" for task in tasks)
    fuzzy = [task for task in new if task.family == "log"]
    leftover = [task for task in new if task.persona == "leftover"]
    assert len(fuzzy) >= 16
    assert len(leftover) >= 8
    assert all(validate_draft(task) == [] for task in new)


def test_v01_log_oracle_passes_via_log_meal():
    env = NutriEnv()
    scorer = Scorer()
    for task in load_split(V01):
        if not task.id.startswith("v01-") or task.family != "log":
            continue
        env.reset(task.s0)
        for row in task.oracle.ledger_tail:
            env.step(
                {
                    "op": "log_meal",
                    "food_id": row.food_id,
                    "grams": row.grams,
                    "eaten_at": row.eaten_at,
                }
            )
        score = scorer.score(env.state(), task.oracle)
        assert score["passed"], (task.id, score)
