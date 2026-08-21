#!/usr/bin/env python3
"""Check whether every Oracle in a frozen split can be Passed through Env.

Uses ``load_split`` (not ``load_exam``) so a mill draft can be checked before
anyone writes a test file for it, and before a version is admitted as exam.

    .venv/bin/python scripts/check_achievable.py
    .venv/bin/python scripts/check_achievable.py --split data/splits/pipeline-draft.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nutrienv.bench import check_achievable  # noqa: E402
from nutrienv.bench.pipeline.types import DEFAULT_FREEZE_RELPATH  # noqa: E402
from nutrienv.bench.split import load_split  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay each Oracle in a frozen split through Env and report "
            "unreachable ids plus coverage."
        )
    )
    parser.add_argument(
        "--split",
        default=DEFAULT_FREEZE_RELPATH,
        help="frozen split JSON (default: mill draft via load_split)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tasks = load_split(args.split)
    report = check_achievable(tasks)
    print(f"items: {len(tasks)}")
    print(f"unreachable: {len(report.unreachable)}")
    for task_id in report.unreachable:
        print(task_id)
    print("by family:")
    for family, count in sorted(report.by_family.items()):
        print(f"  family {family}: {count}")
    print("by feature:")
    for name, count in report.by_feature.items():
        print(f"  {name}: {count}")
    return 1 if report.unreachable else 0


if __name__ == "__main__":
    raise SystemExit(main())
