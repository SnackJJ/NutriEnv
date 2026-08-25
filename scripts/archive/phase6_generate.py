#!/usr/bin/env python3
"""Phase-6 orchestration: 20 catalog-v2 pools (14 log + 6 evaluate).

    .venv/bin/python scripts/phase6_generate.py --seed 20260818 --workers 4
    .venv/bin/python scripts/phase6_generate.py --synthetic --force \\
      --output reports/phase6/candidates.json \\
      --manifest reports/phase6/manifest.json

Live path uses real LLM expanders + ticket 09/10 gates (structured JSON +
semantic vote). Review harness is S4; this script writes the candidate set
and manifest only. Does not freeze the published exam (that is S5 / 11b).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nutrienv.bench.grams_gate import call_judge  # noqa: E402
from nutrienv.bench.pipeline.expander import (  # noqa: E402
    build_system_prompt,
    build_user_prompt,
    coerce_candidates,
    make_llm_expander,
    parse_expander_payload,
    synthetic_expander,
    validate_expander_payload,
)
from nutrienv.bench.pipeline.freezer import freeze_tasks  # noqa: E402
from nutrienv.bench.pipeline.review_harness import resolved_items  # noqa: E402
from nutrienv.bench.pipeline.resolver import resolve_candidate  # noqa: E402
from nutrienv.bench.pipeline.legacy_run_batch import (  # noqa: E402
    _table_only_judge,
    pass_through_reviewer,
    run_batch,
)
from nutrienv.bench.pipeline.sampler import portion_alternatives, sample_pools  # noqa: E402
from nutrienv.bench.pipeline.semantic_vote import (  # noqa: E402
    DEFAULT_K,
    DEFAULT_THRESHOLD,
    semantic_vote,
)
from nutrienv.bench.pipeline.types import (  # noqa: E402
    CATALOG_V2_RELPATH,
    SAMPLER_RULE_VERSION,
    FoodPool,
    PoolFood,
    Rejected,
    catalog_digest,
)
from nutrienv.bench.realize import Task  # noqa: E402
from nutrienv.bench.validator import validate_draft  # noqa: E402
from nutrienv.io.chat import complete_chat  # noqa: E402
from nutrienv.io.dotenv import load_dotenv_keys  # noqa: E402
from nutrienv.world.catalog import canonical_food_id  # noqa: E402
from nutrienv.world.catalog_store import load_catalog  # noqa: E402
from nutrienv.world.portions import resolve_portion  # noqa: E402

load_dotenv_keys(_ROOT / ".env.local")

DEFAULT_SEED = 20260818
DEFAULT_WORKERS = 4
DEFAULT_OUTPUT = "reports/phase6/candidates.json"
DEFAULT_MANIFEST = "reports/phase6/manifest.json"
TASK_ID_PREFIX = "p6"
OMELET_ID = "2707198"
EXPANDER_MAX_TOKENS = 2048

# Ticket mix: 14 log + 6 evaluate, everyday + gym, quotas across the
# DashScope expander pool. flash-0731 is included with a larger token
# budget; S1 smoke showed 768 tokens often dies in reasoning.
MODEL_QUOTAS: tuple[tuple[str, int], ...] = (
    ("qwen3.8-max", 7),
    ("deepseek-v4-flash-0731", 5),
    ("glm-5.2", 4),
    ("qwen3.8-2.4t-a95b", 4),
)

QNS_STAPLES: tuple[tuple[str, str, float, float], ...] = (
    ("chicken_breast", "piece", 105.0, 120.0),
    ("tuna", "can", 75.0, 85.0),
    ("beef", "piece", 65.0, 85.0),
)


@dataclass(frozen=True)
class Slot:
    family: str
    persona: str
    model: str
    reserved: str | None = None


def plan_slots(seed: int) -> tuple[Slot, ...]:
    """20 slots: 14 log + 6 evaluate, 10 everyday + 10 gym, one QNS reserve."""
    pairs: list[tuple[str, str]] = (
        [("log", "everyday")] * 6
        + [("log", "gym")] * 7
        + [("evaluate", "everyday")] * 3
        + [("evaluate", "gym")] * 3
    )
    models: list[str] = []
    for model, count in MODEL_QUOTAS:
        models.extend([model] * count)
    if len(pairs) + 1 != len(models):
        raise RuntimeError("slot plan / model quota mismatch")
    rng = random.Random(int(seed))
    rng.shuffle(models)
    reserved_model = models.pop()
    slots = [
        Slot(family=family, persona=persona, model=model)
        for (family, persona), model in zip(pairs, models, strict=True)
    ]
    slots.append(
        Slot(
            family="log",
            persona="everyday",
            model=reserved_model,
            reserved="qns_isolation",
        )
    )
    return tuple(slots)


def qns_cross_check(catalog: Mapping) -> list[dict[str, object]]:
    """First-wins staple anchors vs the same food's QNS (ticket 06 / Opus)."""
    rows: list[dict[str, object]] = []
    for slug, key, first_wins, qns in QNS_STAPLES:
        entry = catalog[slug]
        portions = entry.get("portions") or {}
        got_first = float(portions[key])
        got_qns = float(portions["qns"])
        rows.append(
            {
                "slug": slug,
                "name": entry.get("name"),
                "first_wins_key": key,
                "first_wins_g": got_first,
                "expected_first_wins_g": first_wins,
                "qns_g": got_qns,
                "expected_qns_g": qns,
                "delta_g": round(got_qns - got_first, 2),
                "matches_table": got_first == first_wins and got_qns == qns,
            }
        )
    return rows


