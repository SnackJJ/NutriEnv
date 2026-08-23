#!/usr/bin/env python3
"""Issue 15 admission gate: verify a frozen candidate split against the 14
assertions on a single command.

    .venv/bin/python scripts/verify_issue15.py --split /path/to/split.json
    .venv/bin/python scripts/verify_issue15.py --split ... --catalog data/fdc/catalog-v2.sqlite
    .venv/bin/python scripts/verify_issue15.py --split ... --personas everyday,cut,gym

Catalog identity: by default the split's OWN recorded ``catalog`` field and
``catalog_sha256`` select and verify the catalog (file must exist, digest must
match) before any gate runs — gates never see a silently-substituted catalog.
An explicit ``--catalog`` override fails closed unless its bytes hash to the
split's recorded digest.

Gates (all from quality_gates / split / validator):
  1. load_split succeeds (reload-valid situations, catalog attached)
  2. per-item validate_draft == []
  3. window_leaks == ()            (recommend/composite queries stay number-free)
  4. recommend_coverage: no missing personas (--personas) or catalog allergen tags
  5. evaluate_tier_coverage: every EVALUATE_TIERS floor met
  6. leftover_floor count >= 24
  7. situation_floors: unfit >= 8, constrained >= 8
  8. freeze -> reload round trip in a private temp dir: the frozen manifest
     resolves ITS OWN recorded catalog, every task reloads, and ordered
     normalized task payloads are identical before and after.

Exit 0 with a compact per-gate PASS/FAIL table when every gate passes; exit 1
with the failing gates and their evidence otherwise; exit 2 with one concise
diagnostic for usage errors (missing split, malformed JSON/schema, catalog
identity mismatch). The source split is never modified; temp artifacts are
cleaned up on every path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nutrienv.bench.pipeline.freezer import freeze_tasks, task_to_item  # noqa: E402
from nutrienv.bench.quality_gates import (  # noqa: E402
    evaluate_tier_coverage,
    evaluate_unfits,
    leftover_floor,
    recommend_coverage,
    situation_floors,
    window_leaks,
)
from nutrienv.bench.split import load_split  # noqa: E402
from nutrienv.bench.validator import validate_draft  # noqa: E402
from nutrienv.world.catalog_store import load_catalog  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class GateResult:
    """One admission gate's verdict plus the evidence behind it."""

    name: str
    passed: bool
    evidence: str


@dataclass(frozen=True)
class LoadedSplit:
    """A reloaded candidate split plus its verified catalog identity."""

    tasks: tuple
    catalog_object: object
    catalog_field: str | None
    catalog_sha256: str | None


def _format_reasons(rows, limit: int = 6) -> str:
    s = ", ".join(str(x) for x in rows[:limit])
    if len(rows) > limit:
        s += f", … (+{len(rows) - limit})"
    return s or "—"


def _resolve_repo_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else _ROOT / path


def _require_sqlite(catalog_path: Path) -> None:
    """``load_catalog`` silently falls back to the demo fixture for a missing
    path, so every caller validates existence and extension first."""
    if catalog_path.suffix != ".sqlite":
        raise ValueError(
            f"catalog must be a .sqlite file, got: {catalog_path}"
        )


