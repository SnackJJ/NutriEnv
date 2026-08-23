"""Single entry: Sampler → Expander → Resolver → Judge → validate_draft → Review → Freezer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from nutrienv.bench.grams_gate import plausibility_gate
from nutrienv.bench.quality_gates import EVALUATE_TIERS
from nutrienv.bench.realize import Task, scored_oracles
from nutrienv.bench.validator import validate_draft
from nutrienv.world.catalog import iter_catalog_entries
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import normalize_tags

from .expander import LlmExpander, coerce_candidates, make_llm_expander, synthetic_expander
from .freezer import freeze_tasks
from .knives import KNIVES
from .models import assign_model
from .resolver import (
    resolve_roster_person,
    build_food_index,
    match_spoken,
    resolve_candidate,
)
from .review_harness import stage_a_code_gate
from .sampler import sample_pools
from .semantic_vote import (
    DEFAULT_K,
    DEFAULT_MODEL_IDS,
    DEFAULT_THRESHOLD,
    MAX_TOKENS,
    TEMPERATURE,
    semantic_vote,
)
from .types import (
    BASE_EXAM_QUOTA,
    CATALOG_V1_RELPATH,
    COMPOSITE_ADMISSION_SLOTS,
    DEFAULT_COMPOSITE_SAMPLE_RELPATH,
    DEFAULT_FREEZE_RELPATH,
    PIPELINE_VERSION,
    SAMPLER_RULE_VERSION,
    SUPPORTED_FAMILIES,
    Expander,
    Judge,
    Rejected,
    Reviewer,
    catalog_digest,
    repo_root,
)

__all__ = [
    "BatchResult",
    "pass_through_reviewer",
    "quota_ledger",
    "run_batch",
    "write_composite_sample",
    "write_tracer_sample",
]


@dataclass
class BatchResult:
    payload: dict
    path: Path | None
    accepted: list[Task] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    review: Mapping[str, object] = field(default_factory=dict)
    model_pools: dict[str, list[str]] = field(default_factory=dict)
    model_accepted: dict[str, int] = field(default_factory=dict)
    n_pools: int = 0
    n_candidates: int = 0


def pass_through_reviewer(candidates: Sequence[Task]) -> dict:
    """Vote-level placeholder: accept everything, return the required shape.

    The Stage A code hard-gate is NOT skipped by this: ``run_batch`` applies
    ``stage_a_code_gate`` structurally before any reviewer runs, so there is
    no mill mode that reaches a freeze without passing the gate.
    """
    return {
        "anomalies": [],
        "per_candidate": {task.id: {} for task in candidates},
    }


def _code_gate(
    accepted: list[Task], rejected: list[Rejected]
) -> tuple[list[Task], list[Rejected]]:
    """Structural Stage A hard-gate. No mill run can bypass it."""
    gated: list[Task] = []
    for task in accepted:
        reasons = stage_a_code_gate(task)
        if reasons:
            rejected.append(Rejected(task.query, "code_gate", task.family))
            continue
        gated.append(task)
    return gated, rejected


def run_batch(
    batch_spec: Mapping,
    *,
    expander: Expander,
    judge: Judge,
    reviewer: Reviewer,
    catalog,
    workers: int = 1,
    voter=None,
    vote_k: int = DEFAULT_K,
    vote_threshold: float = DEFAULT_THRESHOLD,
    vote_models: Sequence[str] | None = None,
    vote_temperature: float = TEMPERATURE,
    vote_max_tokens: int = MAX_TOKENS,
    enable_semantic_vote: bool | None = None,
) -> BatchResult:
    """Run the candidate pipeline. LLM roles must be injected; no network."""
    if expander is None or judge is None or reviewer is None:
        raise ValueError("expander, judge, and reviewer must be injected")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be an int >= 1")
    spec = parse_spec(batch_spec)
    # Fail before any job runs: items/amount_path recipes are synthetic-only
    # (same message as the per-job defence-in-depth guard in _expand_one),
    # so a mixed-quota real batch does not waste LLM calls before failing.
    # Fail closed like pool_allergen: an excluded tag no catalog food carries
    # would silently exclude nothing (checked before any job runs).
    known_tags = {
        tag
        for _food_id, entry in iter_catalog_entries(catalog)
        for tag in normalize_tags(list(entry.get("allergen_tags") or []))
    }
    for family, recipe in spec["family_recipes"].items():
        if "exclude_allergens" in recipe:
            unknown = [
                tag
                for tag in recipe["exclude_allergens"].split(",")
                if tag not in known_tags
            ]
            if unknown:
                raise ValueError(
                    f"recipe {family}.exclude_allergens names unknown "
                    f"allergen tag(s) {unknown} (catalog tags: "
                    f"{sorted(known_tags)})"
                )
    if any(
        key in _EXPANDER_HINTS
        for recipe in spec["family_recipes"].values()
        for key in recipe
    ) and expander is not synthetic_expander:
        raise ValueError(_HINTS_NEED_SYNTHETIC)
    digest = catalog_digest(catalog)
    if digest != spec["catalog_sha"]:
        raise ValueError(
            f"catalog sha256 mismatch: catalog={digest} spec={spec['catalog_sha']}"
        )

    persona = spec["persona"]
    food_index = build_food_index(catalog)
    jobs = _build_jobs(spec, catalog)
    expanders = _bind_expanders(jobs, expander, spec["seed"], workers=workers)
    accepted, rejected, stats = _run_jobs(
        jobs,
        expanders=expanders,
        persona=persona,
        catalog=catalog,
        food_index=food_index,
        judge=judge,
        prefix=spec["task_id_prefix"],
        start_seq=spec["start_seq"],
        skip_gram_backresolve=spec["skip_gram_backresolve"],
        voter=voter,
        vote_k=vote_k,
        vote_threshold=vote_threshold,
        vote_models=tuple(vote_models) if vote_models is not None else DEFAULT_MODEL_IDS,
        vote_temperature=vote_temperature,
        vote_max_tokens=vote_max_tokens,
        enable_semantic_vote=enable_semantic_vote,
        workers=workers,
    )

    accepted, rejected = _code_gate(accepted, rejected)
    review = reviewer(accepted)
    if (
        not isinstance(review, Mapping)
        or "anomalies" not in review
        or "per_candidate" not in review
    ):
        raise ValueError("reviewer must return {anomalies, per_candidate}")

    extra = {
        "seed": spec["seed"],
        "sampler_rule_version": spec["sampler_rule_version"],
        "persona": persona,
        "notes": (
            f"{PIPELINE_VERSION} tracer-bullet freeze from run_batch "
            f"(sampler {spec['sampler_rule_version']}, seed {spec['seed']})."
        ),
        "quota_ledger": quota_ledger(accepted, spec["family_quotas"]),
    }
    if spec.get("version"):
        extra["version"] = spec["version"]
    if not accepted:
        return BatchResult(
            payload={
                "version": PIPELINE_VERSION,
                "catalog": spec["catalog_field"],
                "catalog_sha256": digest,
                "items": [],
                **extra,
            },
            path=None,
            accepted=[],
            rejected=rejected,
            review=review,
            model_pools=stats["model_pools"],
            model_accepted=stats["model_accepted"],
            n_pools=stats["n_pools"],
            n_candidates=stats["n_candidates"],
        )

    payload, path = freeze_tasks(
        accepted,
        catalog=catalog,
        catalog_field=spec["catalog_field"],
        catalog_sha=digest,
        output_path=spec["output_path"],
        extra=extra,
        overwrite=spec["overwrite"],
    )
    return BatchResult(
        payload=payload,
        path=path,
        accepted=accepted,
        rejected=rejected,
        review=review,
        model_pools=stats["model_pools"],
        model_accepted=stats["model_accepted"],
        n_pools=stats["n_pools"],
        n_candidates=stats["n_candidates"],
    )


def write_composite_sample(
    *,
    output_path: Path | str | None = None,
    n: int = 2,
) -> BatchResult:
    """Freeze a small composite sample against catalog-v1. Not a published exam."""
    catalog_path = repo_root() / CATALOG_V1_RELPATH
    catalog = load_catalog(catalog_path)
    digest = catalog_digest(catalog)
    spec = {
        "seed": 20260817,
        "sampler_rule_version": SAMPLER_RULE_VERSION,
        "catalog_sha": digest,
        "persona": "everyday",
        "family_quotas": {"composite": n},
        "model_route": {},
        "catalog": CATALOG_V1_RELPATH,
        "output_path": output_path or (repo_root() / DEFAULT_COMPOSITE_SAMPLE_RELPATH),
        "version": "pipeline-composite-draft",
    }
    return run_batch(
        spec,
        expander=synthetic_expander,
        judge=_table_only_judge,
        reviewer=pass_through_reviewer,
        catalog=catalog,
    )


def quota_ledger(
    accepted: Sequence[Task], family_quotas: Sequence[tuple[str, int]]
) -> dict[str, object]:
    """The published 240 includes the 36 composite slots (ADR 0016).

    Composite items are not an extra quota on top of the exam: they sit
    inside ``BASE_EXAM_QUOTA`` through ``COMPOSITE_ADMISSION_SLOTS`` and use
    the same roster. The ledger still counts single-family and composite
    acceptances separately so drift from either slice stays visible.
    """
    single_accepted: dict[str, int] = {}
    composite_accepted = 0
    for task in accepted:
        if task.oracle.sub_oracles:
            composite_accepted += 1
            continue
        single_accepted[task.family] = single_accepted.get(task.family, 0) + 1
    if composite_accepted > COMPOSITE_ADMISSION_SLOTS:
        raise ValueError(
            f"composite accepted {composite_accepted} exceeds the "
            f"{COMPOSITE_ADMISSION_SLOTS} admission slots inside the exam (ADR 0016)"
        )
    total = sum(single_accepted.values()) + composite_accepted
    if total > BASE_EXAM_QUOTA:
        raise ValueError(
            f"accepted {total} items exceed the {BASE_EXAM_QUOTA}-item exam (ADR 0016)"
        )
    return {
        "exam_quota": BASE_EXAM_QUOTA,
        "composite_admission_slots": COMPOSITE_ADMISSION_SLOTS,
        "single_family_accepted": single_accepted,
        "composite_accepted": composite_accepted,
        "requested": {family: count for family, count in family_quotas},
    }


def write_tracer_sample(
    *,
    output_path: Path | str | None = None,
    n_log: int = 3,
) -> BatchResult:
    """Freeze a small synthetic pipeline sample against catalog-v1."""
    catalog_path = repo_root() / CATALOG_V1_RELPATH
    catalog = load_catalog(catalog_path)
    digest = catalog_digest(catalog)
    spec = {
        "seed": 20260817,
        "sampler_rule_version": SAMPLER_RULE_VERSION,
        "catalog_sha": digest,
        "persona": "everyday",
        "family_quotas": {"log": n_log},
        "model_route": {},
        "catalog": CATALOG_V1_RELPATH,
        "output_path": output_path or (repo_root() / DEFAULT_FREEZE_RELPATH),
        "overwrite": False,
    }
    return run_batch(
        spec,
        expander=synthetic_expander,
        judge=_table_only_judge,
        reviewer=pass_through_reviewer,
        catalog=catalog,
    )


def _table_only_judge(_food: str, _grams: float) -> str:
    # Synthetic phrases are table multiples; a call means something drifted.
    return "suspect"


def _implausible(task: Task, catalog, judge: Judge) -> bool:
    grams_items: list[tuple[str, float]] = []
    for oracle in scored_oracles(task.oracle):
        if oracle.ledger_tail:
            grams_items.extend((row.food_id, row.grams) for row in oracle.ledger_tail)
        if oracle.last_plan:
            grams_items.extend(
                (str(item["food_id"]), float(item["grams"])) for item in oracle.last_plan
            )
    seen: set[tuple[str, float]] = set()
    for food_id, grams in grams_items:
        key = (food_id, grams)
        if key in seen:
            continue
        seen.add(key)
        accepted, _source = plausibility_gate(food_id, grams, catalog, judge=judge)
        if not accepted:
            return True
    return False


def parse_spec(batch_spec: Mapping) -> dict:
    if not isinstance(batch_spec, Mapping):
        raise ValueError("batch_spec must be a mapping")
    if "seed" not in batch_spec:
        raise ValueError("batch_spec.seed is required")
    if "catalog_sha" not in batch_spec:
        raise ValueError("batch_spec.catalog_sha is required")
    quotas_raw = batch_spec.get("family_quotas")
    if not isinstance(quotas_raw, Mapping) or not quotas_raw:
        raise ValueError("batch_spec.family_quotas is required")
    quotas: list[tuple[str, int]] = []
    for family, count in sorted(quotas_raw.items()):
        if family not in SUPPORTED_FAMILIES:
            raise ValueError(f"unsupported family {family!r}")
        n = int(count)
        if n < 0:
            raise ValueError(f"family quota for {family!r} must be >= 0")
        if n == 0:
            continue
        quotas.append((family, n))
    if not quotas:
        raise ValueError("batch_spec.family_quotas must request at least one item")
    output = batch_spec.get("output_path")
    output_path = Path(output) if output is not None else repo_root() / DEFAULT_FREEZE_RELPATH
    catalog_field = batch_spec.get("catalog") or CATALOG_V1_RELPATH
    if not isinstance(catalog_field, str) or not catalog_field:
        raise ValueError("batch_spec.catalog must be a path string")
    persona = batch_spec.get("persona") or "everyday"
    if not isinstance(persona, str) or not persona:
        raise ValueError("batch_spec.persona must be a non-empty string")
    rule = batch_spec.get("sampler_rule_version") or SAMPLER_RULE_VERSION
    if not isinstance(rule, str) or not rule:
        raise ValueError("batch_spec.sampler_rule_version must be a string")
    version = batch_spec.get("version")
    if version is not None and (not isinstance(version, str) or not version):
        raise ValueError("batch_spec.version must be a non-empty string")
    overwrite = batch_spec.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise ValueError("batch_spec.overwrite must be a bool")
    prefix = batch_spec.get("task_id_prefix") or "v10"
    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("batch_spec.task_id_prefix must be a non-empty string")
    raw_seq = batch_spec.get("start_seq", 1)
    if raw_seq is None:
        raw_seq = 1
    start_seq = int(raw_seq)
    if start_seq < 1:
        raise ValueError("batch_spec.start_seq must be >= 1")
    skip_gram_backresolve = batch_spec.get("skip_gram_backresolve", False)
    if not isinstance(skip_gram_backresolve, bool):
        raise ValueError("batch_spec.skip_gram_backresolve must be a bool")
    family_recipes = _parse_family_recipes(
        batch_spec.get("family_recipes"), {family for family, _count in quotas}
    )
    total_quota = sum(count for _family, count in quotas)
    model_quotas = _parse_model_quotas(batch_spec.get("model_quotas"), total_quota)
    return {
        "seed": int(batch_spec["seed"]),
        "catalog_sha": str(batch_spec["catalog_sha"]),
        "persona": persona,
        "family_quotas": quotas,
        "sampler_rule_version": rule,
        "output_path": output_path,
        "catalog_field": catalog_field,
        "version": version,
        "overwrite": overwrite,
        "task_id_prefix": prefix.strip(),
        "start_seq": start_seq,
        "model_quotas": model_quotas,
        "skip_gram_backresolve": skip_gram_backresolve,
        "family_recipes": family_recipes,
    }


# Recipe knobs the resolver actually implements, per family (issue 15
# transport). A key outside the family's set would be silently dropped or
# ignored by the realize branch, so the parser refuses it. ``tier`` is
# evaluate-only authoring data whose value must be a declared
# EVALUATE_TIERS entry (mirrors generate_one's guard); recommend can
# only carry an occasion override. ``shell``/``scene`` are generate_one-only
# until resolver semantics exist; ``occasion`` on evaluate is read only by
# the knife branch from the spoken query, so it is not an advertised knob
# there. ``swap`` is excluded from knives because its grams derive from
# target kcal rather than a catalog/QNS portion.
# Shared by the run_batch entry guard and the per-job guard so a future
# wording change cannot silently desynchronise the two fail-early paths.
_HINTS_NEED_SYNTHETIC = (
    "recipe items/amount_path require the synthetic expander "
    "(--synthetic); the LLM expander cannot honour them yet"
)
# ``log`` carries no recipe: it has no person semantics resolver-side (its
# realize branch is the plain tracer log).
_RECIPE_KEYS: dict[str, frozenset[str]] = {
    "evaluate": frozenset(
        {
            "knife",
            "tier",
            "items",
            "amount_path",
            "person",
            "pool_allergen",
            "exclude_allergens",
        }
    ),
    "recommend": frozenset({"occasion", "person", "pool_allergen", "exclude_allergens"}),
    "update": frozenset({"person", "pool_allergen"}),
    "composite": frozenset({"person", "pool_allergen"}),
}
# Knobs consumed by the expander when producing the query (the rest stamp the
# Candidate). Synthetic expander only — anything else fails closed (see
# _expand_one): LLM prompt shells are issue-15 design.
_EXPANDER_HINTS = frozenset({"items", "amount_path", "exclude_allergens"})
# amount_path values with resolver/expander semantics. Only "explicit_grams"
# changes synthetic speech; there are no accepted no-op values.
_RECIPE_AMOUNT_PATHS = frozenset({"explicit_grams"})
_BATCH_KNIVES = frozenset(KNIVES) - {"swap"}


def _parse_family_recipes(
    raw: object, requested_families: set[str]
) -> dict[str, dict[str, str]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError(
            "batch_spec.family_recipes must be a non-empty mapping"
        )
    recipes: dict[str, dict[str, str]] = {}
    for family, recipe in raw.items():
        if family not in SUPPORTED_FAMILIES:
            raise ValueError(f"unsupported family {family!r} in family_recipes")
        if family not in requested_families:
            raise ValueError(
                f"family_recipes entry for {family!r} is not among the "
                f"requested family_quotas {sorted(requested_families)}"
            )
        allowed = _RECIPE_KEYS.get(family, frozenset())
        if not isinstance(recipe, Mapping):
            raise ValueError(f"family_recipes[{family!r}] must be a mapping")
        parsed: dict[str, str] = {}
        for key, value in recipe.items():
            if key not in allowed:
                raise ValueError(
                    f"recipe key {key!r} is not supported for {family!r} "
                    f"(allowed: {sorted(allowed)})"
                )
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"recipe {family}.{key} must be a non-empty string, "
                    f"got {value!r}"
                )
            if key == "knife" and value not in _BATCH_KNIVES:
                raise ValueError(
                    f"unsupported evaluate knife {value!r} "
                    f"(allowed: {sorted(_BATCH_KNIVES)})"
                )
            if key == "exclude_allergens":
                # Comma/space-separated tags, normalized like catalog tags;
                # an unparseable value is refused rather than silently
                # excluding nothing.
                tags = normalize_tags(value.replace(",", " ").split())
                if not tags:
                    raise ValueError(
                        f"recipe {family}.exclude_allergens must name at "
                        f"least one allergen tag, got {value!r}"
                    )
                parsed[key] = ",".join(tags)
                continue
            if key == "tier" and value not in EVALUATE_TIERS:
                raise ValueError(
                    f"recipe {family}.tier must be one of "
                    f"{sorted(EVALUATE_TIERS)}, got {value!r}"
                )
            if key == "items" and (
                not value.isdigit() or int(value) < 1
            ):
                raise ValueError(
                    f"recipe {family}.items must be a positive integer, "
                    f"got {value!r}"
                )
            if key == "amount_path" and value not in _RECIPE_AMOUNT_PATHS:
                raise ValueError(
                    f"recipe {family}.amount_path must be one of "
                    f"{sorted(_RECIPE_AMOUNT_PATHS)}, got {value!r}"
                )
            if key == "person":
                # Fail-closed roster resolution: an unknown id or out-of-range
                # index never reaches the jobs.
                resolve_roster_person(value)
            parsed[str(key)] = value
        recipes[str(family)] = parsed
    return recipes


def _family_seed(seed: int, family: str) -> int:
    # Stable per-family stream so adding a family does not reshuffle another.
    return seed + (sum(ord(ch) for ch in family) * 1_000_003)


@dataclass
class _PoolJob:
    family: str
    pool: object
    model: str | None
    index: int
    recipe: Mapping[str, object] = field(default_factory=dict)


@dataclass
class _CandOut:
    query: str
    family: str
    task: Task | None
    resolve_reason: Rejected | None
    key: tuple[str, ...] | None
    implausible: bool
    draft_fail: bool
    semantic_fail: bool = False


@dataclass
class _PoolOut:
    family: str
    pool_id: str
    model: str | None
    schema_reject: bool
    cands: list[_CandOut]


def _parse_model_quotas(
    raw: object, total_quota: int
) -> list[tuple[str, int]] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("batch_spec.model_quotas must be a non-empty mapping")
    parsed: list[tuple[str, int]] = []
    total = 0
    for model, count in sorted(raw.items()):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("batch_spec.model_quotas keys must be model ids")
        n = int(count)
        if n < 0:
            raise ValueError(f"model quota for {model!r} must be >= 0")
        if n == 0:
            continue
        parsed.append((model.strip(), n))
        total += n
    if not parsed:
        raise ValueError("batch_spec.model_quotas must request at least one pool")
    if total != total_quota:
        raise ValueError(
            f"model_quotas sum {total} != family_quotas total {total_quota}"
        )
    return parsed


def _build_jobs(spec: Mapping, catalog) -> list[_PoolJob]:
    jobs: list[_PoolJob] = []
    for family, quota in spec["family_quotas"]:
        pools = sample_pools(
            catalog,
            seed=_family_seed(spec["seed"], family),
            family=family,
            n_pools=quota,
            with_allergen=(spec.get("family_recipes") or {}).get(family, {}).get(
                "pool_allergen"
            ),
        )
        recipe = (spec.get("family_recipes") or {}).get(family) or {}
        for pool in pools:
            jobs.append(
                _PoolJob(
                    family=family, pool=pool, model=None, index=len(jobs),
                    recipe=dict(recipe),
                )
            )
    quotas = spec.get("model_quotas")
    if quotas:
        assigned: list[str] = []
        for model, count in quotas:
            assigned.extend([model] * count)
        if len(assigned) != len(jobs):
            raise ValueError(
                f"model_quotas sum {len(assigned)} != sampled pools {len(jobs)}"
            )
        for job, model in zip(jobs, assigned, strict=True):
            job.model = model
    return jobs


def _bind_expanders(
    jobs: Sequence[_PoolJob],
    expander: Expander,
    seed: int,
    *,
    workers: int,
) -> dict[str | None, Expander]:
    bound: dict[str | None, Expander] = {None: expander}
    models = [job.model for job in jobs]
    if all(model is None for model in models):
        if (
            workers > 1
            and isinstance(expander, LlmExpander)
            and len(jobs) > 1
        ):
            for job in jobs:
                model = assign_model(job.index, expander._route, seed=expander._seed)
                job.model = model
            return _bind_expanders(jobs, expander, seed, workers=1)
        return bound
    for model in models:
        if model is None or model in bound:
            continue
        if isinstance(expander, LlmExpander):
            bound[model] = make_llm_expander(
                model_route=[model],
                seed=seed,
                complete=expander._complete,
                parse_retries=expander._parse_retries,
            )
        else:
            bound[model] = expander
    return bound


def _expand_one(
    job: _PoolJob, expander: Expander, persona: str
) -> tuple[_PoolJob, list]:
    recipe = job.recipe or {}
    # Expander hints vs Candidate stamps: items/amount_path/exclude_allergens
    # shape the query the expander produces; everything else is stamped onto
    # the Candidate.
    hints = {}
    for key, value in recipe.items():
        if key not in _EXPANDER_HINTS:
            continue
        if key == "items":
            hints[key] = int(value)
        elif key == "exclude_allergens":
            hints[key] = tuple(value.split(","))
        else:
            hints[key] = value
    if hints and expander is not synthetic_expander:
        # Fail closed: a real (LLM) run must not accept --recipe
        # items/amount_path and silently ignore them. LLM prompt shells are
        # issue-15 design; knife/tier recipes keep working everywhere.
        raise ValueError(_HINTS_NEED_SYNTHETIC)
    if "knife" in recipe and expander is synthetic_expander:
        # The knife branch derives its windows from the spoken "for <meal>"
        # clause; recipe-free drafts keep the historical phrasing. LLM
        # queries speak occasions naturally (prompt-shell design).
        hints["occasion"] = "dinner"
    raw = expander(job.pool, persona=persona, family=job.family, **hints)
    candidates = coerce_candidates(
        raw, family=job.family, persona=persona, pool_id=job.pool.pool_id
    )
    stamps = {
        key: value
        for key, value in recipe.items()
        if key not in _EXPANDER_HINTS and key != "pool_allergen"
    }
    if stamps:
        candidates = [replace(candidate, **stamps) for candidate in candidates]
    return job, candidates


def _vote_candidate(
    candidate,
    catalog,
    voter,
    *,
    k: int,
    threshold: float,
    models: tuple[str, ...],
    temperature: float,
    max_tokens: int,
    pool=None,
) -> bool:
    """Soft semantic vote plus generation-only phrasing band. Oracle untouched."""
    index = build_food_index(catalog)
    for spoken, expression in candidate.items:
        food_id = match_spoken(spoken, catalog, index, pool)
        if food_id is None:
            return False
        grams = resolve_portion(food_id, expression, catalog)
        if grams is None:
            return False
        accepted, _source = semantic_vote(
            candidate.query,
            food=spoken,
            expression=expression,
            voter=voter,
            k=k,
            threshold=threshold,
            models=models,
            temperature=temperature,
            max_tokens=max_tokens,
            oracle_grams=float(grams),
            catalog=catalog,
            food_id=food_id,
        )
        if not accepted:
            return False
    return True


def _finish_one(
    job: _PoolJob,
    tagged: Sequence[tuple[object, str]],
    *,
    catalog,
    food_index: Mapping[str, str],
    judge: Judge,
    skip_gram_backresolve: bool = False,
    voter=None,
    vote_k: int = DEFAULT_K,
    vote_threshold: float = DEFAULT_THRESHOLD,
    vote_models: tuple[str, ...] = DEFAULT_MODEL_IDS,
    vote_temperature: float = TEMPERATURE,
    vote_max_tokens: int = MAX_TOKENS,
    enable_semantic_vote: bool | None = None,
) -> _PoolOut:
    if not tagged:
        return _PoolOut(
            family=job.family,
            pool_id=job.pool.pool_id,
            model=job.model,
            schema_reject=True,
            cands=[],
        )
    local_seen: set[tuple[str, ...]] = set()
    cands: list[_CandOut] = []
    for candidate, task_id in tagged:
        before = set(local_seen)
        vote_on = (
            enable_semantic_vote if enable_semantic_vote is not None else voter is not None
        )
        task, reason = resolve_candidate(
            candidate,
            catalog=catalog,
            task_id=task_id,
            seen=local_seen,
            food_index=food_index,
            skip_gram_backresolve=skip_gram_backresolve or vote_on,
            pool=job.pool,
        )
        occupied = local_seen - before
        key = next(iter(occupied), None)
        implausible = False
        draft_fail = False
        semantic_fail = False
        if reason is None and task is not None:
            if vote_on and not _vote_candidate(
                candidate,
                catalog,
                voter,
                k=vote_k,
                threshold=vote_threshold,
                models=vote_models,
                temperature=vote_temperature,
                max_tokens=vote_max_tokens,
                pool=job.pool,
            ):
                semantic_fail = True
            elif _implausible(task, catalog, judge):
                implausible = True
            else:
                draft_issues = list(validate_draft(task))
                if vote_on:
                    # The semantic vote is the speech gate when it is on;
                    # validate_draft may still fail "not mentioned" for a
                    # rewritten query that the vote accepted.
                    draft_issues = [
                        issue
                        for issue in draft_issues
                        if "not mentioned in the query" not in issue
                    ]
                if draft_issues:
                    draft_fail = True
        cands.append(
            _CandOut(
                query=candidate.query,
                family=job.family,
                task=task,
                resolve_reason=reason,
                key=key,
                implausible=implausible,
                draft_fail=draft_fail,
                semantic_fail=semantic_fail,
            )
        )
    return _PoolOut(
        family=job.family,
        pool_id=job.pool.pool_id,
        model=job.model,
        schema_reject=False,
        cands=cands,
    )


def _assign_task_ids(
    expanded: Sequence[tuple[_PoolJob, list]],
    *,
    prefix: str,
    start_seq: int,
) -> list[tuple[_PoolJob, list[tuple[object, str]]]]:
    seq = start_seq
    planned: list[tuple[_PoolJob, list[tuple[object, str]]]] = []
    for job, candidates in expanded:
        tagged: list[tuple[object, str]] = []
        for candidate in candidates:
            tagged.append((candidate, f"{prefix}-{job.family}-{seq:04d}"))
            seq += 1
        planned.append((job, tagged))
    return planned


def _assemble(
    pool_outs: Sequence[_PoolOut],
) -> tuple[list[Task], list[Rejected], dict[str, object]]:
    seen: set[tuple[str, ...]] = set()
    accepted: list[Task] = []
    rejected: list[Rejected] = []
    model_accepted: dict[str, int] = {}
    model_pools: dict[str, list[str]] = {}
    n_candidates = 0
    for pool_out in pool_outs:
        if pool_out.model is not None:
            model_pools.setdefault(pool_out.model, []).append(pool_out.pool_id)
        if pool_out.schema_reject:
            rejected.append(Rejected("", "schema", pool_out.family))
            continue
        n_candidates += len(pool_out.cands)
        for item in pool_out.cands:
            if item.key is not None:
                if item.key in seen:
                    rejected.append(Rejected(item.query, "duplicate", item.family))
                    continue
                seen.add(item.key)
            if item.resolve_reason is not None:
                rejected.append(item.resolve_reason)
                continue
            if item.implausible:
                rejected.append(Rejected(item.query, "implausible", item.family))
                continue
            if item.semantic_fail:
                rejected.append(Rejected(item.query, "semantic", item.family))
                continue
            if item.draft_fail:
                rejected.append(Rejected(item.query, "validate_draft", item.family))
                continue
            if item.task is None:
                rejected.append(Rejected(item.query, "unresolvable", item.family))
                continue
            accepted.append(item.task)
            if pool_out.model is not None:
                model_accepted[pool_out.model] = model_accepted.get(pool_out.model, 0) + 1
    return (
        accepted,
        rejected,
        {
            "model_pools": model_pools,
            "model_accepted": model_accepted,
            "n_pools": len(pool_outs),
            "n_candidates": n_candidates,
        },
    )


def _run_jobs(
    jobs: Sequence[_PoolJob],
    *,
    expanders: Mapping[str | None, Expander],
    persona: str,
    catalog,
    food_index: Mapping[str, str],
    judge: Judge,
    prefix: str,
    start_seq: int,
    skip_gram_backresolve: bool = False,
    voter=None,
    vote_k: int = DEFAULT_K,
    vote_threshold: float = DEFAULT_THRESHOLD,
    vote_models: tuple[str, ...] = DEFAULT_MODEL_IDS,
    vote_temperature: float = TEMPERATURE,
    vote_max_tokens: int = MAX_TOKENS,
    enable_semantic_vote: bool | None = None,
    workers: int,
) -> tuple[list[Task], list[Rejected], dict[str, object]]:
    if workers == 1:
        expanded = [
            _expand_one(job, expanders[job.model], persona) for job in jobs
        ]
        planned = _assign_task_ids(expanded, prefix=prefix, start_seq=start_seq)
        finished = [
            _finish_one(
                job,
                tagged,
                catalog=catalog,
                food_index=food_index,
                judge=judge,
                skip_gram_backresolve=skip_gram_backresolve,
                voter=voter,
                vote_k=vote_k,
                vote_threshold=vote_threshold,
                vote_models=vote_models,
                vote_temperature=vote_temperature,
                vote_max_tokens=vote_max_tokens,
                enable_semantic_vote=enable_semantic_vote,
            )
            for job, tagged in planned
        ]
        return _assemble(finished)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        expand_futures = [
            pool.submit(_expand_one, job, expanders[job.model], persona)
            for job in jobs
        ]
        expanded = [future.result() for future in expand_futures]
        planned = _assign_task_ids(expanded, prefix=prefix, start_seq=start_seq)
        finish_futures = [
            pool.submit(
                _finish_one,
                job,
                tagged,
                catalog=catalog,
                food_index=food_index,
                judge=judge,
                skip_gram_backresolve=skip_gram_backresolve,
                voter=voter,
                vote_k=vote_k,
                vote_threshold=vote_threshold,
                vote_models=vote_models,
                vote_temperature=vote_temperature,
                vote_max_tokens=vote_max_tokens,
                enable_semantic_vote=enable_semantic_vote,
            )
            for job, tagged in planned
        ]
        finished = [future.result() for future in finish_futures]
    return _assemble(finished)


if __name__ == "__main__":
    result = write_tracer_sample()
    print(f"wrote {result.path}: {len(result.accepted)} items")
