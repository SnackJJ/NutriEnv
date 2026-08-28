#!/usr/bin/env python3
"""Per-family sample runner (ADR 0017 mill, one item at a time).

This is NOT the batch orchestrator and it does not freeze anything. It runs
``generate_one`` across the five families until a small number of items per
family is accepted, validates every accepted Task with ``validate_draft`` and
``validate_oracle_grams``, and writes one JSON summary for review.

Use:

    .venv/bin/python scripts/generate_samples.py --count 3            # offline tracer
    .venv/bin/python scripts/generate_samples.py --count 3 --live     # live LLM (needs env keys)
    .venv/bin/python scripts/generate_samples.py --family log --count 2 --live

Evaluate is authored from a code-chosen plate (``search_fit_plate``): the
speech writer (synthetic or live) only phrases the plate. Knives then perturb
a fit plate; over_slot / under_slot / allergy are tried so the sample run
includes both fit and unfit Evaluate items.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nutrienv.bench.pipeline.freezer import task_to_item  # noqa: E402
from nutrienv.bench.pipeline.generate_one import (  # noqa: E402
    AMOUNT_PATHS,
    GenerateOneResult,
    generate_one,
    make_log_expander,
    make_unfit_rewriter,
    search_fit_plate,
)
from nutrienv.bench.pipeline.models import QWEN_EXPANDER_MODELS  # noqa: E402
from nutrienv.bench.pipeline.roster import (  # noqa: E402
    ROSTER,
    profile_for,
    sample_roster_person,
)
from nutrienv.bench.pipeline.sampler import (  # noqa: E402
    sample_pools,
    speakable_tracer_food,
    spoken_display_name,
)
from nutrienv.bench.pipeline.types import FoodPool  # noqa: E402
from nutrienv.io.chat import complete_chat  # noqa: E402
from nutrienv.world.catalog_store import load_catalog  # noqa: E402
from nutrienv.bench.validator import validate_draft, validate_oracle_grams  # noqa: E402

DEFAULT_CATALOG = "data/fdc/catalog-v2.sqlite"
DEFAULT_OUT = ".scratch/v2-samples/samples.json"
FAMILIES = ("log", "evaluate", "recommend", "update", "composite")


# --------------------------------------------------------------------------
# Synthetic tracer + speech writer (offline, deterministic)
# --------------------------------------------------------------------------

def _spoken(catalog, food_id: str) -> str:
    return spoken_display_name(catalog, food_id)


def make_synthetic_tracer(catalog):
    def tracer(pool: FoodPool, *, persona: str, family: str, amount_path: str | None = None) -> dict[str, object]:
        path = amount_path or "named_measure"
        picked = speakable_tracer_food(pool, catalog, amount_path=path)
        if picked is None:
            return {"query": "", "foods": []}
        _food, phrase, spoken = picked
        if family == "composite":
            query = f"I had {phrase} of {spoken} for lunch. What should I eat for dinner?"
        elif family == "evaluate":
            query = f"Evaluate this as my plan for lunch: {phrase} of {spoken}."
        else:
            query = f"For lunch I had {phrase} of {spoken}."
        return {"query": query, "foods": [_food.food_id]}

    return tracer


def synthetic_rewriter(catalog, items, *, intent: str, occasion: str, amount_path: str | None = None) -> dict[str, object]:
    """Phrase a code-chosen plate with the food's own table phrase."""
    parts = []
    foods = []
    for item in items:
        food_id = str(item["food_id"])
        grams = float(item["grams"])
        foods.append(food_id)
        # Prefer the quantity-1.0 alternative whose grams match the plate.
        phrase = _phrase_for_grams(catalog, food_id, grams)
        spoken = _spoken(catalog, food_id)
        parts.append(f"{phrase or f'{grams:g} g'} of {spoken}")
    query = f"Evaluate this as my plan for {occasion}: " + _join_natural(parts) + "."
    return {"query": query, "foods": foods}


def _phrase_for_grams(catalog, food_id: str, grams: float) -> str | None:
    entry = catalog.get(food_id) or {}
    portions = entry.get("portions") or {}
    if not isinstance(portions, dict):
        return None
    from nutrienv.bench.pipeline.sampler import portion_alternatives, unit_naturalness_rank

    matching = [
        alt
        for alt in portion_alternatives(entry)
        if alt.quantity == 1.0 and abs(alt.grams - grams) < 1e-9
    ]
    if not matching:
        return None
    matching.sort(key=lambda alt: (unit_naturalness_rank(alt.key), alt.phrase))
    return matching[0].phrase


