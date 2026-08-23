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


def _v05_payload_copy(tmp_path: Path, *, with_sha: bool) -> Path:
    payload = json.loads(Path(V05_GOLD).read_text())
    if not with_sha:
        payload.pop("catalog_sha256", None)
    split = tmp_path / "copy.json"
    split.write_text(json.dumps(payload), encoding="utf-8")
    return split


def test_override_without_recorded_sha_is_refused(tmp_path: Path) -> None:
    """A no-SHA split cannot be verified against any override: fail closed
    instead of trusting the file (demo fallback stays out of the picture)."""
    import contextlib
    import io

    split = _v05_payload_copy(tmp_path, with_sha=False)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = vi.main(
            ["--split", str(split), "--catalog", "data/fdc/catalog-v2.sqlite"]
        )
    out = buffer.getvalue()
    assert rc == 2
    assert "no catalog_sha256" in out
    assert "Traceback" not in out


def test_non_sqlite_catalog_is_refused(tmp_path: Path) -> None:
    """Both catalog paths require a .sqlite file: a hash-matching text file
    must not silently load the demo fixture."""
    import contextlib
    import io

    catalog_txt = tmp_path / "catalog.txt"
    catalog_txt.write_bytes(b"not a sqlite database at all")
    digest = hashlib.sha256(catalog_txt.read_bytes()).hexdigest()
    payload = json.loads(Path(V05_GOLD).read_text())
    payload["catalog"] = str(catalog_txt)
    payload["catalog_sha256"] = digest
    split = tmp_path / "txt.json"
    split.write_text(json.dumps(payload), encoding="utf-8")

    for override in (None, str(catalog_txt)):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            argv = ["--split", str(split)]
            if override:
                argv += ["--catalog", override]
            rc = vi.main(argv)
        out = buffer.getvalue()
        assert rc == 2, (override, out)
        assert ".sqlite" in out
        assert "Traceback" not in out


def test_tampered_split_manifest_is_refused_at_entry(tmp_path: Path) -> None:
    """A split whose recorded sha no longer matches its catalog bytes cannot
    enter the gates at all (rc 2, clean diagnostic) -- the round-trip gate's
    own FAIL row for this case is pinned above via the direct gate call."""
    import contextlib
    import io

    split = _consistent_real_catalog_split(tmp_path)
    payload = json.loads(split.read_text())
    tampered_catalog = tmp_path / "tampered.sqlite"
    raw = Path("data/fdc/catalog-v2.sqlite").read_bytes()
    tampered_catalog.write_bytes(raw[:-1] + bytes([raw[-1] ^ 0xFF]))
    payload["catalog"] = str(tampered_catalog)
    split.write_text(json.dumps(payload), encoding="utf-8")

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = vi.main(["--split", str(split)])
    out = buffer.getvalue()
    assert rc == 2
    assert "sha256 mismatch" in out
    assert "Traceback" not in out


def test_round_trip_fails_when_output_manifest_sha_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A frozen manifest whose catalog field points at a byte-different
    sqlite copy while keeping the OLD recorded sha must make the round-trip
    gate itself FAIL with SHA-mismatch evidence -- injected into the gate via
    a tampering freeze_tasks wrapper, never asserted through a side door.

    Also pins the corrupt-sqlite rc-2/no-traceback contract for the entry
    loader (fix-round-3 Medium)."""
    import contextlib
    import io
    import sqlite3

    split = _consistent_real_catalog_split(tmp_path)
    loaded = vi._load_verified(split, None)
    result = vi.gate_freeze_round_trip(loaded.tasks, loaded)
    assert result.passed, result.evidence

    tampered_catalog = tmp_path / "tampered.sqlite"
    raw = Path("data/fdc/catalog-v2.sqlite").read_bytes()
    tampered_catalog.write_bytes(raw[:-1] + bytes([raw[-1] ^ 0xFF]))

    real_freeze = vi.freeze_tasks

    def _tampering_freeze(tasks, *, catalog, output_path, **kwargs):
        payload, path = real_freeze(
            tasks, catalog=catalog, output_path=output_path, **kwargs
        )
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        doc["catalog"] = str(tampered_catalog)  # old sha kept: identity broken
        Path(path).write_text(json.dumps(doc), encoding="utf-8")
        return payload, path

    with monkeypatch.context() as m:
        m.setattr(vi, "freeze_tasks", _tampering_freeze)
        tampered = vi.gate_freeze_round_trip(loaded.tasks, loaded)
    assert not tampered.passed
    assert "sha256 mismatch" in tampered.evidence

    # And through main: the same tampering surfaces as the FAIL row, rc 1.
    buffer = io.StringIO()
    real_load = vi._load_verified
    with monkeypatch.context() as m:
        m.setattr(vi, "freeze_tasks", _tampering_freeze)
        # Entry keeps loading the pristine input split; only the gate's
        # reload sees the tampered temp manifest.
        m.setattr(
            vi,
            "_load_verified",
            lambda split_path, override=None: (
                loaded
                if str(split_path) == V05_GOLD
                else real_load(split_path, override)
            ),
        )
        with contextlib.redirect_stdout(buffer):
            rc = vi.main(["--split", V05_GOLD])
    out = buffer.getvalue()
    assert rc == 1
    assert "FAIL  freeze_round_trip" in out
    assert "sha256 mismatch" in out


def test_corrupt_sqlite_catalog_returns_2_without_traceback(
    tmp_path: Path,
) -> None:
    """A *.sqlite file whose SHA matches but whose content is not a database
    must produce a concise rc-2 usage diagnostic, never a traceback."""
    import contextlib
    import io

    corrupt = tmp_path / "corrupt.sqlite"
    body = b"not a sqlite database at all"
    corrupt.write_bytes(body)
    payload = {
        "catalog": str(corrupt),
        "catalog_sha256": hashlib.sha256(body).hexdigest(),
        "items": [
            {
                "id": "x",
                "family": "log",
                "query": "I ate rice.",
                "situations": [],
                "persona": "everyday",
                "s0": {"profile": {"user_id": "u"}, "ledger": []},
                "oracle": {},
            }
        ],
    }
    split = tmp_path / "split.json"
    split.write_text(json.dumps(payload), encoding="utf-8")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = vi.main(["--split", str(split)])
    out = buffer.getvalue()
    assert rc == 2
    assert out.startswith("error:")
    assert "Traceback" not in out
