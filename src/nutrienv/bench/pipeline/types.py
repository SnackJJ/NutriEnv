"""Shared types and catalog digest for the v1.0 candidate pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from nutrienv.bench.realize import Task

__all__ = [
    "CATALOG_V1_RELPATH",
    "DEFAULT_FREEZE_RELPATH",
    "MAX_PER_POOL",
    "PIPELINE_VERSION",
    "POOL_SIZE",
    "QUANTITY_MULTIPLES",
    "SAMPLER_RULE_VERSION",
    "SUPPORTED_FAMILIES",
    "Candidate",
    "Expander",
    "FoodPool",
    "Judge",
    "PoolFood",
    "PortionAlternative",
    "Rejected",
    "Reviewer",
    "catalog_digest",
]

PIPELINE_VERSION = "v1.0-gold"
SAMPLER_RULE_VERSION = "sampler-v1"
POOL_SIZE = 8
MAX_PER_POOL = 3
QUANTITY_MULTIPLES = (0.5, 1.0, 1.5, 2.0)
SUPPORTED_FAMILIES = frozenset({"log", "evaluate"})
CATALOG_V1_RELPATH = "data/fdc/catalog-v1.sqlite"
DEFAULT_FREEZE_RELPATH = "data/splits/v1.0-gold.json"

_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class PortionAlternative:
    key: str
    quantity: float
    phrase: str
    grams: float


@dataclass(frozen=True)
class PoolFood:
    food_id: str
    name: str
    aliases: tuple[str, ...]
    alternatives: tuple[PortionAlternative, ...]


@dataclass(frozen=True)
class FoodPool:
    pool_id: str
    family: str
    foods: tuple[PoolFood, ...]


@dataclass(frozen=True)
class Candidate:
    items: tuple[tuple[str, str], ...]
    query: str
    family: str
    persona: str
    pool_id: str = ""


@dataclass(frozen=True)
class Rejected:
    query: str
    reason: str
    family: str


class Expander(Protocol):
    def __call__(
        self, pool: FoodPool, *, persona: str, family: str
    ) -> Mapping[str, object] | Sequence[Mapping[str, object]]: ...


class Judge(Protocol):
    def __call__(self, food: str, grams: float) -> str: ...


class Reviewer(Protocol):
    def __call__(self, candidates: Sequence[Task]) -> Mapping[str, object]: ...


def catalog_digest(catalog) -> str:
    """SHA-256 of catalog file bytes, or a stable digest of an in-memory map."""
    path = getattr(catalog, "_db_path", None)
    if path is not None:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    payload: dict[str, object] = {}
    for food_id in sorted(catalog):
        entry = catalog[food_id]
        if not isinstance(entry, dict):
            continue
        payload[food_id] = {
            "name": entry.get("name"),
            "portions": entry.get("portions"),
            "aliases": list(entry.get("aliases") or []),
        }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def repo_root() -> Path:
    return _ROOT