def quantifier_distribution(records: Sequence[Mapping]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        for item in record.get("items") or []:
            key = item.get("portion_key")
            if isinstance(key, str) and key:
                counts[key] += 1
    return dict(sorted(counts.items()))


def find_qns_isolation(
    records: Sequence[Mapping], catalog: Mapping
) -> dict[str, object] | None:
    """First accepted item whose QNS grams differ from another key on that food."""
    for record in records:
        for item in record.get("items") or []:
            food_id = item.get("food_id")
            key = item.get("portion_key")
            if key != "qns" or not isinstance(food_id, str):
                continue
            portions = (catalog.get(food_id) or {}).get("portions") or {}
            qns = portions.get("qns")
            if not isinstance(qns, (int, float)):
                continue
            others = [
                float(grams)
                for other, grams in portions.items()
                if other != "qns" and isinstance(grams, (int, float))
            ]
            if others and any(float(qns) != value for value in others):
                return {
                    "id": record.get("id"),
                    "food_id": food_id,
                    "qns_g": float(qns),
                    "other_keys": {
                        other: float(grams)
                        for other, grams in portions.items()
                        if other != "qns" and isinstance(grams, (int, float))
                    },
                }
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--catalog", default=CATALOG_V2_RELPATH)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument(
        "--allow-synthetic-fallback",
        action="store_true",
        help="if a live slot fails, fill it with synthetic_expander and disclose",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.workers < 1:
        raise SystemExit("workers must be >= 1")
    catalog_path = _resolve_path(args.catalog)
    catalog = load_catalog(catalog_path)
    digest = catalog_digest(catalog)
    slots = plan_slots(args.seed)
    output_path = _resolve_path(args.output)
    manifest_path = _resolve_path(args.manifest)
    tmp_dir = output_path.parent / ".phase6-slots"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    accepted: list[Task] = []
    rejected: list[Rejected] = []
    records: list[dict[str, object]] = []
    fallbacks: list[dict[str, object]] = []
    seq = 1
    for index, slot in enumerate(slots):
        expander, fallback_used = _slot_expander(slot, args)
        if slot.reserved == "qns_isolation":
            expander = _qns_isolation_expander(slot, args, expander)
            result_accepted, result_rejected, used_fallback = _run_reserved(
                slot,
                catalog=catalog,
                expander=expander,
                judge=_judge(args),
                task_id=f"{TASK_ID_PREFIX}-{slot.family}-{seq:04d}",
                enable_vote=not args.synthetic,
                allow_fallback=bool(args.allow_synthetic_fallback and not args.synthetic),
            )
            fallback_used = fallback_used or used_fallback
        else:
            spec = {
                "seed": args.seed + index * 1009,
                "sampler_rule_version": SAMPLER_RULE_VERSION,
                "catalog_sha": digest,
                "persona": slot.persona,
                "family_quotas": {slot.family: 1},
                "model_quotas": {slot.model: 1},
                "catalog": _catalog_field(args.catalog, catalog_path),
                "output_path": tmp_dir / f"slot-{index:02d}.json",
                "overwrite": True,
                "task_id_prefix": TASK_ID_PREFIX,
                "start_seq": seq,
            }
            result = run_batch(
                spec,
                expander=expander,
                judge=_judge(args),
                reviewer=pass_through_reviewer,
                catalog=catalog,
                workers=1,
                voter=None,
                enable_semantic_vote=not args.synthetic,
            )
            result_accepted = list(result.accepted)
            result_rejected = list(result.rejected)
            if (
                not result_accepted
                and not args.synthetic
                and args.allow_synthetic_fallback
            ):
                spec["output_path"] = tmp_dir / f"slot-{index:02d}-fallback.json"
                result = run_batch(
                    spec,
                    expander=synthetic_expander,
                    judge=_table_only_judge,
                    reviewer=pass_through_reviewer,
                    catalog=catalog,
                    workers=1,
                    voter=None,
                    enable_semantic_vote=False,
                )
                result_accepted = list(result.accepted)
                result_rejected = list(result.rejected)
                fallback_used = True
        seq += max(len(result_accepted) + len(result_rejected), 1)
        if fallback_used:
            fallbacks.append(
                {
                    "slot": index,
                    "family": slot.family,
                    "persona": slot.persona,
                    "model": slot.model,
                    "reserved": slot.reserved,
                }
            )
        vote = "skipped" if args.synthetic else "pass"
        for task in result_accepted:
            accepted.append(task)
            records.append(_record(task, model=slot.model, vote=vote, fallback=fallback_used))
        for item in result_rejected:
            rejected.append(item)
            records.append(
                {
                    "id": None,
                    "model": slot.model,
                    "family": item.family,
                    "persona": slot.persona,
                    "query": item.query,
                    "items": [],
                    "vote": "fail" if item.reason == "semantic" else item.reason,
                    "fallback": fallback_used,
                    "rejected": item.reason,
                }
            )

    isolation = find_qns_isolation(
        [row for row in records if row.get("id")], catalog
    )
    catalog_field = _catalog_field(args.catalog, catalog_path)
    extra = {
        "seed": args.seed,
        "sampler_rule_version": SAMPLER_RULE_VERSION,
        "persona": "mixed",
        "notes": (
            f"phase6 draft candidates from phase6_generate "
            f"(seed {args.seed}, catalog-v2). Not a published exam."
        ),
    }
    if accepted:
        payload, path = freeze_tasks(
            accepted,
            catalog=catalog,
            catalog_field=catalog_field,
            catalog_sha=digest,
            output_path=output_path,
            extra=extra,
            overwrite=bool(args.force),
        )
    else:
        payload, path = {"items": []}, None

    manifest = {
        "seed": args.seed,
        "catalog": catalog_field,
        "catalog_sha256": digest,
        "n_slots": len(slots),
        "n_accepted": len(accepted),
        "n_rejected": len(rejected),
        "slots": [
            {
                "family": slot.family,
                "persona": slot.persona,
                "model": slot.model,
                "reserved": slot.reserved,
            }
            for slot in slots
        ],
        "accepted": [row for row in records if row.get("id")],
        "rejected": [row for row in records if row.get("id") is None],
        "quantifiers": quantifier_distribution(
            [row for row in records if row.get("id")]
        ),
        "qns_cross_check": qns_cross_check(catalog),
        "qns_isolation": isolation,
        "fallbacks": fallbacks,
        "candidates_path": str(path) if path is not None else None,
        "synthetic": bool(args.synthetic),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"slots={len(slots)} accepted={len(accepted)} rejected={len(rejected)} "
        f"fallbacks={len(fallbacks)}"
    )
    print("quantifiers:", manifest["quantifiers"])
    print("qns_isolation:", isolation)
    if path is None:
        print("no candidates accepted", file=sys.stderr)
        return 1
    print(f"wrote {path}: {len(accepted)} items")
    print(f"wrote {manifest_path}")
    return 0


def _qns_isolation_expander(slot: Slot, args: argparse.Namespace, base):
    """Ask the reserved slot for omelet-as-serving (QNS ≠ piece)."""
    if args.synthetic:
        return base

    def expand(pool, *, persona: str, family: str):
        hint = (
            "\nInclude the omelet using a serving / 'an omelet' "
            "(the QNS amount), not a piece."
        )
        messages = (
            {"role": "system", "content": build_system_prompt(persona=persona, family=family)},
            {"role": "user", "content": build_user_prompt(pool) + hint},
        )
        for _attempt in range(3):
            parsed = parse_expander_payload(_expander_complete(slot.model, messages))
            if parsed is None:
                continue
            if validate_expander_payload(parsed, pool):
                continue
            return parsed
        return base(pool, persona=persona, family=family)

    return expand


def _slot_expander(slot: Slot, args: argparse.Namespace):
    if args.synthetic:
        return synthetic_expander, False
    return (
        make_llm_expander(
            model_route=[slot.model],
            seed=args.seed,
            complete=_expander_complete,
            parse_retries=2,
        ),
        False,
    )


def _expander_complete(model_id: str, messages: Sequence[Mapping[str, str]]) -> str:
    return complete_chat(
        model_id,
        messages,
        max_tokens=EXPANDER_MAX_TOKENS,
        timeout=90.0,
        retries=2,
    )


def _judge(args: argparse.Namespace):
    return _table_only_judge if args.synthetic else call_judge


def _run_reserved(
    slot: Slot,
    *,
    catalog,
    expander,
    judge,
    task_id: str,
    enable_vote: bool,
    allow_fallback: bool,
) -> tuple[list[Task], list[Rejected], bool]:
    pool = build_qns_isolation_pool(catalog, family=slot.family)
    used_fallback = False
    raw = expander(pool, persona=slot.persona, family=slot.family)
    candidates = coerce_candidates(
        raw, family=slot.family, persona=slot.persona, pool_id=pool.pool_id
    )
    if not candidates and allow_fallback:
        raw = synthetic_expander(pool, persona=slot.persona, family=slot.family)
        candidates = coerce_candidates(
            raw, family=slot.family, persona=slot.persona, pool_id=pool.pool_id
        )
        used_fallback = True
    accepted: list[Task] = []
    rejected: list[Rejected] = []
    seen: set[tuple[str, ...]] = set()
    if not candidates:
        rejected.append(Rejected("", "schema", slot.family))
        return accepted, rejected, used_fallback
    for candidate in candidates:
        task, reason = resolve_candidate(
            candidate,
            catalog=catalog,
            task_id=task_id,
            seen=seen,
            skip_gram_backresolve=enable_vote,
            pool=pool,
        )
        if reason is not None or task is None:
            rejected.append(reason or Rejected(candidate.query, "unresolvable", slot.family))
            continue
        if enable_vote and not _vote_ok(candidate, catalog, pool):
            rejected.append(Rejected(candidate.query, "semantic", slot.family))
            continue
        if _implausible(task, catalog, judge):
            rejected.append(Rejected(candidate.query, "implausible", slot.family))
            continue
        if validate_draft(task):
            rejected.append(Rejected(candidate.query, "validate_draft", slot.family))
            continue
        accepted.append(task)
    return accepted, rejected, used_fallback


def _vote_ok(candidate, catalog, pool) -> bool:
    from nutrienv.bench.pipeline.expander import match_pool_food

    for spoken, expression in candidate.items:
        food_id = match_pool_food(spoken, pool)
        if food_id is None:
            return False
        grams = resolve_portion(food_id, expression, catalog)
        if grams is None:
            return False
        accepted, _source = semantic_vote(
            candidate.query,
            food=spoken,
            expression=expression,
            voter=None,
            k=DEFAULT_K,
            threshold=DEFAULT_THRESHOLD,
            oracle_grams=float(grams),
            catalog=catalog,
            food_id=food_id,
        )
        if not accepted:
            return False
    return True


def _implausible(task: Task, catalog, judge) -> bool:
    from nutrienv.bench.grams_gate import plausibility_gate
    from nutrienv.bench.realize import scored_oracles

    seen: set[tuple[str, float]] = set()
    for oracle in scored_oracles(task.oracle):
        pairs: list[tuple[str, float]] = []
        if oracle.ledger_tail:
            pairs.extend((row.food_id, row.grams) for row in oracle.ledger_tail)
        if oracle.last_plan:
            pairs.extend(
                (str(item["food_id"]), float(item["grams"])) for item in oracle.last_plan
            )
        for food_id, grams in pairs:
            key = (food_id, grams)
            if key in seen:
                continue
            seen.add(key)
            ok, _source = plausibility_gate(food_id, grams, catalog, judge=judge)
            if not ok:
                return True
    return False


def build_qns_isolation_pool(catalog: Mapping, *, family: str) -> FoodPool:
    """Pool that contains omelet (piece 55 ≠ qns 110) plus seven others."""
    extras = sample_pools(catalog, seed=17, family=family, n_pools=1)[0]
    omelet = _pool_food(catalog, OMELET_ID)
    others = [food for food in extras.foods if food.food_id != OMELET_ID][:7]
    return FoodPool(
        pool_id=f"{family}-qns",
        family=family,
        foods=(omelet, *others),
    )


def _pool_food(catalog: Mapping, food_id: str) -> PoolFood:
    entry = catalog[food_id]
    aliases = tuple(
        str(alias) for alias in (entry.get("aliases") or []) if alias
    )
    return PoolFood(
        food_id=canonical_food_id(catalog, food_id),
        name=str(entry.get("name") or food_id),
        aliases=aliases,
        alternatives=portion_alternatives(entry),
    )


def _record(task: Task, *, model: str, vote: str, fallback: bool) -> dict[str, object]:
    return {
        "id": task.id,
        "model": model,
        "family": task.family,
        "persona": task.persona,
        "query": task.query,
        "items": resolved_items(task),
        "vote": vote,
        "fallback": fallback,
    }


def _catalog_field(raw: str, resolved: Path) -> str:
    path = Path(raw)
    if path.is_absolute():
        try:
            return str(resolved.relative_to(_ROOT))
        except ValueError:
            return str(resolved)
    return raw


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = _ROOT / path
    return path


if __name__ == "__main__":
    raise SystemExit(main())
