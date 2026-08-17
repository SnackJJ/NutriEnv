"""Gray-zone probe is the judge gate: ground-truth misses must fail."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
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
        _result("ctrl-steak-030", "absurd", False, False),
        _result("ctrl-banana-010", "absurd", False, False),
        _result("ctrl-oil-100", "absurd", False, False),
        _result("ctrl-steak-160", "normal", True, True),
        _result("ctrl-banana-126", "normal", True, True),
    ]


def test_conclude_passes_when_all_ground_truth_holds(capsys) -> None:
    assert probe.conclude(_full_pass()) is True
    assert "GATE_SAFE" in capsys.readouterr().out


def test_conclude_fails_on_gray_false_kill(capsys) -> None:
    rows = _full_pass()
    rows[4] = _result("omelet-piece-55", "gray", True, False)
    assert probe.conclude(rows) is False
    assert "GATE_NEEDS_ADJUSTMENT" in capsys.readouterr().out


def test_conclude_fails_on_absurd_leak(capsys) -> None:
    rows = _full_pass()
    rows[6] = _result("ctrl-steak-030", "absurd", False, True)
    assert probe.conclude(rows) is False
    assert "mixed" in capsys.readouterr().out


def test_conclude_fails_on_normal_miss(capsys) -> None:
    rows = _full_pass()
    rows[9] = _result("ctrl-steak-160", "normal", True, False)
    assert probe.conclude(rows) is False
    assert "mixed" in capsys.readouterr().out


def test_probe_uses_catalog_v1() -> None:
    assert probe.CATALOG_V1_PATH == ROOT / "data" / "fdc" / "catalog-v1.sqlite"
    assert probe.K == 5
    assert probe.THRESHOLD == 0.6
