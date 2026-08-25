"""ADR 0017 mill single-item CLI: synthetic tracer + payload shape.

Live network is never exercised here; the CLI contract is pinned offline.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "generate_one_cli.py"

CATALOG = ROOT / "data" / "fdc" / "catalog-v2.sqlite"


def _run(tmp_path: Path, *argv: str) -> tuple[int, dict]:
    out = tmp_path / "item.json"
    proc = subprocess.run(
        [sys.executable, str(CLI), *argv, "--output", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    return proc.returncode, payload


@pytest.mark.skipif(not CATALOG.is_file(), reason="catalog-v2 is not present")
def test_synthetic_log_seed_zero_writes_task_payload(tmp_path: Path) -> None:
    code, payload = _run(
        tmp_path, "--synthetic", "--seed", "0", "--amount-path", "named_measure"
    )
    assert code == 0
    assert payload["status"] == "accepted"
    assert payload["task_id"] == "one-log-0000"
    assert payload["family"] == "log"
    assert payload["oracle_ledger"][0]["food_id"]
    assert payload["oracle_ledger"][0]["grams"] > 0


@pytest.mark.skipif(not CATALOG.is_file(), reason="catalog-v2 is not present")
def test_synthetic_all_three_amount_paths_accept_or_reject_cleanly(
    tmp_path: Path,
) -> None:
    for path in ("named_measure", "explicit_grams", "unspecified"):
        code, payload = _run(
            tmp_path, "--synthetic", "--seed", "0", "--amount-path", path
        )
        assert code in (0, 1)
        assert payload["status"] in {"accepted", "rejected"}
        if payload["status"] == "rejected":
            assert payload["reason"]


def test_cli_rejects_unknown_person_and_bad_amount_path() -> None:
    bad_person = subprocess.run(
        [sys.executable, str(CLI), "--synthetic", "--person", "roster-nope"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad_person.returncode == 2
    bad_path = subprocess.run(
        [sys.executable, str(CLI), "--synthetic", "--amount-path", "bogus"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad_path.returncode == 2


@pytest.mark.skipif(not CATALOG.is_file(), reason="catalog-v2 is not present")
def test_synthetic_evaluate_tier_single_accepts_or_rejects_cleanly(tmp_path: Path) -> None:
    code, payload = _run(
        tmp_path,
        "--synthetic",
        "--family",
        "evaluate",
        "--seed",
        "4",
        "--tier",
        "single",
        "--amount-path",
        "named_measure",
    )
    assert code in (0, 1)
    assert payload["status"] in {"accepted", "rejected"}
    if payload["status"] == "accepted":
        assert payload["family"] == "evaluate"
        assert "task_id" in payload
