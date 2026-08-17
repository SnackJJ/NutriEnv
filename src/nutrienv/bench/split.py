"""Load a frozen Task split. This file is the published exam."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.types import LedgerRow, Profile, WorldState, normalize_tags, normalize_window

from .generator import FAMILIES, Oracle, Task
from .situations import SITUATIONS

__all__ = ["GOLD_SPLIT_PATH", "load_split", "load_exam"]

_ROOT = Path(__file__).resolve().parents[3]
GOLD_SPLIT_PATH = _ROOT / "data" / "splits" / "v0-gold.json"


def load_split(path: Path | str | None = None) -> list[Task]:
    """Read a frozen JSON split and attach the local catalog to every S0."""
    target = Path(path) if path is not None else GOLD_SPLIT_PATH
    if not target.is_file():
        raise FileNotFoundError(f"split not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("split must contain a non-empty items list")
    catalog = load_catalog()
    return [_item(entry, catalog) for entry in items]


def load_exam(path: Path | str | None = None) -> list[Task]:
    """Load the published 240-item exam. Fail closed on catalog identity.

    Unlike :func:`load_split`, this checks ``version``, a non-empty ``items``
    list, that the recorded catalog file exists (resolved from the repo root),
    and that ``sha256(catalog bytes)`` matches ``catalog_sha256``.
    """
    target = Path(path) if path is not None else _ROOT / "data" / "splits" / "v0.5-gold.json"
    if not target.is_file():
        raise FileNotFoundError(f"exam split not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("exam payload must be an object")
    version = payload.get("version")
    if version != "v0.5-gold":
        raise ValueError(f"exam version must be 'v0.5-gold', got {version!r}")
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
    digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    if digest != digest_field:
        raise ValueError(
            f"exam catalog sha256 mismatch: file={digest} split={digest_field}"
        )
    return load_split(target)


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
    s0 = _s0(entry.get("s0"), catalog)
    oracle = _oracle(entry.get("oracle"), s0, catalog)
    return Task(task_id, family, query.strip(), s0, oracle, situations, persona)


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
    return Profile(
        user_id=str(value.get("user_id") or default_user),
        allergies=normalize_tags(value.get("allergies") or []),
        medications=normalize_tags(value.get("medications") or []),
        windows=windows,
        plan_preset=copy.deepcopy(value.get("plan_preset") or {}),
        version=int(value.get("version") or 1),
    )


def _canonical_food_id(food_id: str, catalog: object) -> str:
    resolver = getattr(catalog, "canonical_id", None)
    if callable(resolver) and food_id in catalog:  # type: ignore[operator]
        return str(resolver(food_id))
    return food_id


def _row(value: object, catalog: object) -> LedgerRow:
    if not isinstance(value, dict):
        raise ValueError("ledger row must be an object")
    return LedgerRow(
        _canonical_food_id(str(value["food_id"]), catalog),
        float(value["grams"]),
        str(value["eaten_at"]),
    )


def _plan_item(value: object, catalog: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("plan item must be an object")
    item = copy.deepcopy(value)
    if "food_id" in item:
        item["food_id"] = _canonical_food_id(str(item["food_id"]), catalog)
    return item


def _oracle(value: object, s0: WorldState, catalog: object) -> Oracle:
    if value is None:
        return Oracle()
    if not isinstance(value, dict):
        raise ValueError("oracle must be an object")
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
        profile = _profile(merged, default_user=s0.profile.user_id)
    else:
        raise ValueError("oracle.profile must be omitted, 's0', or an object")

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

    plan_windows = None
    raw_windows = value.get("plan_windows")
    if raw_windows is not None:
        if not isinstance(raw_windows, dict):
            raise ValueError("oracle.plan_windows must be an object")
        plan_windows = {
            str(key): normalize_window(bounds) for key, bounds in raw_windows.items()
        }

    return Oracle(
        profile=profile,
        last_plan=copy.deepcopy(last_plan) if last_plan is not None else None,
        ledger_tail=ledger_tail,
        ledger=ledger,
        plan_must_be_safe=bool(value.get("plan_must_be_safe", False)),
        plan_must_fit_windows=bool(value.get("plan_must_fit_windows", False)),
        allow_empty_plan=bool(value.get("allow_empty_plan", False)),
        plan_windows=plan_windows,
    )
