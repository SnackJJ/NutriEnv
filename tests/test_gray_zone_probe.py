"""Gray-zone probe is the judge gate: ground-truth misses must fail."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "archive"))
import gray_zone_probe as probe  # noqa: E402


def _result(case_id: str, group: str, expect_accept: bool, accepted: bool) -> probe.Result:
    case = probe.Case(case_id, "food", 1.0, group, "src", expect_accept)
    return probe.Result(case, ["ok"], ["reason"], 1.0 if accepted else 0.0, accepted)


def _full_pass() -> list[probe.Result]:
    return [
        _result("sandwich-piece-175", "gray", True, True),
        _result("sandwich-qns-115", "gray", True, True),
        _result("lasagna-piece-206", "gray", True, True),
        _result("lasagna-qns-250", "gray", True, True),
        _result("omelet-piece-55", "gray", True, True),
        _result("omelet-qns-110", "gray", True, True),
        _result("chicken-piece-105", "gray", True, True),
        _result("tuna-can-75", "gray", True, True),
        _result("beef-piece-65", "gray", True, True),
        _result("ctrl-steak-030", "absurd", False, False),
        _result("ctrl-banana-010", "absurd", False, False),
        _result("ctrl-oil-100", "absurd", False, False),
        _result("ctrl-steak-160", "normal", True, True),
        _result("ctrl-banana-126", "normal", True, True),
    ]


def _set_accepted(rows: list[probe.Result], case_id: str, accepted: bool) -> list[probe.Result]:
    return [
        row
        if row.case.case_id != case_id
        else _result(case_id, row.case.group, row.case.expect_accept, accepted)
        for row in rows
    ]


def test_conclude_passes_when_all_ground_truth_holds(capsys) -> None:
    assert probe.conclude(_full_pass()) is True
    assert "GATE_SAFE" in capsys.readouterr().out


def test_conclude_fails_on_gray_false_kill(capsys) -> None:
    rows = _set_accepted(_full_pass(), "omelet-piece-55", False)
    assert probe.conclude(rows) is False
    assert "GATE_NEEDS_ADJUSTMENT" in capsys.readouterr().out


def test_conclude_fails_on_absurd_leak(capsys) -> None:
    rows = _set_accepted(_full_pass(), "ctrl-steak-030", True)
    assert probe.conclude(rows) is False
    assert "mixed" in capsys.readouterr().out


def test_conclude_fails_on_normal_miss(capsys) -> None:
    rows = _set_accepted(_full_pass(), "ctrl-steak-160", False)
    assert probe.conclude(rows) is False
    assert "mixed" in capsys.readouterr().out


def test_probe_uses_catalog_v2() -> None:
    assert probe.CATALOG_V2_PATH == ROOT / "data" / "fdc" / "catalog-v2.sqlite"
    assert probe.K == 5
    assert probe.THRESHOLD == 0.6


def test_confirm_catalog_v2_anchors() -> None:
    found = probe.confirm_catalog()
    assert found["2707198"]["piece"] == 55.0
    assert found["2707198"]["qns"] == 110.0
    assert found["chicken_breast"]["grams"] == 105.0
    assert found["tuna"]["grams"] == 75.0
    assert found["beef"]["grams"] == 65.0


def test_build_cases_includes_staple_first_wins_anchors() -> None:
    confirmed = {
        "2706880": {"label": "sandwich", "name": "sandwich", "piece": 175.0, "qns": 115.0, "ratio": "1.52x"},
        "2708750": {"label": "lasagna", "name": "lasagna", "piece": 206.0, "qns": 250.0, "ratio": "1.21x"},
        "2707198": {"label": "omelet", "name": "omelet", "piece": 55.0, "qns": 110.0, "ratio": "2.00x"},
        "chicken_breast": {
            "label": "chicken",
            "name": "chicken",
            "key": "piece",
            "grams": 105.0,
            "diary": "chicken breast",
        },
        "tuna": {"label": "tuna", "name": "tuna", "key": "can", "grams": 75.0, "diary": "tuna"},
        "beef": {"label": "beef", "name": "beef", "key": "piece", "grams": 65.0, "diary": "beef"},
    }
    ids = [case.case_id for case in probe.build_cases(confirmed)]
    assert "tuna-can-75" in ids
    assert "beef-piece-65" in ids
    assert "chicken-piece-105" in ids
