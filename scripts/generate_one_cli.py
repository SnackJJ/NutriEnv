#!/usr/bin/env python3
"""ADR 0017 mill single-item CLI: roster world → pool → {query, foods} → bind.

Run one item through the new generation pipeline (``generate_one``):

    .venv/bin/python scripts/generate_one_cli.py --synthetic            # offline tracer
    .venv/bin/python scripts/generate_one_cli.py --family log --seed 7  # live Qwen expander
    .venv/bin/python scripts/generate_one_cli.py --family evaluate --seed 7 --anchor

The old v1.0 batch orchestrators (generate_batch / phase6_generate /
run_pilot_20) are archived: this is the replacement surface, one item at a
time. Batch orchestration comes later, once several items pass end-to-end.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nutrienv.bench.pipeline.generate_one import (  # noqa: E402
    AMOUNT_PATHS,
    make_log_expander,
    generate_one,
)
from nutrienv.bench.pipeline.gram_anchor import make_llm_gram_anchor  # noqa: E402
from nutrienv.bench.pipeline.models import QWEN_EXPANDER_MODELS  # noqa: E402
from nutrienv.bench.pipeline.roster import ROSTER, profile_for  # noqa: E402
from nutrienv.bench.pipeline.types import FoodPool  # noqa: E402
from nutrienv.io.chat import complete_chat  # noqa: E402
from nutrienv.world.catalog_store import load_catalog  # noqa: E402

DEFAULT_CATALOG = "data/fdc/catalog-v2.sqlite"


def _live_complete(model_id: str, messages: Sequence[Mapping[str, str]]) -> str:
    return complete_chat(model_id, messages)


def synthetic_query_foods_expander(
    pool: FoodPool, *, persona: str, family: str, amount_path: str | None = None
) -> dict[str, object]:
    """Deterministic tracer for the {query, foods} contract. No network.

    Picks the first pool food with a speakable 1-quantity alternative and
    writes a phrase that matches the requested amount path (grams never pass
    through this function: ``generate_one`` binds them in code).
    """
    path = amount_path or "named_measure"
    for food in pool.foods:
        phrase = _tracer_phrase(food, path)
        if phrase is None:
            continue
        spoken = food.aliases[0] if food.aliases else food.name.split(",", 1)[0].strip()
        if not spoken:
            spoken = food.food_id
        query = f"Please log {phrase} of {spoken} for lunch."
        if family in {"evaluate", "composite"}:
            query = f"Evaluate this as my plan for lunch: {phrase} of {spoken}."
        return {"query": query, "foods": [food.food_id]}
    return {"query": "", "foods": []}


def _tracer_phrase(food, path: str) -> str | None:
    if path == "explicit_grams":
        for alt in food.alternatives:
            if alt.quantity == 1.0 and alt.key not in {"qns"}:
                return f"{alt.grams:g} g"
        return None
    if path == "unspecified":
        # QNS-backed foods speak bowl/plate/order (qns grams resolve).
        for alt in food.alternatives:
            if alt.key == "qns" and alt.quantity == 1.0:
                return "a bowl"
        return None
    for alt in food.alternatives:
        if alt.quantity == 1.0 and alt.key not in {"qns"}:
            return alt.phrase
    return None


def _person_for(person_id: str | None) -> str | None:
    if person_id is None:
        return None
    for person in ROSTER:
        if person.user_id == person_id:
            return person_id
    raise argparse.ArgumentTypeError(
        f"unknown roster person {person_id!r} "
        f"(expected one of {[p.user_id for p in ROSTER]})"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", default="log",
                        choices=("log", "evaluate", "recommend", "update", "composite"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--person", type=_person_for, default=None,
                        help="roster user_id; default samples from --seed")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--amount-path", default=None, choices=AMOUNT_PATHS)
    parser.add_argument("--occasion", default="lunch")
    parser.add_argument("--pool-size", type=int, default=12)
    parser.add_argument("--tier", default="", help="evaluate-only tier; empty elsewhere")
    parser.add_argument("--model", default=None,
                        help="expander model id (default: first live Qwen leg)")
    parser.add_argument("--synthetic", action="store_true",
                        help="offline deterministic tracer (no network)")
    parser.add_argument("--anchor", action="store_true",
                        help="propose grams via an LLM anchor when resolve_portion fails (live only)")
    parser.add_argument("--output", default=None, help="write the task/rejection JSON here")
    parser.add_argument("--pretty", action="store_true")
    return parser


def _result_payload(result) -> dict:
    if result.accepted is not None:
        task = result.accepted
        payload: dict = {
            "status": "accepted",
            "task_id": task.id,
            "family": task.family,
            "persona": task.persona,
            "query": task.query,
        }
        if task.oracle.ledger_tail:
            payload["oracle_ledger"] = [
                {"food_id": row.food_id, "grams": row.grams, "when": row.eaten_at}
                for row in task.oracle.ledger_tail
            ]
        return payload
    rejected = result.rejected
    return {
        "status": "rejected",
        "query": rejected.query if rejected is not None else "",
        "reason": rejected.reason if rejected is not None else "unresolvable",
        "family": rejected.family if rejected is not None else "",
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = load_catalog(Path(args.catalog))

    if args.synthetic:
        expander = synthetic_query_foods_expander
    else:
        model_id = args.model or QWEN_EXPANDER_MODELS[0]
        expander = make_log_expander(complete=_live_complete)

    gram_anchor = None
    if args.anchor:
        if args.synthetic:
            raise SystemExit("--anchor requires a live model (drop --synthetic)")
        gram_anchor = make_llm_gram_anchor(catalog=catalog)

    kwargs: dict = dict(
        catalog=catalog,
        family=args.family,
        seed=args.seed,
        amount_path=args.amount_path,
        occasion=args.occasion,
        pool_size=args.pool_size,
        expander=expander,
        tier=args.tier,
        gram_anchor=gram_anchor,
    )
    if args.person is not None:
        from nutrienv.bench.pipeline.roster import profile_for
        person = next(p for p in ROSTER if p.user_id == args.person)
        kwargs["person"] = person

    result = generate_one(**kwargs)
    payload = _result_payload(result)
    indent = 2 if args.pretty or args.synthetic else None
    text = json.dumps(payload, indent=indent, ensure_ascii=False, sort_keys=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0 if result.accepted is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
