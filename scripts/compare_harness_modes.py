#!/usr/bin/env python3
"""Side-by-side comparison of two benchmark reports run under different harness modes.

Answers one question: for the same split, the same model and the same scorer, does the
native function-calling harness (``--contract native-tools``) do better or worse than the
text ReAct loop (``--contract text-json``)?

The two runs must differ in exactly one thing — the harness. If the split or the model
does not match, the script says so and refuses to print a delta: that delta would be
measuring the setup, not the harness.

    .venv/bin/python scripts/eval_benchmark_suite.py --contract text-json \\
        --out reports/mode_react.json
    .venv/bin/python scripts/eval_benchmark_suite.py --contract native-tools \\
        --out reports/mode_toolcall.json
    .venv/bin/python scripts/compare_harness_modes.py \\
        reports/mode_react.json reports/mode_toolcall.json

Reports written before ``contract`` was recorded are labelled legacy and are still
comparable to a fresh run, with a warning.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.harness.prompt_freeze import effective_fingerprint  # noqa: E402

DESCRIPTION = "Side-by-side comparison of two harness-mode reports."
# Reports written before 2026-09-21 carry `harness_mode` with `react` / `tool_call`.
LEGACY_MODES = {"react": "text-json", "tool_call": "native-tools"}
UNRECORDED_MODE = "text-json (legacy: contract not recorded)"


def _report_int(report: dict[str, Any], key: str) -> int:
    """One integer field of a report, validated by name.

    A report is a file someone else may have written: a missing or non-numeric field must name
    itself, not surface as `ValueError: invalid literal for int()` with no key.
    """
    value = report.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return round(value)
    raise SystemExit(f"{key} in {report.get('split', '?')} is not a number: {value!r}")

# Metrics copied straight out of the report, with the label used in the table.
_OVERALL_METRICS: tuple[tuple[str, str], ...] = (
    ("passed_tasks", "passed"),
    ("total_tasks", "total"),
    ("pass_rate_pct", "pass %"),
    ("clean_pass_rate_pct", "clean pass % (void excluded)"),
    ("void_count", "void tasks"),
    ("overall_avg_steps", "avg steps"),
    ("total_invalid_tool_calls", "invalid tool calls"),
    ("total_allergen_violations", "allergen violations"),
    ("overall_avg_tokens_per_task", "avg tokens/task"),
    ("overall_avg_time_seconds", "avg seconds/task"),
)


def load_report(path: Path) -> dict[str, Any]:
    """Read one report JSON, failing loudly rather than comparing a truncated file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"report not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"report is not valid JSON: {path} ({exc})") from None
    if not isinstance(data, dict) or "tasks" not in data:
        raise SystemExit(f"not an eval report (no tasks[]): {path}")
    return data


def mode_of(report: dict[str, Any]) -> str:
    recorded = report.get("contract") or report.get("harness_mode")
    if recorded is None:
        return UNRECORDED_MODE
    return LEGACY_MODES.get(str(recorded), str(recorded))


def split_of(report: dict[str, Any]) -> str:
    return Path(str(report.get("split", "?"))).name


