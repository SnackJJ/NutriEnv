#!/usr/bin/env python3
"""Issue 15 admission gate: verify a frozen candidate split against the 14
assertions on a single command.

    .venv/bin/python scripts/verify_issue15.py --split /path/to/split.json
    .venv/bin/python scripts/verify_issue15.py --split ... --catalog data/fdc/catalog-v2.sqlite
    .venv/bin/python scripts/verify_issue15.py --split ... --personas everyday,cut,gym --allergens

Runs (all from quality_gates / split / validator):
  1. load_split succeeds (reload-valid situations, catalog attached)
  2. per-item validate_draft == []
  3. window_leaks == ()            (recommend/composite queries stay number-free)
  4. recommend_coverage: no missing personas (--personas; default each task's
     `Persona` module choice is not used — pass explicit personas) and no missing
     catalog allergen tags
  5. evaluate_tier_coverage: every EVALUATE_TIERS floor met
  6. leftover_floor count >= 24
  7. situation_floors: unfit >= 8, constrained >= 8
  8. freeze_tasks -> load_split round-trip: same task count, validate == []
     (proves the freeze path is safe to ship)

Exit 0 with a compact per-gate PASS/FAIL table when every gate passes; exit 1
with the failing gates and their evidence otherwise. The frozen split itself is
never modified. Designed to be the admission ticket's acceptance tool and is
safe to run repeatedly on the same split.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nutrienv.bench.quality_gates import (  # noqa: E402
    constrained_recommends,
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


def _format_reasons(rows, limit: int = 6) -> str:
    s = ", ".join(str(x) for x in rows[:limit])
    if len(rows) > limit:
        s += f", … (+{len(rows) - limit})"
    return s or "—"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True, help="frozen split to verify")
    parser.add_argument("--catalog", type=str, default="data/fdc/catalog-v2.sqlite")
    parser.add_argument(
        "--personas", default="everyday,cut,gym", help="comma-separated personas to require"
    )
    args = parser.parse_args(argv)

    if not args.split.is_file():
        print(f"error: split not found: {args.split}")
        return 2

    catalog = load_catalog(args.catalog)
    tasks = load_split(args.split, catalog=catalog)

    gates = {}

    # 1 — reload-valid + family tally
    gates["load_split"] = ("PASS", f"{len(tasks)} tasks reload-valid")
    print(f"families: {dict(Counter(t.family for t in tasks))}")

    # 2 — validate_draft
    bad = [(t.id, v) for t in tasks if (v := validate_draft(t))]
    gates["validate_draft"] = (
        "PASS" if not bad else "FAIL",
        "0 issues" if not bad else _format_reasons(bad),
    )

    # 3 — window_leaks
    leaks = window_leaks(tasks)
    gates["window_leaks"] = ("PASS" if not leaks else "FAIL", _format_reasons(leaks))

    # 4 — persona × allergen coverage
    personas = tuple(p.strip() for p in args.personas.split(",") if p.strip())
    rc = recommend_coverage(tasks, personas=personas, allergen_tags=None)
    cov_ok = not rc.missing_personas and not rc.missing_allergens
    gates["persona_x_allergen"] = (
        "PASS" if cov_ok else "FAIL",
        f"missing_personas={rc.missing_personas or '—'} "
        f"missing_allergens={rc.missing_allergens or '—'}",
    )

    # 5 — evaluate tier floors
    tc = evaluate_tier_coverage(tasks)
    tier_ok = not tc.missing
    gates["evaluate_tiers"] = (
        "PASS" if tier_ok else "FAIL",
        f"counts={tc.counts} missing={tc.missing or '—'}",
    )

    # 6 — leftover floor
    lf = leftover_floor(tasks)
    leftover_ok = lf.count >= lf.minimum
    gates["leftover_floor"] = (
        "PASS" if leftover_ok else "FAIL",
        f"{lf.count} / min {lf.minimum}",
    )

    # 7 — situation floors
    sf = situation_floors(tasks)
    floors_ok = sf.unfit_count >= sf.unfit_minimum and sf.constrained_count >= sf.constrained_minimum
    gates["situation_floors"] = (
        "PASS" if floors_ok else "FAIL",
        f"unfit {sf.unfit_count}/{sf.unfit_minimum} "
        f"constrained {sf.constrained_count}/{sf.constrained_minimum}",
    )

    # 8 — freeze -> load round-trip safety
    from nutrienv.bench.pipeline.freezer import freeze_tasks  # noqa: E402

    try:
        _payload, _path = freeze_tasks(
            tasks,
            catalog=catalog,
            output_path=Path("/tmp") / f"verify-{args.split.stem}.gold.json",
            overwrite=True,
        )
        reloaded = load_split(_path, catalog=catalog)
        rt_ok = len(reloaded) == len(tasks) and not any(
            validate_draft(t) for t in reloaded
        )
        gates["freeze_round_trip"] = (
            "PASS" if rt_ok else "FAIL",
            f"{len(reloaded)}/{len(tasks)} reloaded, validate clean={rt_ok}",
        )
    except Exception as exc:  # noqa: BLE001 — report, don't crash the gate table
        gates["freeze_round_trip"] = ("FAIL", f"{type(exc).__name__}: {str(exc)[:120]}")

    print("\nissue-15 admission gates:")
    all_ok = True
    for name, (status, evidence) in gates.items():
        marker = "PASS" if status == "PASS" else "FAIL"
        if status != "PASS":
            all_ok = False
        print(f"  {marker:4}  {name:18} {evidence}")
    print("RESULT:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())