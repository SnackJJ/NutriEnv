"""Load a frozen Task split. This file is the published exam."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from nutrienv.world.catalog import canonical_food_id
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.daily_windows import UPDATE_BANDS, derive_profile_windows
from nutrienv.world.types import (
    PHASES,
    LedgerRow,
    Profile,
    WorldState,
    normalize_reasons,
    normalize_tags,
    normalize_window,
)

from .quality_gates import EVALUATE_TIERS
from .realize import FAMILIES, Oracle, Task
from .situations import SITUATIONS

__all__ = ["GOLD_SPLIT_PATH", "EXAM_SPLIT_PATH", "load_split", "load_exam"]

_ROOT = Path(__file__).resolve().parents[3]
# Archived v0 calibration set; kept for archaeology through load_split.
GOLD_SPLIT_PATH = _ROOT / "data" / "splits" / "archive" / "v0-gold.json"
# Published issue-15 exam: a 240-item split built against catalog-v2 and
# admitted by scripts/verify_issue15.py (14 assertions PASS). v0.5-gold
# remains archived and load_exam rejects it by version.
EXAM_SPLIT_PATH = _ROOT / "data" / "splits" / "v2.0-gold.json"
_EXAM_VERSIONS = frozenset({"v2.0-gold"})


def load_split(path: Path | str | None = None, *, catalog=None) -> list[Task]:
    """Read a frozen JSON split and attach a catalog to every S0.

    ``catalog=None`` prefers the split's recorded ``catalog`` path when the
    payload has one, so frozen increments stay bound to the catalog they were
    authored against. If the payload records no catalog, the active default
    catalog (:func:`load_catalog` with no path) is used. Pass a catalog object
    when the caller has already resolved and verified the file that must be
    attached.
    """
    target = Path(path) if path is not None else EXAM_SPLIT_PATH
    if not target.is_file():
        raise FileNotFoundError(f"split not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("split must contain a non-empty items list")
    if catalog is None:
        catalog_field = payload.get("catalog") if isinstance(payload, dict) else None
        if isinstance(catalog_field, str) and catalog_field:
            catalog_path = Path(catalog_field)
            if not catalog_path.is_absolute():
                catalog_path = _ROOT / catalog_field
            catalog = load_catalog(catalog_path)
        else:
            catalog = load_catalog()
    return [_item(entry, catalog) for entry in items]


def load_exam(path: Path | str | None = None) -> list[Task]:
    """Load the published 240-item exam. Fail closed on catalog identity.

    Unlike :func:`load_split`, this checks ``version``, a non-empty ``items``
    list, that the recorded catalog file exists (resolved from the repo root)
    and is a ``.sqlite`` file (``load_catalog`` would otherwise silently fall
    back to the demo fixture), and that ``sha256(catalog bytes)`` matches
    ``catalog_sha256``. The verified catalog file is the one attached to
    every Task.
    """
    target = Path(path) if path is not None else EXAM_SPLIT_PATH
    if not target.is_file():
        raise FileNotFoundError(f"exam split not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("exam payload must be an object")
    version = payload.get("version")
    if version not in _EXAM_VERSIONS:
        raise ValueError(
            f"exam version must be one of {sorted(_EXAM_VERSIONS)}, got {version!r}"
        )
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("exam must contain a non-empty items list")
    catalog_field = payload.get("catalog")
    digest_field = payload.get("catalog_sha256")
    if not isinstance(catalog_field, str) or not catalog_field:
        raise ValueError("exam catalog field is missing")
    if not isinstance(digest_field, str) or not digest_field:
        raise ValueError("exam catalog_sha256 field is missing")
    catalog_path = Path(catalog_field)
    if not catalog_path.is_absolute():
        catalog_path = _ROOT / catalog_field
    if not catalog_path.is_file():
        raise FileNotFoundError(f"exam catalog not found: {catalog_path}")
    if catalog_path.suffix != ".sqlite":
        raise ValueError(
            f"exam catalog must be a .sqlite file, got: {catalog_path}"
        )
    digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    if digest != digest_field:
        raise ValueError(
            f"exam catalog sha256 mismatch: file={digest} split={digest_field}"
        )
    catalog = load_catalog(catalog_path)
    return load_split(target, catalog=catalog)


def _item(entry: object, catalog: dict) -> Task:
    if not isinstance(entry, dict):
        raise ValueError("split item must be an object")
    task_id = entry.get("id")
    family = entry.get("family")
    query = entry.get("query")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("item.id must be a non-empty string")
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}")
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"{task_id}: query must be a non-empty string")
    situations = _situations(entry.get("situations"))
    persona = entry.get("persona") or ""
    if not isinstance(persona, str):
        raise ValueError(f"{task_id}: persona must be a string")
    declared_tier = entry.get("tier")
    if declared_tier is not None and (
        not isinstance(declared_tier, str)
        or (declared_tier and declared_tier not in EVALUATE_TIERS)
    ):
        raise ValueError(
            f"{task_id}: tier must be empty or one of {sorted(EVALUATE_TIERS)}"
        )
    tier = declared_tier or ""
    s0 = _s0(entry.get("s0"), catalog)
    oracle = _oracle(entry.get("oracle"), s0, catalog)
    return Task(task_id, family, query.strip(), s0, oracle, situations, persona, tier)


def _situations(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise ValueError("situations must be a list of strings")
    unknown = [name for name in value if name not in SITUATIONS]
    if unknown:
        raise ValueError(f"unknown situations: {unknown}")
    return tuple(value)


def _s0(value: object, catalog: dict) -> WorldState:
    if not isinstance(value, dict):
        raise ValueError("item.s0 must be an object")
    profile = _profile(value.get("profile"), default_user="gold-user")
    ledger = [_row(row, catalog) for row in value.get("ledger") or []]
    raw_plan = value.get("last_plan") or []
    if not isinstance(raw_plan, list):
        raise ValueError("s0.last_plan must be a list")
    last_plan = [_plan_item(item, catalog) for item in raw_plan]
    return WorldState(
        profile=profile,
        ledger=ledger,
        catalog=copy.deepcopy(catalog),
        last_plan=last_plan,
    )


def _profile(value: object, *, default_user: str) -> Profile:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("profile must be an object")
    windows_raw = value.get("windows") or {}
    if not isinstance(windows_raw, dict):
        raise ValueError("windows must be an object")
    windows = {str(key): normalize_window(bounds) for key, bounds in windows_raw.items()}
    age_y = value.get("age_y")
    height_cm = value.get("height_cm")
    weight_kg = value.get("weight_kg")
    return Profile(
        user_id=str(value.get("user_id") or default_user),
        allergies=normalize_tags(value.get("allergies") or []),
        medications=normalize_tags(value.get("medications") or []),
        windows=windows,
        plan_preset=copy.deepcopy(value.get("plan_preset") or {}),
        version=int(value.get("version") or 1),
        sex=value.get("sex"),
        age_y=None if age_y is None else int(age_y),
        height_cm=None if height_cm is None else float(height_cm),
        weight_kg=None if weight_kg is None else float(weight_kg),
        activity=value.get("activity"),
        phase=_phase(value),
    )


def _phase(value: dict) -> str:
    if "phase" not in value:
        return "maintain"
    phase = value["phase"]
    if phase not in PHASES:
        raise ValueError("phase must be 'maintain', 'cut', or 'muscle'")
    return phase


def _row(value: object, catalog: object) -> LedgerRow:
    if not isinstance(value, dict):
        raise ValueError("ledger row must be an object")
    return LedgerRow(
        canonical_food_id(catalog, str(value["food_id"])),
        float(value["grams"]),
        str(value["eaten_at"]),
    )


def _plan_item(value: object, catalog: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("plan item must be an object")
    item = copy.deepcopy(value)
    if "food_id" in item:
        item["food_id"] = canonical_food_id(catalog, str(item["food_id"]))
    return item


def _oracle(value: object, s0: WorldState, catalog: object, *, allow_subs: bool = True) -> Oracle:
    if value is None:
        return Oracle()
    if not isinstance(value, dict):
        raise ValueError("oracle must be an object")
    update_band = value.get("update_band")
    if update_band is not None and update_band not in UPDATE_BANDS:
        raise ValueError("oracle.update_band must be 'cut', 'fatigue', or 'muscle'")

    profile_spec = value.get("profile")
    if profile_spec is None:
        profile = None
    elif profile_spec == "s0":
        profile = copy.deepcopy(s0.profile)
    elif isinstance(profile_spec, dict):
        merged = {
            "user_id": s0.profile.user_id,
            "allergies": list(s0.profile.allergies),
            "medications": list(s0.profile.medications),
            "windows": {key: list(bounds) for key, bounds in s0.profile.windows.items()},
            "plan_preset": copy.deepcopy(s0.profile.plan_preset),
            "version": s0.profile.version,
            "sex": s0.profile.sex,
            "age_y": s0.profile.age_y,
            "height_cm": s0.profile.height_cm,
            "weight_kg": s0.profile.weight_kg,
            "activity": s0.profile.activity,
            "phase": s0.profile.phase,
        }
        if "allergies" in profile_spec:
            merged["allergies"] = profile_spec["allergies"]
        if "medications" in profile_spec:
            merged["medications"] = profile_spec["medications"]
        if "windows" in profile_spec:
            windows = dict(merged["windows"])
            windows.update(profile_spec["windows"])
            merged["windows"] = windows
        if "plan_preset" in profile_spec:
            merged["plan_preset"] = profile_spec["plan_preset"]
        for key in ("sex", "age_y", "height_cm", "weight_kg", "activity", "phase"):
            if key in profile_spec:
                merged[key] = profile_spec[key]
        profile = _profile(merged, default_user=s0.profile.user_id)
        if not update_band and any(
            key in profile_spec
            for key in ("sex", "age_y", "height_cm", "weight_kg", "activity", "phase")
        ):
            derived = derive_profile_windows(profile)
            if derived is not None:
                profile = replace(profile, windows=derived)
    else:
        raise ValueError("oracle.profile must be omitted, 's0', or an object")

    if update_band:
        # A band oracle's windows are S0's: the exact baseline for non-band
        # keys, and for fatigue the floor the end state must rise above.
        # Re-deriving or naming them compares the end state against itself.
        if profile is None:
            raise ValueError("oracle.update_band requires oracle.profile")
        if profile.windows != s0.profile.windows:
            raise ValueError(
                "oracle.update_band keeps S0 windows as the band baseline; "
                "the oracle profile must not name or re-derive windows"
            )

    tail_raw = value.get("ledger_tail")
    ledger_tail = None if tail_raw is None else [_row(row, catalog) for row in tail_raw]

    ledger = None
    ledger_spec = value.get("ledger")
    if ledger_spec == "s0":
        ledger = tuple(s0.ledger)
    elif ledger_spec == "s0_plus_tail":
        if ledger_tail is None:
            raise ValueError("oracle.ledger s0_plus_tail requires ledger_tail")
        ledger = (*s0.ledger, *ledger_tail)
    elif ledger_spec is not None:
        if not isinstance(ledger_spec, list):
            raise ValueError("oracle.ledger must be omitted, 's0', 's0_plus_tail', or a list")
        ledger = tuple(_row(row, catalog) for row in ledger_spec)

    last_plan = value["last_plan"] if "last_plan" in value else None
    if last_plan is not None and not isinstance(last_plan, list):
        raise ValueError("oracle.last_plan must be a list or omitted")
    if last_plan is not None:
        last_plan = [_plan_item(item, catalog) for item in last_plan]

    evaluated_plan = value.get("evaluated_plan")
    if evaluated_plan is not None:
        if not isinstance(evaluated_plan, list):
            raise ValueError("oracle.evaluated_plan must be a list or omitted")
        evaluated_plan = [_plan_item(item, catalog) for item in evaluated_plan]

    plan_windows = None
    raw_windows = value.get("plan_windows")
    if raw_windows is not None:
        if not isinstance(raw_windows, dict):
            raise ValueError("oracle.plan_windows must be an object")
        plan_windows = {
            str(key): normalize_window(bounds) for key, bounds in raw_windows.items()
        }

    sub_oracles = None
    sub_raw = value.get("sub_oracles")
    if sub_raw is not None:
        if not allow_subs:
            raise ValueError("nested sub_oracles are not allowed")
        if not isinstance(sub_raw, list) or len(sub_raw) < 2:
            raise ValueError("oracle.sub_oracles must be a list of at least 2 oracles")
        sub_oracles = tuple(
            _oracle(item, s0, catalog, allow_subs=False) for item in sub_raw
        )

    last_verdict = value.get("last_verdict")
    if last_verdict is not None and last_verdict not in {"accept", "reject"}:
        raise ValueError("oracle.last_verdict must be omitted, 'accept', or 'reject'")
    last_reasons = ()
    if "last_reasons" in value:
        last_reasons = normalize_reasons(value["last_reasons"])
    if last_verdict != "reject" and last_reasons:
        raise ValueError("oracle.last_reasons require last_verdict 'reject'")
    plan_must_be_safe = bool(value.get("plan_must_be_safe", False))
    plan_must_fit_windows = bool(value.get("plan_must_fit_windows", False))
    allow_empty_plan = bool(value.get("allow_empty_plan", False))
    if last_verdict == "reject":
        if plan_must_fit_windows:
            raise ValueError("reject oracle must not set plan_must_fit_windows")
        if allow_empty_plan:
            raise ValueError("reject oracle must not set allow_empty_plan")

    return Oracle(
        profile=profile,
        last_plan=copy.deepcopy(last_plan) if last_plan is not None else None,
        ledger_tail=ledger_tail,
        ledger=ledger,
        plan_must_be_safe=plan_must_be_safe,
        plan_must_fit_windows=plan_must_fit_windows,
        allow_empty_plan=allow_empty_plan,
        plan_windows=plan_windows,
        last_verdict=last_verdict,
        last_reasons=last_reasons,
        update_band=update_band,
        evaluated_plan=evaluated_plan,
        bound_labels=_bound_labels(value),
        sub_oracles=sub_oracles,
    )


def _bound_labels(value: dict) -> tuple[str, ...]:
    raw = value.get("bound_labels")
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(name, str) for name in raw):
        raise ValueError("oracle.bound_labels must be a list of strings")
    unknown = [name for name in raw if name not in {"leftover_over", "leftover_under"}]
    if unknown:
        raise ValueError(f"unknown bound_labels: {unknown}")
    return tuple(raw)
