#!/usr/bin/env python3
"""Run ReActHarness against a frozen split. Generator is draft-only."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.bench import load_exam, load_split  # noqa: E402
from nutrienv.harness.react import REACT_VERSIONS, ReActHarness  # noqa: E402
from nutrienv.io.dotenv import load_dotenv_keys  # noqa: E402
from nutrienv.harness.runner import DEFAULT_MAX_STEPS, run_split  # noqa: E402

DEFAULT_MODEL = "deepseek-v4-flash"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a frozen NutriEnv split with ReActHarness (DeepSeek). "
            "API keys come from data/.env.local plus any files listed in the "
            "NUTRIENV_DOTENV environment variable (pathsep-separated)."
        )
    )
    parser.add_argument(
        "--split",
        default=None,
        help="frozen split JSON (default: load_exam, the published 240-item exam)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--harness-version",
        default="v0",
        choices=REACT_VERSIONS,
        help="ReAct manual version (default: v0, the frozen baseline)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible chat completions URL (auto DashScope for qwen*)",
    )
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="parallel tasks (one Env + harness clone each)",
    )
    parser.add_argument("--k", type=int, default=1, help="episodes per task")
    parser.add_argument(
        "--ids",
        default=None,
        help="comma-separated task ids (subset of the split)",
    )
    parser.add_argument("--limit", type=int, default=None, help="first N tasks")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="draft factory only; do not use for published Pass",
    )
    parser.add_argument("--n", type=int, default=None, help="draft factory size")
    parser.add_argument("--family", default=None, help="draft factory family")
    parser.add_argument(
        "--leak-oracle",
        action="store_true",
        help="diagnostic: put this Task's Oracle into the system prompt (not a published number)",
    )
    return parser


def load_react_tasks(split_path: Path | str | None = None):
    """Default exam is fail-closed; an explicit path uses the generic loader."""
    if split_path is None:
        return load_exam()
    return load_split(split_path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    extra = [
        Path(item)
        for item in (os.environ.get("NUTRIENV_DOTENV") or "").split(os.pathsep)
        if item
    ]
    load_dotenv_keys(_ROOT / ".env.local", *extra)

    use_factory = args.seed is not None or args.n is not None
    task_ids = None
    if use_factory:
        if args.seed is None or args.n is None:
            print("draft factory mode needs both --seed and --n", file=sys.stderr)
            return 2
        print(
            "warning: Generator factory is a draft, not the exam",
            file=sys.stderr,
        )
        split_path = None
        if args.ids:
            task_ids = [item.strip() for item in args.ids.split(",") if item.strip()]
    else:
        # Fail closed before constructing the harness: default exam uses
        # load_exam (catalog path + sha). An explicit --split is historical
        # and stays on the generic loader.
        tasks = load_react_tasks(args.split)
        split_path = None if args.split is None else args.split
        if args.ids:
            task_ids = [item.strip() for item in args.ids.split(",") if item.strip()]
        elif args.limit is not None:
            if args.limit < 1:
                print("--limit must be >= 1", file=sys.stderr)
                return 2
            task_ids = [task.id for task in tasks[: args.limit]]

    harness = ReActHarness(
        model=args.model,
        base_url=args.base_url,
        timeout=180.0,
        leak_oracle=args.leak_oracle,
        max_steps=args.max_steps,
        version=args.harness_version,
    )
    result = run_split(
        seed=args.seed,
        n=args.n,
        k=args.k,
        family=args.family,
        split_path=split_path,
        max_steps=args.max_steps,
        harness=harness,
        harness_label=harness.label + ("-leak" if args.leak_oracle else ""),
        model_label=args.model,
        task_ids=task_ids,
        verbose=True,
        workers=args.workers,
        leak_oracle=args.leak_oracle,
    )

    print(
        f"env={result['env']} harness={result['harness']} model={result['model']}"
    )
    print(f"split={result['split']} n={result['n']} pass_rate={result['pass_rate']:.4f}")
    if args.k > 1:
        print(f"pass@{args.k}={result['pass_at_k']:.4f}  (>=1 of {args.k})")
        print(f"pass^{args.k}={result['pass_k']:.4f}  (all {args.k})")
    for row in result.get("details") or []:
        mark = "PASS" if row["passed"] else ("PASS@" if row.get("passed_any") else "FAIL")
        ops = ",".join(row.get("ops") or [])
        print(
            f"{mark} {row['id']} family={row['family']} persona={row['persona']} "
            f"tag={row['tag']} steps={row.get('n_steps')} ops={ops}"
        )
    safe_model = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in args.model)
    report = Path(f"/tmp/react-gold-{harness.label}-{safe_model}.json")
    report.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    Path("/tmp/react-gold-last.json").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"report={report}", file=sys.stderr)
    return 0 if result["pass_rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
