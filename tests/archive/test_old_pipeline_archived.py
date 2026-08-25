"""Old v1.0 generation scripts are archived; the ADR 0017 mill owns generation.

The four scripts that drove the old ``{items:[{food, expression}]}`` contract
(generate_batch / phase6_generate / run_pilot_20 / smoke_expander_models) are
no longer on the formal path. The new pipeline is the ADR 0017 mill
(``generate_one``, ``{query, foods}``), so these scripts live under
``scripts/archive/`` and must not import from the live ``scripts/`` module
resolution path.

This is a reversal test in the archive convention: it asserts the old entry
points are gone from the live path, rather than deleting their historical
coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

OLD_SCRIPTS = (
    "generate_batch",
    "phase6_generate",
    "run_pilot_20",
    "smoke_expander_models",
)


def test_old_generation_scripts_are_not_on_the_live_path() -> None:
    live = ROOT / "scripts"
    archive = live / "archive"
    for name in OLD_SCRIPTS:
        assert (archive / f"{name}.py").is_file(), f"{name} should be archived"
        assert not (live / f"{name}.py").exists(), f"{name} must not stay live"


def test_live_scripts_do_not_import_them_by_module_name() -> None:
    live = ROOT / "scripts"
    for path in live.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in OLD_SCRIPTS:
            assert (
                f"import {name}" not in text
            ), f"{path.name} still imports archived {name}"


def test_new_entry_point_exists() -> None:
    # The ADR 0017 mill single-item entry is the replacement surface.
    assert (ROOT / "src" / "nutrienv" / "bench" / "pipeline" / "generate_one.py").is_file()
    generation = (ROOT / "scripts" / "generate_one_cli.py")
    assert generation.is_file(), "new generate_one CLI must exist on the live path"


def _archive_importable_regression_test() -> None:
    """Kept as an explicit doc-marker: archived scripts are import-checked via
    their subprocess-tested payloads in the new pipeline tests, not by
    importing this module path at runtime. pytest exercises them through
    ``tests/archive/test_pilot_20.py`` (historical) and the new mill tests."""
    pass