def _join_natural(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _rewriter_for(catalog, *, live: bool, model_id: str = "qwen3.8-max"):
    if live:
        return make_unfit_rewriter(
            complete=complete_chat, catalog=catalog, model_id=model_id
        )
    return lambda items, *, intent, occasion, amount_path=None: synthetic_rewriter(
        catalog, items, intent=intent, occasion=occasion, amount_path=amount_path
    )


# --------------------------------------------------------------------------
# Recipes
# --------------------------------------------------------------------------

def _mk_live_expander(models):
    n = 0

    def make():
        nonlocal n
        model = models[n % len(models)]
        n += 1
        return make_log_expander(complete=complete_chat, model_id=model)

    return make


def _sample_log(rng_seed, catalog, *, live, models, pool_size, amount_path) -> GenerateOneResult:
    expander = (
        make_synthetic_tracer(catalog)
        if not live
        else _mk_live_expander(list(models))()
    )
    return generate_one(
        catalog=catalog,
        family="log",
        seed=rng_seed,
        amount_path=amount_path,
        occasion="lunch",
        pool_size=pool_size,
        expander=expander,
    )


def _sample_recommend(rng_seed, catalog, *, pool_size) -> GenerateOneResult:
    shells = ["rec-lunch", "rec-dinner", "rec-breakfast"]
    occasions = {"rec-lunch": "lunch", "rec-dinner": "dinner", "rec-breakfast": "breakfast"}
    # Constrained named-dish trap roughly every third item, but only when the
    # sampled roster person actually has an allergy (cc-review rounds 1+2:
    # rec-named-dish was silently dropped on a no-allergy person).
    person = sample_roster_person(rng_seed)
    if rng_seed % 3 == 2 and person.allergies:
        return generate_one(
            catalog=catalog,
            family="recommend",
            seed=rng_seed,
            occasion="dinner",
            shell="rec-named-dish",
        )
    shell = shells[rng_seed % len(shells)]
    return generate_one(
        catalog=catalog,
        family="recommend",
        seed=rng_seed,
        occasion=occasions[shell],
        shell=shell,
    )


def _sample_update(rng_seed, catalog, *, pool_size) -> GenerateOneResult:
    shells = [
        ("upd-add-allergy-short", {"allergen": "milk"}),
        ("upd-weight", {"n": "71"}),
        ("upd-phase-cut", {}),
        ("upd-phase-muscle", {}),
    ]
    shell, slots = shells[rng_seed % len(shells)]
    return generate_one(
        catalog=catalog,
        family="update",
        seed=rng_seed,
        shell=shell,
        slots=slots,
    )


def _sample_composite(rng_seed, catalog, *, live, models, pool_size, steps) -> GenerateOneResult:
    expander = make_synthetic_tracer(catalog) if not live else _mk_live_expander(list(models))()
    return generate_one(
        catalog=catalog,
        family="composite",
        seed=rng_seed,
        amount_path="named_measure",
        occasion="lunch",
        pool_size=pool_size,
        expander=expander,
        steps=steps,
    )


# --------------------------------------------------------------------------
# Entailment gate: the query's spoken food words must pin the Oracle food_id.
# cc-review-v2-samples §2: name.split(",",1)[0] emits common nouns that
# search_foods cannot resolve to the scored row. We require every token of
# the natural display name to appear in the query, so an agent reading the
# query has the discriminator tokens to hit the Oracle via search_foods.
# --------------------------------------------------------------------------

def _query_entails_food(query: str, catalog, food_id: str) -> bool:
    # cc-review-v2-samples-round2 §2.2 / §5.1: assert the spoken display name
    # ranks the Oracle #1 through FoodCatalog.search (the same surface the
    # agent's search_foods uses), not merely that every token appears in the
    # query. Token-subset is necessary but not sufficient.
    display = spoken_display_name(catalog, food_id)
    hits = catalog.search(display, limit=1)
    if hits and str(hits[0].get("food_id")) == food_id:
        return True
    return False


def _oracle_meal_foods(oracle) -> list[str]:
    foods: list[str] = []
    for row in oracle.ledger_tail or []:
        foods.append(str(getattr(row, "food_id", row)))
    for item in oracle.last_plan or []:
        if isinstance(item, dict):
            foods.append(str(item["food_id"]))
    for item in oracle.evaluated_plan or []:
        if isinstance(item, dict):
            foods.append(str(item["food_id"]))
    return foods


def _entailment_failures(task, catalog) -> list[str]:
    oracles = list(task.oracle.sub_oracles or ()) or [task.oracle]
    misses: list[str] = []
    for oracle in oracles:
        for food_id in set(_oracle_meal_foods(oracle)):
            if not _query_entails_food(task.query, catalog, food_id):
                misses.append(food_id)
    return sorted(set(misses))


def _payload(result: GenerateOneResult) -> dict:
    if result.accepted is not None:
        task = result.accepted
        payload = {
            "status": "accepted",
            "task_id": task.id,
            "family": task.family,
            "persona": task.persona,
            "tier": task.tier,
            "query": task.query,
            # Full S0 + oracle payload (same shape the freeze path writes), so
            # update profile diffs, recommend plan_windows, and composite
            # sub_oracles are all visible in the review JSON.
            "task": task_to_item(task),
        }
        if task.oracle.ledger_tail:
            payload["oracle_ledger_tail"] = [
                {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at}
                for row in task.oracle.ledger_tail
            ]
        if task.oracle.last_plan:
            payload["oracle_last_plan"] = task.oracle.last_plan
        if task.oracle.last_verdict is not None:
            payload["oracle_last_verdict"] = task.oracle.last_verdict
            payload["oracle_last_reasons"] = list(task.oracle.last_reasons)
        payload["validation"] = {
            "draft": validate_draft(task),
            "grams": validate_oracle_grams(task),
        }
        return payload
    rejected = result.rejected
    return {
        "status": "rejected",
        "query": rejected.query if rejected is not None else "",
        "reason": rejected.reason if rejected is not None else "unresolvable",
        "family": rejected.family if rejected is not None else "",
    }


def run_family(
    family,
    *,
    catalog,
    count,
    max_attempts,
    start_seed,
    live,
    models,
    pool_size,
) -> tuple[list[dict], list[dict]]:
    accepted: list[dict] = []
    rejected: list[dict] = []
    n = 0
    seed = start_seed
    while n < count and seed < start_seed + max_attempts:
        if family == "log":
            # Live expanders follow the named-measure instructions most
            # reliably; the synthetic tracer still rotates through all three
            # amount paths to prove the knob.
            path = "named_measure" if live else AMOUNT_PATHS[seed % len(AMOUNT_PATHS)]
            result = _sample_log(seed, catalog, live=live, models=models, pool_size=pool_size, amount_path=path)
        elif family == "recommend":
            result = _sample_recommend(seed, catalog, pool_size=pool_size)
        elif family == "update":
            result = _sample_update(seed, catalog, pool_size=pool_size)
        elif family == "composite":
            result = _sample_composite(seed, catalog, live=live, models=models, pool_size=pool_size, steps=("log", "recommend"))
        elif family == "evaluate":
            person = sample_roster_person(seed)
            profile = profile_for(person)
            pools = sample_pools(catalog, seed=seed, family="evaluate", n_pools=1, pool_size=pool_size, spoken_only=True)
            plate = search_fit_plate(pools[0], profile=profile, catalog=catalog, occasion="lunch") if pools else None
            if plate is None:
                rejected.append({"status": "rejected", "family": "evaluate", "seed": seed, "reason": "no_fit_plate"})
                seed += 1
                continue
            rewriter = _rewriter_for(
                catalog,
                live=live,
                model_id=models[n % len(models)] if models else "qwen3.8-max",
            )
            knife = None
            if n >= 1:
                # Alternate unfit knives after the first fit sample.
                knife = ("under_slot", "over_slot", "allergy")[n % 3]
            result = generate_one(
                catalog=catalog,
                family="evaluate",
                seed=seed,
                person=person,
                occasion="lunch",
                pool_size=pool_size,
                items=plate,
                rewriter=rewriter,
                knife=knife,
                tier="single",
            )
        else:
            raise AssertionError(family)

        payload = _payload(result)
        payload["seed"] = seed
        if result.accepted is not None:
            issues = payload["validation"]["draft"] + payload["validation"]["grams"]
            missing = _entailment_failures(result.accepted, catalog)
            if not live and missing:
                issues.append("entailment:" + "+".join(missing))
            if issues:
                # Admitted by the mill only after the validation gates run
                # (validate_draft, validate_oracle_grams, query↔food entailment).
                payload["status"] = "rejected"
                payload["reason"] = "validation:" + "; ".join(issues)
                rejected.append(payload)
                seed += 1
                continue
            accepted.append(payload)
            n += 1
            seed += 1
        else:
            rejected.append(payload)
            seed += 1
    return accepted, rejected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", action="append", choices=FAMILIES, default=None,
                        help="repeatable; default runs all five")
    parser.add_argument("--count", type=int, default=2, help="accepted samples per family")
    parser.add_argument("--max-attempts", type=int, default=48, help="seed attempts per family")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--pool-size", type=int, default=12)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--live", action="store_true", help="live LLM expander/rewriter")
    parser.add_argument("--models", default=",".join(QWEN_EXPANDER_MODELS))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    families = tuple(args.family) if args.family else FAMILIES
    models = tuple(part for part in args.models.split(",") if part.strip())
    catalog = load_catalog(Path(args.catalog))

    report: dict = {
        "families": families,
        "count_target": args.count,
        "live": args.live,
        "catalog": args.catalog,
        "accepted": {},
        "rejected": {},
    }
    all_accepted = 0
    for family in families:
        accepted, rejected = run_family(
            family,
            catalog=catalog,
            count=args.count,
            max_attempts=args.max_attempts,
            start_seed=args.seed,
            live=args.live,
            models=models,
            pool_size=args.pool_size,
        )
        report["accepted"][family] = accepted
        report["rejected"][family] = rejected
        all_accepted += len(accepted)
        print(f"{family}: {len(accepted)} accepted / {len(accepted) + len(rejected)} attempts", file=sys.stderr)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, indent=2 if args.pretty else None, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}; {all_accepted} accepted samples", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
