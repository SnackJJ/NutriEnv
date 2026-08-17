"""Serialize surviving Tasks to a frozen split after oracle-gram validation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from nutrienv.bench.realize import Task
from nutrienv.bench.validator import validate_oracle_grams

from .types import (
    CATALOG_V1_RELPATH,
    DEFAULT_FREEZE_RELPATH,
    PIPELINE_VERSION,
    catalog_digest,
    repo_root,
)

__all__ = ["freeze_tasks", "task_to_item"]


def freeze_tasks(
    tasks: Sequence[Task],
    *,
    catalog,
    catalog_field: str = CATALOG_V1_RELPATH,
    catalog_sha: str | None = None,
    output_path: Path | str | None = None,
    extra: Mapping[str, object] | None = None,
) -> tuple[dict, Path]:
    """Validate oracle grams, then write a deterministic frozen payload."""
    if not tasks:
        raise ValueError("freeze requires a non-empty task list")
    issues = [
        f"{task.id}: {issue}"
        for task in tasks
        for issue in validate_oracle_grams(task)
    ]
    if issues:
        raise ValueError("oracle grams gate failed:\n" + "\n".join(issues))

    digest = catalog_sha if catalog_sha is not None else catalog_digest(catalog)
    payload: dict[str, object] = {
        "version": PIPELINE_VERSION,
        "catalog": catalog_field,
        "catalog_sha256": digest,
        "items": [task_to_item(task) for task in tasks],
    }
    if extra:
        payload.update(extra)

    target = Path(output_path) if output_path is not None else repo_root() / DEFAULT_FREEZE_RELPATH
    if not target.is_absolute():
        target = repo_root() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload, target


def task_to_item(task: Task) -> dict:
    profile = {
        "user_id": task.s0.profile.user_id,
        "allergies": list(task.s0.profile.allergies),
        "windows": {
            key: list(bounds) for key, bounds in task.s0.profile.windows.items()
        },
    }
    if task.s0.profile.plan_preset:
        profile["plan_preset"] = dict(task.s0.profile.plan_preset)
    s0: dict[str, object] = {
        "profile": profile,
        "ledger": [
            {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at}
            for row in task.s0.ledger
        ],
    }
    if task.s0.last_plan:
        s0["last_plan"] = [
            {"food_id": item["food_id"], "grams": item["grams"]}
            for item in task.s0.last_plan
        ]

    oracle: dict[str, object] = {"profile": "s0"}
    if task.family == "evaluate":
        oracle["last_plan"] = [
            {"food_id": item["food_id"], "grams": item["grams"]}
            for item in (task.oracle.last_plan or [])
        ]
        oracle["plan_must_fit_windows"] = True
        oracle["ledger"] = "s0"
    else:
        oracle["ledger_tail"] = [
            {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at}
            for row in (task.oracle.ledger_tail or [])
        ]
        oracle["ledger"] = "s0_plus_tail"

    return {
        "id": task.id,
        "family": task.family,
        "persona": task.persona,
        "situations": list(task.situations),
        "query": task.query,
        "s0": s0,
        "oracle": oracle,
    }
