"""Serialize surviving Tasks to a frozen split after oracle-gram validation."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from dataclasses import replace

from nutrienv.bench.realize import Oracle, Task, scored_oracles
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
    overwrite: bool = False,
) -> tuple[dict, Path]:
    """Validate oracle grams, then write a deterministic frozen payload."""
    if not tasks:
        raise ValueError("freeze requires a non-empty task list")
    issues = [
        f"{task.id}: {issue}"
        for task in tasks
        for issue in _oracle_gram_issues(task)
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
    blob = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if target.exists() and not overwrite and target.read_bytes() != blob.encode("utf-8"):
        raise FileExistsError(
            f"refusing to overwrite existing frozen split {target} "
            "(pass overwrite=True)"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(blob, encoding="utf-8")
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
    body = task.s0.profile
    for key in ("sex", "age_y", "height_cm", "weight_kg", "activity"):
        value = getattr(body, key)
        if value is not None:
            profile[key] = value
    if body.phase != "maintain":
        profile["phase"] = body.phase
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

    item = {
        "id": task.id,
        "family": task.family,
        "persona": task.persona,
        "situations": list(task.situations),
        "query": task.query,
        "s0": s0,
        "oracle": _oracle_payload(task.oracle, family=task.family, s0=task.s0),
    }
    # Declared tiers round-trip; omitting the empty default keeps rebuilds
    # of tierless archives byte-identical.
    if task.tier:
        item["tier"] = task.tier
    return item


def _oracle_gram_issues(task: Task) -> list[str]:
    issues: list[str] = []
    for oracle in scored_oracles(task.oracle):
        issues.extend(validate_oracle_grams(replace(task, oracle=oracle)))
    return issues


def _oracle_payload(oracle: Oracle, *, family: str, s0) -> dict[str, object]:
    if oracle.sub_oracles:
        # Parent fields are unused (compose_oracles); serializing a "profile"
        # here would resurrect one on load and break round-trip identity.
        return {
            "sub_oracles": [
                _oracle_payload(sub, family=_sub_family(sub), s0=s0)
                for sub in oracle.sub_oracles
            ],
        }
    payload: dict[str, object] = {}
    prof_payload = _oracle_profile_payload(oracle.profile, s0.profile)
    if prof_payload is not None:
        payload["profile"] = prof_payload
    if family == "evaluate" or (
        oracle.last_plan is not None and oracle.ledger_tail is None
    ):
        payload["last_plan"] = [
            {"food_id": item["food_id"], "grams": item["grams"]}
            for item in (oracle.last_plan or [])
        ]
        _attach_plan_flags(payload, oracle)
        if oracle.plan_windows:
            payload["plan_windows"] = {
                key: list(bounds) for key, bounds in oracle.plan_windows.items()
            }
        _attach_verdict(payload, oracle)
        _attach_update_band(payload, oracle)
        _attach_evaluated_plan(payload, oracle)
        payload["ledger"] = _ledger_payload(oracle.ledger, s0)
        return payload
    if oracle.ledger_tail is not None:
        payload["ledger_tail"] = [
            {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at}
            for row in oracle.ledger_tail
        ]
        payload["ledger"] = "s0_plus_tail"
    if oracle.last_plan is not None:
        payload["last_plan"] = [
            {"food_id": item["food_id"], "grams": item["grams"]}
            for item in oracle.last_plan
        ]
    _attach_plan_flags(payload, oracle)
    if oracle.plan_windows:
        payload["plan_windows"] = {
            key: list(bounds) for key, bounds in oracle.plan_windows.items()
        }
    _attach_verdict(payload, oracle)
    _attach_update_band(payload, oracle)
    _attach_evaluated_plan(payload, oracle)
    if "ledger" not in payload and oracle.ledger is not None:
        payload["ledger"] = _ledger_payload(oracle.ledger, s0)
    return payload


def _ledger_payload(ledger, s0) -> object:
    """'s0' when the ledger equals S0's, else the explicit row list.

    A composite update child carries ``ledger=()``; dropping the key would
    load as ``None`` and fail validate_draft's "update oracle ledger is
    missing" gate on reload.
    """
    if tuple(ledger or ()) == tuple(s0.ledger):
        return "s0"
    return [
        {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at}
        for row in (ledger or ())
    ]


def _attach_plan_flags(payload: dict[str, object], oracle: Oracle) -> None:
    if oracle.last_verdict == "reject":
        return
    if oracle.plan_must_be_safe:
        payload["plan_must_be_safe"] = True
    if oracle.plan_must_fit_windows:
        payload["plan_must_fit_windows"] = True
    if oracle.allow_empty_plan:
        payload["allow_empty_plan"] = True


def _attach_verdict(payload: dict[str, object], oracle: Oracle) -> None:
    if oracle.last_verdict is not None:
        payload["last_verdict"] = oracle.last_verdict
    if oracle.last_verdict == "reject":
        payload["last_reasons"] = list(oracle.last_reasons)


def _attach_update_band(payload: dict[str, object], oracle: Oracle) -> None:
    if oracle.update_band:
        payload["update_band"] = oracle.update_band


def _attach_evaluated_plan(payload: dict[str, object], oracle: Oracle) -> None:
    if oracle.evaluated_plan:
        payload["evaluated_plan"] = [
            {"food_id": item["food_id"], "grams": item["grams"]}
            for item in oracle.evaluated_plan
        ]
    if oracle.bound_labels:
        payload["bound_labels"] = list(oracle.bound_labels)


def _oracle_profile_payload(oracle_profile, s0_profile) -> object:
    if oracle_profile is None:
        return None
    if oracle_profile == s0_profile:
        return "s0"
    diff: dict[str, object] = {}
    if oracle_profile.allergies != s0_profile.allergies:
        diff["allergies"] = list(oracle_profile.allergies)
    if oracle_profile.medications != s0_profile.medications:
        diff["medications"] = list(oracle_profile.medications)
    if oracle_profile.plan_preset != s0_profile.plan_preset:
        diff["plan_preset"] = copy.deepcopy(oracle_profile.plan_preset)
    if oracle_profile.version != s0_profile.version:
        diff["version"] = oracle_profile.version
    moved = {
        key: list(bounds)
        for key, bounds in oracle_profile.windows.items()
        if s0_profile.windows.get(key) != bounds
    }
    if moved:
        diff["windows"] = moved
    for key in ("sex", "age_y", "height_cm", "weight_kg", "activity", "phase"):
        value = getattr(oracle_profile, key)
        if value != getattr(s0_profile, key):
            diff[key] = value
    return diff if diff else "s0"


def _sub_family(oracle: Oracle) -> str:
    if oracle.last_verdict == "reject":
        return "evaluate"
    if oracle.last_plan is not None and oracle.ledger_tail is None:
        return "evaluate" if oracle.last_plan else "recommend"
    if oracle.last_plan == []:
        return "recommend"
    if oracle.last_plan:
        return "evaluate"
    return "log"
