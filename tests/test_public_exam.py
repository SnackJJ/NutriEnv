"""Published v1.1 exam, reductions and historical v1.0 still load."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from nutrienv.bench.split import EXAM_SPLIT_PATH, load_exam, load_split


def test_published_exam_is_63_and_matches_load_exam() -> None:
    assert EXAM_SPLIT_PATH.name == "nutrienv-v1.1.json"
    tasks = load_split()
    exam = load_exam()
    assert len(tasks) == 63
    assert {t.id for t in tasks} == {t.id for t in exam}
    assert Counter(t.family for t in tasks) == {
        "update": 2,
        "log": 6,
        "evaluate": 8,
        "recommend": 11,
        "composite": 36,
    }


def test_mini_is_ten_task_subset_of_v1_1() -> None:
    public = load_exam()
    mini = load_split(Path("data/splits/nutrienv-mini.json"))
    assert len(mini) == 10
    assert {t.id for t in mini} <= {t.id for t in public}


def test_historical_v1_0_still_loads() -> None:
    assert len(load_split(Path("data/splits/nutrienv-v1.0.json"))) == 63
