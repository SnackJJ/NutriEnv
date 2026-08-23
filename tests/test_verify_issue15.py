"""Tests: the issue-15 admission gate script (exit codes, named rows,
catalog identity, round-trip content equality, temp cleanup)."""

from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path

import pytest

from nutrienv.bench.pipeline.expander import synthetic_expander
from nutrienv.bench.pipeline.run_batch import run_batch
from nutrienv.bench.pipeline.types import catalog_digest

import scripts.verify_issue15 as vi

V05_GOLD = "data/splits/archive/v0.5-gold.json"


class _pass_judge:
    def __call__(self, task, catalog):  # pragma: no cover - trivially true
        return False


def _pass_reviewer(cands):
    return {"anomalies": [], "per_candidate": {t.id: {} for t in cands}}


def _composite_demo_split(tmp_path: Path) -> Path:
    """A small composite split frozen against the demo catalog object."""
    from nutrienv.world.catalog_fixture import demo_catalog

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
        spec,
        expander=synthetic_expander,
        judge=_pass_judge(),
        reviewer=_pass_reviewer,
        catalog=cat,
        workers=1,
    )
    assert res.accepted, "small demo catalog must produce at least one composite"
    return tmp_path / "c.json"


def test_missing_split_returns_2() -> None:
    assert vi.main(["--split", "no/such/split.json"]) == 2


def test_malformed_json_returns_2_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    split = tmp_path / "bad.json"
    split.write_text("{not json", encoding="utf-8")
    rc = vi.main(["--split", str(split)])
    out = capsys.readouterr().out
    assert rc == 2
    assert out.startswith("error:")
    assert "Traceback" not in out


def test_empty_items_split_returns_2(tmp_path: Path) -> None:
    split = tmp_path / "empty.json"
    split.write_text(json.dumps({"items": []}), encoding="utf-8")
    rc = vi.main(["--split", str(split)])
    assert rc == 2


def test_manifest_catalog_identity_mismatch_is_a_usage_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """The demo-object split records catalog-v1 with a demo digest; the gate
    must refuse to judge it against the recorded-but-foreign catalog file."""
    split = _composite_demo_split(tmp_path)
    payload = json.loads(split.read_text())
    assert payload["catalog"] == "data/fdc/archive/catalog-v1.sqlite"
    rc = vi.main(["--split", str(split)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "sha256 mismatch" in out or "not found" in out
    assert "Traceback" not in out


def test_named_rows_on_v05_gold_uses_its_own_catalog(
    capsys: pytest.CaptureFixture,
) -> None:
    """v0.5-gold verifies against its OWN recorded catalog: validate_draft is
    clean (no spurious failures), tier/unfit floors fail honestly, rc 1."""
    rc = vi.main(["--split", V05_GOLD])
    out = capsys.readouterr().out
    assert rc == 1
    assert "PASS  load_split" in out
    assert "PASS  validate_draft" in out
    assert "FAIL  evaluate_tiers" in out
    assert "FAIL  situation_floors" in out
    assert "RESULT: FAIL" in out
    assert "Traceback" not in out


def test_rc0_when_every_gate_passes(tmp_path: Path, monkeypatch) -> None:
    """Exit-code aggregation and rendering: all gates green -> rc 0."""
    monkeypatch.setattr(
        vi,
        "run_gates",
        lambda loaded, personas: [
            vi.GateResult("load_split", True, "ok"),
            vi.GateResult("validate_draft", True, "0 issues"),
            vi.GateResult("window_leaks", True, "—"),
            vi.GateResult("persona_x_allergen", True, "—"),
            vi.GateResult("evaluate_tiers", True, "—"),
            vi.GateResult("leftover_floor", True, "24 / min 24"),
            vi.GateResult("situation_floors", True, "unfit 8/8 constrained 8/8"),
            vi.GateResult("freeze_round_trip", True, "content identical=True"),
        ],
    )
    rc = vi.main(["--split", V05_GOLD])
    assert rc == 0


def _consistent_real_catalog_split(tmp_path: Path) -> Path:
    """A composite split whose recorded catalog field+sha match the real
    catalog-v2 file, so the manifest is verifiable end to end."""
    from nutrienv.world.catalog_store import load_catalog

    catalog_path = Path("data/fdc/catalog-v2.sqlite")
    cat = load_catalog(catalog_path)
    spec = {
        "catalog": str(catalog_path),
        "catalog_sha": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "seed": 5,
        "family_quotas": {"composite": 1},
        "persona": "everyday",
        "sampler_rule_version": "sampler-v1",
        "output_path": tmp_path / "real.json",
        "version": "smoke-real",
        "overwrite": True,
    }
    res = run_batch(
        spec,
        expander=synthetic_expander,
        judge=_pass_judge(),
        reviewer=_pass_reviewer,
        catalog=cat,
        workers=1,
    )
    assert res.accepted
    return tmp_path / "real.json"


def test_consistent_manifest_round_trip_passes_and_cleans_up(
    tmp_path: Path,
) -> None:
    """Positive path: an internally-consistent manifest loads without an
    override, the freeze round-trip passes content equality, and no
    verify-issue15 temp dirs are left behind."""
    split = _consistent_real_catalog_split(tmp_path)
    loaded = vi._load_verified(split, None)
    result = vi.gate_freeze_round_trip(loaded.tasks, loaded)
    assert result.passed, result.evidence
    assert "content identical=True" in result.evidence
    assert glob.glob("/tmp/verify-issue15-*") == []

    # And the whole script accepts it as far as floors allow: validate and
    # round-trip rows PASS even though the coverage/tier floors fail honestly.
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = vi.main(["--split", str(split), "--personas", "everyday"])
    out = buffer.getvalue()
    assert rc == 1  # tier/unfit/coverage floors fail on a 1-item split
    assert "PASS  validate_draft" in out
    assert "PASS  freeze_round_trip" in out