def comparability(reports: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Return (comparable, notes). Notes explain every reason a delta is unsafe."""
    notes: list[str] = []
    splits = {split_of(r) for r in reports}
    models = {str(r.get("model", "?")) for r in reports}
    modes = {mode_of(r) for r in reports}

    if len(splits) > 1:
        notes.append(f"different splits: {', '.join(sorted(splits))} — deltas not comparable")
    if len(models) > 1:
        notes.append(f"different models: {', '.join(sorted(models))} — deltas not comparable")
    if len(modes) == 1:
        notes.append(f"both reports share one harness mode ({next(iter(modes))}) — nothing to compare")
    # A prompt edit silently changes what both sides were told. Treat a differing
    # generation the same as a differing split: no delta.
    prompts = {str(effective_fingerprint(r) or "unrecorded") for r in reports}
    if len(prompts) > 1:
        notes.append(
            f"different prompt generations ({sorted(prompts)}) — the two sides were not told the "
            "same thing; deltas not comparable"
        )
    # A scorer change re-judges the same trajectories differently: a different ruler.
    scorers = {str(r.get("scorer_version") or "unrecorded") for r in reports}
    if len(scorers) > 1:
        notes.append(
            f"different scorer versions ({sorted(scorers)}) — the two sides were judged by "
            "different rulers; deltas not comparable"
        )
    loops = {str(r.get("loop_version") or "unrecorded") for r in reports}
    if len(loops) > 1:
        notes.append(
            f"different episode loops ({sorted(loops)}) — turn handling differed; "
            "deltas not comparable"
        )
    if any(m == UNRECORDED_MODE for m in modes):
        notes.append(
            "at least one report predates contract recording; assume the legacy text ReAct loop"
        )

    comparable = (
        len(splits) == 1
        and len(models) == 1
        and len(modes) > 1
        and len(prompts) == 1
        and len(scorers) == 1
        and len(loops) == 1
    )
    return comparable, notes


def family_table(report: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Per-family passed/total, tolerating a report that only carries tasks[]."""
    families = report.get("family_breakdown")
    if isinstance(families, dict) and families:
        return {
            str(name): {"passed": _report_int(row, "passed"), "total": _report_int(row, "total")}
            for name, row in families.items()
        }
    tallied: dict[str, dict[str, int]] = {}
    for task in report.get("tasks", []):
        row = tallied.setdefault(str(task.get("family", "?")), {"passed": 0, "total": 0})
        row["total"] += 1
        if task.get("passed"):
            row["passed"] += 1
    return tallied


def build_comparison(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure: collect everything the renderer needs plus the comparability verdict."""
    comparable, notes = comparability(reports)
    return {
        "comparable": comparable,
        "notes": notes,
        "reports": reports,
        "metrics": [
            {"label": label, "values": [r.get(key) for r in reports]}
            for key, label in _OVERALL_METRICS
        ],
        "families": {
            name: {
                "per_report": [
                    family_table(r).get(name, {"passed": 0, "total": 0}) for r in reports
                ]
            }
            for name in sorted({n for r in reports for n in family_table(r)})
        },
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def render(comp: dict[str, Any]) -> str:
    reports = comp["reports"]
    headers = [mode_of(r) for r in reports]
    width = max(len(h) for h in headers) + 2
    lines: list[str] = []

    lines.append(f"split: {split_of(reports[0])}   model: {reports[0].get('model', '?')}")
    lines.append("")
    header_row = " " * 34 + "".join(h.rjust(width) for h in headers)
    lines.append(header_row)
    lines.append("-" * len(header_row))

    for row in comp["metrics"]:
        lines.append(row["label"].ljust(34) + "".join(_fmt(v).rjust(width) for v in row["values"]))

    for name, row in comp["families"].items():
        cells = []
        for entry in row["per_report"]:
            cells.append(f"{entry['passed']}/{entry['total']}")
        lines.append(f"  {name}".ljust(34) + "".join(c.rjust(width) for c in cells))

    if comp["comparable"]:
        first, second = reports[0], reports[1]
        delta = _report_int(second, "passed_tasks") - _report_int(first, "passed_tasks")
        lines.append("")
        lines.append(
            f"delta ({headers[1]} vs {headers[0]}): {delta:+d} tasks "
            f"({delta / max(1, _report_int(first, 'total_tasks')) * 100:+.1f} pp)"
        )
    else:
        lines.append("")
        lines.append("NOT COMPARABLE — no delta printed")

    if comp["notes"]:
        lines.append("")
        for note in comp["notes"]:
            lines.append(f"note: {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("reports", nargs="+", type=Path, help="two eval report JSON files")
    parser.add_argument("--json", action="store_true", help="emit the comparison as JSON")
    args = parser.parse_args(argv)

    if len(args.reports) != 2:
        parser.error("exactly two reports are required (react vs tool_call)")

    reports = [load_report(p) for p in args.reports]
    comp = build_comparison(reports)

    if args.json:
        print(json.dumps(comp, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(comp))
    return 0 if comp["comparable"] else 2


if __name__ == "__main__":
    sys.exit(main())
