"""Leaf IO: dotenv does not clobber env; bench no longer imports harness."""

from __future__ import annotations

import os
from pathlib import Path

from nutrienv.harness.react import load_dotenv_keys as react_load_dotenv_keys
from nutrienv.io.dotenv import load_dotenv_keys


def test_grams_gate_source_does_not_import_harness() -> None:
    source = Path("src/nutrienv/bench/grams_gate.py").read_text(encoding="utf-8")
    assert "nutrienv.harness" not in source


def test_load_dotenv_keys_does_not_override_existing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NUTRIENV_DOTENV_TEST_FOO", "keep")
    monkeypatch.delenv("NUTRIENV_DOTENV_TEST_BAR", raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "NUTRIENV_DOTENV_TEST_FOO=new\nNUTRIENV_DOTENV_TEST_BAR=added\n",
        encoding="utf-8",
    )
    load_dotenv_keys(path)
    assert os.environ["NUTRIENV_DOTENV_TEST_FOO"] == "keep"
    assert os.environ["NUTRIENV_DOTENV_TEST_BAR"] == "added"


def test_react_reexports_same_dotenv_loader() -> None:
    assert react_load_dotenv_keys is load_dotenv_keys
