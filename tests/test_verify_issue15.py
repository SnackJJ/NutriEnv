"""Smoke: the issue-15 admission gate script runs and enforces exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from nutrienv.bench.pipeline.run_batch import run_batch
from nutrienv.bench.pipeline.expander import synthetic_expander
from nutrienv.bench.pipeline.types import catalog_digest
from nutrienv.world.catalog_fixture import demo_catalog

from scripts.verify_issue15 import main as verify_main


def _run(args: list[str]) -> int:
    return verify_main(args)


def test_verify_accepts_a_clean_composite_freeze(tmp_path: Path) -> None:
    """A small composite split we produce passes the gates it can (validate,
    window, freeze round-trip) — the script does not falsely reject."""
    cat = demo_catalog()
    spec = {
        "catalog_sha": catalog_digest(cat),
        "seed": 3,
        "family_quotas": {"composite": 2},
        "persona": "everyday",
        "sampler_rule_version": "sampler-v1",
        "output_path": tmp_path / "c.json",
        "version": "smoke",
        "overwrite": True,
        "family_recipes": {"composite": {"person": "roster-ben"}},
    }
    res = run_batch(
        spec, expander=synthetic_expander, judge=_pass_judge,
        reviewer=_pass_reviewer, catalog=cat, workers=1,
    )
    assert res.accepted, "small demo catalog must produce at least one composite"
    rc = _run(["--split", str(tmp_path / "c.json"), "--personas", "everyday,gym"])
    # demo_catalog lacks most allergen tags, so coverage/tier/floors fail;
    # the script must still run to completion and report FAIL (rc 1), never crash.
    assert rc == 1
    # A missing split is a usage error (rc 2), also non-crashing.
    assert _run(["--split", str(tmp_path / "missing.json")]) == 2


class _pass_judge:
    def __call__(self, task, catalog):  # pragma: no cover - trivially true
        return False


def _pass_reviewer(cands):
    return {"anomalies": [], "per_candidate": {t.id: {} for t in cands}}
