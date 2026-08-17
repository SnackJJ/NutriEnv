"""Single entry: Sampler → Expander → Resolver → Judge → validate_draft → Review → Freezer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from nutrienv.bench.grams_gate import plausibility_gate
from nutrienv.bench.realize import Task, scored_oracles
from nutrienv.bench.validator import fitting_plan, validate_draft
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.types import ledger_totals

from .expander import coerce_candidates, synthetic_expander
from .freezer import freeze_tasks
from .resolver import build_food_index, resolve_candidate
from .sampler import sample_pools
from .types import (
    BASE_EXAM_QUOTA,
    CATALOG_V1_RELPATH,
    COMPOSITE_EXTRA_QUOTA,
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


def pass_through_reviewer(candidates: Sequence[Task]) -> dict:
    """06 placeholder: accept everything, return the required summary shape."""
    return {
        "anomalies": [],
        "per_candidate": {task.id: {} for task in candidates},
    }


def run_batch(
    batch_spec: Mapping,
    *,
    expander: Expander,
    judge: Judge,
    reviewer: Reviewer,
    catalog,
) -> BatchResult:
    """Run the candidate pipeline. LLM roles must be injected; no network."""
    if expander is None or judge is None or reviewer is None:
        raise ValueError("expander, judge, and reviewer must be injected")
    spec = _parse_spec(batch_spec)
    digest = catalog_digest(catalog)
    if digest != spec["catalog_sha"]:
        raise ValueError(
            f"catalog sha256 mismatch: catalog={digest} spec={spec['catalog_sha']}"
        )

    persona = spec["persona"]
    rejected: list[Rejected] = []
    accepted: list[Task] = []
    seen: set[tuple[str, ...]] = set()
    food_index = build_food_index(catalog)
    seq = 0

    for family, quota in spec["family_quotas"]:
        pools = sample_pools(
            catalog,
            seed=_family_seed(spec["seed"], family),
            family=family,
            n_pools=quota,
        )
        for pool in pools:
            raw = expander(pool, persona=persona, family=family)
            candidates = coerce_candidates(
                raw, family=family, persona=persona, pool_id=pool.pool_id
            )
            if not candidates:
                rejected.append(Rejected("", "schema", family))
                continue
            for candidate in candidates:
                seq += 1
                task_id = f"v10-{family}-{seq:04d}"
                task, reason = resolve_candidate(
                    candidate,
                    catalog=catalog,
                    task_id=task_id,
                    seen=seen,
                    food_index=food_index,
                )
                if reason is not None:
                    rejected.append(reason)
                    continue
                if _implausible(task, catalog, judge):
                    rejected.append(Rejected(candidate.query, "implausible", family))
                    continue
                draft_issues = list(validate_draft(task))
                draft_issues.extend(_composite_draft_issues(task))
                if draft_issues:
                    rejected.append(Rejected(candidate.query, "validate_draft", family))
                    continue
                accepted.append(task)

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
        )

    payload, path = freeze_tasks(
        accepted,
        catalog=catalog,
        catalog_field=spec["catalog_field"],
        catalog_sha=digest,
        output_path=spec["output_path"],
        extra=extra,
    )
    return BatchResult(
        payload=payload,
        path=path,
        accepted=accepted,
        rejected=rejected,
        review=review,
    )


def write_composite_sample(
    *,
    output_path: Path | str | None = None,
    n: int = 2,
) -> BatchResult:
    """Freeze a small composite sample against catalog-v1. Does not replace v1.0-gold."""
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
        "version": "v1.0-composite-sample",
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
    """Base 240 vs composite extra, counted separately (ADR 0013)."""
    base_accepted: dict[str, int] = {}
    composite_accepted = 0
    for task in accepted:
        if task.oracle.sub_oracles:
            composite_accepted += 1
            continue
        base_accepted[task.family] = base_accepted.get(task.family, 0) + 1
    return {
        "base_quota": BASE_EXAM_QUOTA,
        "composite_extra_quota": COMPOSITE_EXTRA_QUOTA,
        "base_accepted": base_accepted,
        "composite_accepted": composite_accepted,
        "requested": {family: count for family, count in family_quotas},
    }


def write_tracer_sample(
    *,
    output_path: Path | str | None = None,
    n_log: int = 3,
) -> BatchResult:
    """Freeze a small synthetic v1.0-gold sample against catalog-v1."""
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


def _composite_draft_issues(task: Task) -> list[str]:
    if not task.oracle.sub_oracles:
        return []
    issues: list[str] = []
    tail: list = []
    for sub in task.oracle.sub_oracles:
        if sub.ledger_tail:
            tail = list(sub.ledger_tail)
            break
    eaten = ledger_totals([*task.s0.ledger, *tail], task.s0.catalog)
    for sub in task.oracle.sub_oracles:
        if sub.last_plan != [] or not sub.plan_must_fit_windows:
            continue
        if sub.plan_windows:
            for key, (lo, hi) in task.s0.profile.windows.items():
                used = eaten.get(key, 0.0)
                expected = (
                    round(max(0.0, lo - used), 2),
                    round(max(0.0, hi - used), 2),
                )
                if sub.plan_windows.get(key) != expected:
                    issues.append(f"composite plan_windows {key} != remainder {expected}")
        windows = sub.plan_windows or task.s0.profile.windows
        if fitting_plan(task.s0.catalog, windows, task.s0.profile.allergies) is None:
            issues.append("composite recommend is unpassable")
    return issues


def _parse_spec(batch_spec: Mapping) -> dict:
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
    return {
        "seed": int(batch_spec["seed"]),
        "catalog_sha": str(batch_spec["catalog_sha"]),
        "persona": persona,
        "family_quotas": quotas,
        "sampler_rule_version": rule,
        "output_path": output_path,
        "catalog_field": catalog_field,
        "version": version,
    }


def _family_seed(seed: int, family: str) -> int:
    # Stable per-family stream so adding a family does not reshuffle another.
    return seed + (sum(ord(ch) for ch in family) * 1_000_003)


if __name__ == "__main__":
    result = write_tracer_sample()
    print(f"wrote {result.path}: {len(result.accepted)} items")