def _load_verified(split_path: Path, catalog_override: str | None) -> LoadedSplit:
    """Attach the right catalog to the split and verify its identity.

    Without ``catalog_override`` the split's recorded ``catalog`` field selects
    the file, which must exist and hash to the recorded ``catalog_sha256``
    before ``load_split`` runs (so the demo-catalog fallback can never mask a
    broken manifest). With an override, the override's bytes must hash to the
    recorded digest or the run refuses to judge the split against foreign data.
    Raises ValueError/FileNotFoundError/json.JSONDecodeError on malformed
    inputs; callers translate that into a usage failure.
    """
    payload = json.loads(Path(split_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("split payload must be a JSON object")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("split has no items")
    field = payload.get("catalog")
    sha = payload.get("catalog_sha256")

    if catalog_override is not None:
        # An override is only verifiable against a recorded digest: without
        # one there is nothing to compare, so refuse rather than trust it.
        if not isinstance(sha, str) or not sha:
            raise ValueError(
                "split records no catalog_sha256; an explicit --catalog "
                "override cannot be verified against it"
            )
        override_path = _resolve_repo_path(catalog_override)
        if not override_path.is_file():
            raise FileNotFoundError(f"--catalog not found: {override_path}")
        _require_sqlite(override_path)
        digest = hashlib.sha256(override_path.read_bytes()).hexdigest()
        if digest != sha:
            raise ValueError(
                f"catalog identity mismatch: --catalog {override_path} "
                f"sha256 {digest} != split-recorded {sha}"
            )
        return LoadedSplit(
            tasks=tuple(load_split(split_path, catalog=load_catalog(override_path))),
            catalog_object=load_catalog(override_path),
            catalog_field=catalog_override,
            catalog_sha256=digest,
        )

    if not isinstance(field, str) or not field:
        raise ValueError("split records no catalog field to verify")
    if not isinstance(sha, str) or not sha:
        raise ValueError("split records no catalog_sha256 to verify")
    catalog_path = _resolve_repo_path(field)
    if not catalog_path.is_file():
        raise FileNotFoundError(f"split catalog not found: {catalog_path}")
    _require_sqlite(catalog_path)
    digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    if digest != sha:
        raise ValueError(
            f"split catalog sha256 mismatch: file={digest} split={sha}"
        )
    catalog = load_catalog(catalog_path)
    return LoadedSplit(
        tasks=tuple(load_split(split_path, catalog=catalog)),
        catalog_object=catalog,
        catalog_field=field,
        catalog_sha256=sha,
    )


def gate_validate_draft(tasks) -> GateResult:
    bad = [(t.id, v) for t in tasks if (v := validate_draft(t))]
    return GateResult(
        "validate_draft",
        not bad,
        "0 issues" if not bad else _format_reasons(bad),
    )


def gate_window_leaks(tasks) -> GateResult:
    leaks = window_leaks(tasks)
    return GateResult("window_leaks", not leaks, _format_reasons(leaks))


def gate_persona_allergen(tasks, personas) -> GateResult:
    coverage = recommend_coverage(tasks, personas=personas, allergen_tags=None)
    passed = not coverage.missing_personas and not coverage.missing_allergens
    return GateResult(
        "persona_x_allergen",
        passed,
        f"missing_personas={coverage.missing_personas or '—'} "
        f"missing_allergens={coverage.missing_allergens or '—'}",
    )


def gate_evaluate_tiers(tasks) -> GateResult:
    tier_report = evaluate_tier_coverage(tasks)
    return GateResult(
        "evaluate_tiers",
        not tier_report.missing,
        f"counts={tier_report.counts} missing={tier_report.missing or '—'}",
    )


def gate_leftover_floor(tasks) -> GateResult:
    leftover_report = leftover_floor(tasks)
    passed = leftover_report.count >= leftover_report.minimum
    return GateResult(
        "leftover_floor",
        passed,
        f"{leftover_report.count} / min {leftover_report.minimum}",
    )


def gate_situation_floors(tasks) -> GateResult:
    floors_report = situation_floors(tasks)
    passed = (
        floors_report.unfit_count >= floors_report.unfit_minimum
        and floors_report.constrained_count >= floors_report.constrained_minimum
    )
    return GateResult(
        "situation_floors",
        passed,
        f"unfit {floors_report.unfit_count}/{floors_report.unfit_minimum} "
        f"constrained {floors_report.constrained_count}/{floors_report.constrained_minimum}",
    )


def gate_freeze_round_trip(tasks, loaded: LoadedSplit) -> GateResult:
    """Freeze into a private temp dir preserving the input's VERIFIED catalog
    identity, reload WITHOUT injecting a catalog (the frozen manifest must
    resolve its own), then compare ordered normalized task payloads."""
    with tempfile.TemporaryDirectory(prefix="verify-issue15-") as tmp_dir:
        target = Path(tmp_dir) / "round-trip.json"
        try:
            _payload, _path = freeze_tasks(
                list(tasks),
                catalog=loaded.catalog_object,
                catalog_field=loaded.catalog_field or None,
                catalog_sha=loaded.catalog_sha256,
                output_path=target,
                overwrite=True,
            )
            # No catalog injection, full identity verification: the frozen
            # manifest's recorded sha must match the catalog its own field
            # points at, or the artifact does not resolve on its own terms.
            reloaded = _load_verified(_path, None)
        except Exception as exc:  # noqa: BLE001 — report, don't crash the table
            return GateResult(
                "freeze_round_trip", False, f"{type(exc).__name__}: {str(exc)[:120]}"
            )
    same_content = [task_to_item(t) for t in tasks] == [
        task_to_item(t) for t in reloaded.tasks
    ]
    draft_clean = not any(validate_draft(t) for t in reloaded.tasks)
    evidence = (
        f"{len(reloaded.tasks)}/{len(tasks)} reloaded from own verified "
        f"manifest, content identical={same_content}, validate clean={draft_clean}"
    )
    return GateResult(
        "freeze_round_trip", same_content and draft_clean, evidence
    )


def run_gates(loaded: LoadedSplit, personas) -> list[GateResult]:
    results = [
        GateResult(
            "load_split",
            True,
            f"{len(loaded.tasks)} tasks reload-valid",
        ),
        gate_validate_draft(loaded.tasks),
        gate_window_leaks(loaded.tasks),
        gate_persona_allergen(loaded.tasks, personas),
        gate_evaluate_tiers(loaded.tasks),
        gate_leftover_floor(loaded.tasks),
        gate_situation_floors(loaded.tasks),
        gate_freeze_round_trip(loaded.tasks, loaded),
    ]
    return results


def render(gates: list[GateResult]) -> None:
    print("\nissue-15 admission gates:")
    for gate in gates:
        marker = "PASS" if gate.passed else "FAIL"
        print(f"  {marker:4}  {gate.name:18} {gate.evidence}")
    all_ok = all(gate.passed for gate in gates)
    print("RESULT:", "PASS" if all_ok else "FAIL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True, help="frozen split to verify")
    parser.add_argument(
        "--catalog",
        type=str,
        default=None,
        help=(
            "optional catalog override; defaults to the split's own recorded "
            "catalog (verified against its recorded sha256)"
        ),
    )
    parser.add_argument(
        "--personas", default="everyday,cut,gym", help="comma-separated personas to require"
    )
    args = parser.parse_args(argv)

    if not args.split.is_file():
        print(f"error: split not found: {args.split}")
        return 2

    try:
        loaded = _load_verified(args.split, args.catalog)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        sqlite3.Error,
    ) as exc:
        print(f"error: cannot load split: {exc}")
        return 2

    personas = tuple(p.strip() for p in args.personas.split(",") if p.strip())
    print(f"families: {dict(Counter(t.family for t in loaded.tasks))}")

    gates = run_gates(loaded, personas)
    render(gates)
    return 0 if all(gate.passed for gate in gates) else 1


if __name__ == "__main__":
    raise SystemExit(main())
