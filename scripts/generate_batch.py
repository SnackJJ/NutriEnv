#!/usr/bin/env python3
"""Generic v1.0 batch orchestrator: per-model quotas + pool-level workers.

    .venv/bin/python scripts/generate_batch.py \\
      --model-quota deepseek-v4-flash-0731:10 --model-quota qwen3.8-max:10 \\
      --family log --persona everyday --seed 42 --workers 6 \\
      --output data/splits/v1.0-batch.json --force

``--model id --count N`` is sugar for a single-model ``--model-quota id:N``.
``--synthetic`` is offline: synthetic expander, table-only judge, pass-through
reviewer. Each ``--family`` requests ``sum(model_quotas)`` (or ``--count``)
pools; with several families the per-model quotas are repeated so
``sum(model_quotas) == sum(family_quotas)``.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nutrienv.bench.grams_gate import call_judge  # noqa: E402
from nutrienv.bench.pipeline.expander import make_llm_expander, synthetic_expander  # noqa: E402
from nutrienv.bench.pipeline.review_harness import make_reviewer  # noqa: E402

from nutrienv.bench.pipeline.run_batch import (  # noqa: E402
    _table_only_judge,
    pass_through_reviewer,
    run_batch,
)
from nutrienv.bench.pipeline.types import (  # noqa: E402
    CATALOG_V1_RELPATH,
    DEFAULT_FREEZE_RELPATH,
    SAMPLER_RULE_VERSION,
    SUPPORTED_FAMILIES,
    catalog_digest,
)
from nutrienv.world.catalog_store import load_catalog  # noqa: E402

DEFAULT_SEED = 20260817
DEFAULT_WORKERS = 4
DEFAULT_PREFIX = "v10"
# Recipe knobs advertised on the CLI (family-specific rules are enforced by
# run_batch's parser). ``shell``/``scene`` are generate_one-only until
# resolver semantics exist; knife "swap" is excluded because its grams derive
# from target kcal, not a catalog/QNS portion.
RECIPE_KEYS = ("knife", "occasion", "tier", "items", "amount_path", "person")


def _parse_recipe(value: str) -> tuple[str, dict[str, str]]:
    family, separator, assignment = value.partition(":")
    family = family.strip()
    if not separator or not family:
        raise argparse.ArgumentTypeError(f"expected family:key=value, got {value!r}")
    key, _, raw = assignment.partition("=")
    key, raw_value = key.strip(), raw.strip()
    if key not in RECIPE_KEYS or not raw_value:
        raise argparse.ArgumentTypeError(
            f"expected family:key=value with key in {list(RECIPE_KEYS)}, got {value!r}"
        )
    return family, {key: raw_value}


def _parse_model_quota(value: str) -> tuple[str, int]:
    if ":" not in value:
        raise argparse.ArgumentTypeError(f"expected id:N, got {value!r}")
    model, _, raw = value.partition(":")
    model = model.strip()
    if not model:
        raise argparse.ArgumentTypeError(f"expected id:N, got {value!r}")
    try:
        count = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected id:N with integer N, got {value!r}"
        ) from exc
    if count < 0:
        raise argparse.ArgumentTypeError(f"quota must be >= 0, got {count}")
    return model, count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-quota",
        action="append",
        default=[],
        type=_parse_model_quota,
        metavar="ID:N",
        help="repeatable model_id:pool_count (takes precedence over rotation)",
    )
    parser.add_argument("--model", default=None, help="single-model sugar with --count")
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="pool count for --model (single-model sugar)",
    )
    parser.add_argument(
        "--family",
        action="append",
        default=[],
        choices=sorted(SUPPORTED_FAMILIES),
        help="repeatable family (default: log)",
    )
    parser.add_argument(
        "--recipe",
        action="append",
        default=[],
        type=_parse_recipe,
        metavar="FAMILY:KEY=VALUE",
        help=(
            "repeatable per-family recipe knob, e.g. --recipe evaluate:tier=pair "
            f"or --recipe evaluate:knife=allergy (keys: {list(RECIPE_KEYS)})"
        ),
    )
    parser.add_argument("--persona", default="everyday")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--output",
        default=DEFAULT_FREEZE_RELPATH,
        help=f"freeze path (default {DEFAULT_FREEZE_RELPATH})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing different freeze file",
    )
    parser.add_argument(
        "--catalog",
        default=CATALOG_V1_RELPATH,
        help=f"catalog sqlite (default {CATALOG_V1_RELPATH})",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="offline: synthetic expander + table-only judge + pass-through reviewer",
    )
    parser.add_argument("--task-id-prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--start-seq", type=int, default=1)
    parser.add_argument(
        "--skip-gram-backresolve",
        action="store_true",
        help=(
            "skip the deterministic query-gram == oracle check; "
            "default stays fail-closed until the ticket 10 vote is wired"
        ),
    )
    return parser


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = _ROOT / path
    return path


def _collect_quotas(args: argparse.Namespace) -> dict[str, int]:
    quotas: dict[str, int] = {}
    for model, count in args.model_quota:
        quotas[model] = quotas.get(model, 0) + count
    if args.model is not None:
        if args.count is None:
            raise SystemExit("--model requires --count")
        if args.count < 0:
            raise SystemExit("--count must be >= 0")
        quotas[args.model] = quotas.get(args.model, 0) + args.count
    elif args.count is not None and not quotas:
        raise SystemExit("--count requires --model or --model-quota")
    if not quotas:
        raise SystemExit("provide --model-quota id:N or --model id --count N")
    return quotas


def _print_stats(result) -> None:
    reasons = Counter(item.reason for item in result.rejected)
    print(
        f"pools={result.n_pools} candidates={result.n_candidates} "
        f"accepted={len(result.accepted)}"
    )
    if result.model_accepted:
        bits = [
            f"{model}={result.model_accepted.get(model, 0)}"
            for model in result.model_pools
        ]
        print("per-model accepted: " + " ".join(bits))
    if reasons:
        print(
            "rejections: "
            + " ".join(f"{reason}={count}" for reason, count in sorted(reasons.items()))
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.workers < 1:
        raise SystemExit("workers must be >= 1")
    if args.start_seq < 1:
        raise SystemExit("start_seq must be >= 1")

    model_quotas = _collect_quotas(args)
    families = args.family or ["log"]
    per_family = sum(model_quotas.values())
    family_quotas = {family: per_family for family in families}
    if len(families) > 1:
        model_quotas = {
            model: count * len(families) for model, count in model_quotas.items()
        }

    family_recipes: dict[str, dict[str, str]] = {}
    for family, recipe in args.recipe:
        if family not in families:
            raise SystemExit(
                f"--recipe family {family!r} is not among the requested "
                f"--family values {families}"
            )
        if not args.synthetic and set(recipe) & {"items", "amount_path"}:
            raise SystemExit(
                f"--recipe {family}:{'/'.join(recipe)} requires --synthetic; "
                "the LLM expander cannot honour items/amount_path yet"
            )
        family_recipes.setdefault(family, {}).update(recipe)

    catalog_path = _resolve_path(args.catalog)
    catalog = load_catalog(catalog_path)
    digest = catalog_digest(catalog)
    catalog_field = args.catalog
    if Path(catalog_field).is_absolute():
        try:
            catalog_field = str(Path(catalog_field).relative_to(_ROOT))
        except ValueError:
            catalog_field = str(catalog_path)

    spec = {
        "seed": args.seed,
        "sampler_rule_version": SAMPLER_RULE_VERSION,
        "catalog_sha": digest,
        "persona": args.persona,
        "family_quotas": family_quotas,
        "model_route": {},
        "model_quotas": model_quotas,
        "family_recipes": family_recipes or None,
        "catalog": catalog_field,
        "output_path": _resolve_path(args.output),
        "overwrite": bool(args.force),
        "task_id_prefix": args.task_id_prefix,
        "start_seq": args.start_seq,
        "skip_gram_backresolve": bool(args.skip_gram_backresolve),
    }

    if args.synthetic:
        expander = synthetic_expander
        judge = _table_only_judge
        reviewer = pass_through_reviewer
        voter = None
        enable_semantic_vote = False
    else:
        expander = make_llm_expander(
            model_route=list(model_quotas),
            seed=args.seed,
        )
        judge = call_judge
        reviewer = make_reviewer()
        voter = None
        enable_semantic_vote = True

    # Spec validation (recipe keys/values, quotas, sha) is labeled as such:
    # failures here are rejections, while later run_batch failures keep their
    # own reporting.
    try:
        from nutrienv.bench.pipeline.run_batch import _parse_spec

        _parse_spec(spec)
    except ValueError as exc:
        raise SystemExit(f"batch spec rejected: {exc}")

    result = run_batch(
        spec,
        expander=expander,
        judge=judge,
        reviewer=reviewer,
        catalog=catalog,
        workers=args.workers,
        voter=voter,
        enable_semantic_vote=enable_semantic_vote,
    )
    _print_stats(result)
    if not result.accepted:
        print("no candidates accepted", file=sys.stderr)
        return 1
    print(f"wrote {result.path}: {len(result.accepted)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
