"""Published v1.0 exam and catalog still load."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from nutrienv.bench.split import EXAM_SPLIT_PATH, load_exam, load_split


def test_published_exam_is_63_and_matches_load_exam() -> None:
    assert EXAM_SPLIT_PATH.name == "nutrienv-v1.0.json"
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


def test_mini_is_ten_task_subset_of_v1() -> None:
    public = load_split(Path("data/splits/nutrienv-v1.0.json"))
    mini = load_split(Path("data/splits/nutrienv-mini.json"))
    assert len(mini) == 10
    assert {t.id for t in mini} <= {t.id for t in public}
