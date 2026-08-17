#!/usr/bin/env python3
"""Thin CLI: bind frozen Env+split to ScriptHarness and print Pass / pass^k."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/run_split.py` without an editable install.
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nutrienv.harness.runner import run_split  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a frozen NutriEnv split against ScriptHarness (model=script)."
    )
    parser.add_argument(
        "--split",
        default=None,
        help="frozen split JSON (default: published 240-item exam via load_exam)",
    )
    parser.add_argument("--k", type=int, default=1, help="episodes per task (pass^k)")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="parallel tasks (default 1; ScriptHarness is local)",
    )
    parser.add_argument("--family", default=None, help="optional task family")
    parser.add_argument("--situation", default=None, help="optional situation kind")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_split(
        k=args.k,
        family=args.family,
        situation=args.situation,
        split_path=args.split,
        workers=args.workers,
    )
    print(
        f"env={result['env']} harness={result['harness']} model={result['model']}"
    )
    print(f"pass_rate={result['pass_rate']:.4f}")
    if args.k > 1:
        print(f"pass@{args.k}={result['pass_at_k']:.4f}")
        print(f"pass^{args.k}={result['pass_k']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
