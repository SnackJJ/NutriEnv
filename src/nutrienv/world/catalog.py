"""Episode catalog: a Mapping of food_id -> entry, plus BM25 search.

A dict is still a valid catalog (the 15-food fixture). The USDA snapshot is a
:class:`FoodCatalog` backed by the local FDC sqlite file. Runtime never calls
the USDA API.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path

__all__ = ["FoodCatalog", "SEARCH_LIMIT", "canonical_food_id", "iter_catalog_entries"]

SEARCH_LIMIT = 25
_TOKEN = re.compile(r"[a-z0-9]+")


class FrozenDict(dict):
    """A dict that rejects in-place writes. Nested values freeze separately."""

    def __setitem__(self, key, value):
        raise TypeError("catalog entry is immutable")

    def __delitem__(self, key):
        raise TypeError("catalog entry is immutable")

    def clear(self):
        raise TypeError("catalog entry is immutable")

    def pop(self, *args, **kwargs):
        raise TypeError("catalog entry is immutable")

    def popitem(self):
        raise TypeError("catalog entry is immutable")

    def setdefault(self, *args, **kwargs):
        raise TypeError("catalog entry is immutable")

    def update(self, *args, **kwargs):
        raise TypeError("catalog entry is immutable")


def _freeze_mapping(entry: Mapping) -> FrozenDict:
    frozen = FrozenDict()
    dict.update(frozen, entry)
    return frozen


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower().replace("_", " "))


def canonical_food_id(catalog, food_id: str) -> str:
    """Resolve a minted slug or id when the catalog can; else return it."""
    resolver = getattr(catalog, "canonical_id", None)
    if callable(resolver) and food_id in catalog:
        return str(resolver(food_id))
    return food_id


class FoodCatalog(Mapping[str, dict]):
    """Read-mostly catalog with slug aliases and ranked search.

    ``food_id`` is the USDA ``fdc_id`` string. Staple slugs such as
    ``milk_whole`` resolve through the alias table so older Tasks keep working.
    Search uses SQLite FTS5 BM25 when a database is attached, otherwise
    token-AND over the in-memory map (fixture tests).
    """

    def __init__(
        self,
        foods: dict[str, dict],
        *,
        aliases: dict[str, str] | None = None,
        db_path: Path | str | None = None,
        size: int | None = None,
    ) -> None:
        self._base = foods
        self._aliases = dict(aliases or {})
        for slug, food_id in list(self._aliases.items()):
            if slug not in self._base and food_id in self._base:
                self._base[slug] = self._base[food_id]
        self._db_path = Path(db_path) if db_path is not None else None
        self._size = size if size is not None else len({self._canonical(k) for k in foods})
        seen: dict[int, FrozenDict] = {}
        for key, entry in list(self._base.items()):
            token = id(entry)
            if token not in seen:
                seen[token] = entry if isinstance(entry, FrozenDict) else _freeze_mapping(entry)
            self._base[key] = seen[token]

    @classmethod
    def from_mapping(cls, foods: Mapping[str, dict]) -> FoodCatalog:
        copied = {str(k): dict(v) for k, v in foods.items() if isinstance(v, dict)}
        return cls(copied, size=len(copied))

    @classmethod
    def from_sqlite(cls, path: Path | str) -> FoodCatalog:
        target = Path(path)
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            foods: dict[str, dict] = {}
            for row in conn.execute(
                "SELECT food_id, name, data_type, category, nutrients, "
                "portions, allergen_tags, aliases FROM foods "
                "WHERE data_type != 'branded_food'"
            ):
                foods[row["food_id"]] = _row_to_entry(row)
            aliases = {
                str(alias): str(food_id)
                for alias, food_id in conn.execute("SELECT alias, food_id FROM aliases")
            }
            size = int(conn.execute("SELECT COUNT(*) FROM foods").fetchone()[0])
        finally:
            conn.close()
        return cls(foods, aliases=aliases, db_path=target, size=size)

    def search(self, query: str, *, limit: int = SEARCH_LIMIT) -> list[dict]:
        needle = query.strip().lower()
        if not needle or needle == "*":
            return []
        if self._db_path is not None:
            return self._search_fts(needle, limit)
        return self._search_memory(needle, limit)

    def _search_memory(self, needle: str, limit: int) -> list[dict]:
        query = {tok for tok in _tokens(needle) if len(tok) >= 2}
        if not query:
            return []
        hits: list[dict] = []
        seen: set[str] = set()
        for food_id, entry in self._base.items():
            canonical = self._canonical(food_id)
            if canonical in seen:
                continue
            bag = set(_tokens(canonical))
            bag.update(_tokens(str(entry.get("name", ""))))
            for alias in entry.get("aliases") or []:
                bag.update(_tokens(str(alias)))
            if query <= bag:
                seen.add(canonical)
                hits.append(self._hit(canonical, entry))
            if len(hits) >= limit:
                break
        hits.sort(key=lambda row: row["food_id"])
        return hits[:limit]

    def _search_fts(self, needle: str, limit: int) -> list[dict]:
        terms = [tok for tok in _tokens(needle) if len(tok) >= 2]
        if not terms:
            return []
        match = " AND ".join(terms)
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT foods.food_id, foods.name, foods.allergen_tags, "
                "foods.aliases, bm25(food_fts) AS rank "
                "FROM food_fts JOIN foods ON foods.food_id = food_fts.food_id "
                "WHERE food_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()
        hits = []
        for row in rows:
            aliases = json.loads(row["aliases"] or "[]")
            tags = json.loads(row["allergen_tags"] or "[]")
            hits.append(
                {
                    "food_id": row["food_id"],
                    "name": row["name"],
                    "aliases": aliases,
                    "allergen_tags": tags,
                }
            )
        # Exact staple aliases (e.g. "chicken" → chicken_breast) must surface
        # even when BM25 ranks them below SEARCH_LIMIT.
        return _prepend_unique(self._exact_alias_hits(terms), _promote_alias_hits(hits, terms), limit)

    def _exact_alias_hits(self, terms: list[str]) -> list[dict]:
        """Foods whose an alias token-set equals the query (not a subset)."""
        wanted = set(terms)
        if not wanted:
            return []
        hits: list[dict] = []
        seen: set[str] = set()
        for food_id, entry in self._base.items():
            canonical = self._canonical(food_id)
            if canonical in seen:
                continue
            aliases = list(entry.get("aliases") or [])
            if food_id in self._aliases:
                aliases.append(food_id)
            if any(set(_tokens(str(alias))) == wanted for alias in aliases):
                seen.add(canonical)
                source = self._base.get(canonical, entry)
                hits.append(self._hit(canonical, source))
        return hits

    def _hit(self, food_id: str, entry: dict) -> dict:
        return {
            "food_id": food_id,
            "name": entry.get("name", ""),
            "aliases": list(entry.get("aliases") or []),
            "allergen_tags": list(entry.get("allergen_tags") or []),
        }

    def canonical_id(self, food_id: str) -> str:
        """Return the FDC id for a minted slug or id."""
        return self._resolve(food_id)

    def _canonical(self, food_id: str) -> str:
        if food_id in self._aliases:
            return self._aliases[food_id]
        return food_id

    def _resolve(self, food_id: str) -> str:
        canonical = self._canonical(food_id)
        if canonical in self._base or food_id in self._base:
            return canonical if canonical in self._base else food_id
        if self._lookup_db(canonical) is not None:
            return canonical
        raise KeyError(food_id)

    def _lookup_db(self, food_id: str) -> dict | None:
        if self._db_path is None:
            return None
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT food_id, name, data_type, category, nutrients, "
                "portions, allergen_tags, aliases FROM foods WHERE food_id = ?",
                (food_id,),
            ).fetchone()
            if row is None:
                alias = conn.execute(
                    "SELECT food_id FROM aliases WHERE alias = ?", (food_id,)
                ).fetchone()
                if alias is None:
                    return None
                row = conn.execute(
                    "SELECT food_id, name, data_type, category, nutrients, "
                    "portions, allergen_tags, aliases FROM foods WHERE food_id = ?",
                    (alias["food_id"],),
                ).fetchone()
                if row is None:
                    return None
        finally:
            conn.close()
        entry = _freeze_mapping(_row_to_entry(row))
        self._base[row["food_id"]] = entry
        return entry

    def __getitem__(self, food_id: str) -> dict:
        if not isinstance(food_id, str):
            raise KeyError(food_id)
        try:
            canonical = self._resolve(food_id)
        except KeyError:
            raise KeyError(food_id) from None
        source = self._base
        if canonical not in source:
            looked = self._lookup_db(canonical)
            if looked is None:
                raise KeyError(food_id)
        return self._base[canonical]

    def iter_entries(self) -> Iterator[tuple[str, dict]]:
        """Canonical ``(food_id, entry)`` pairs, same objects as ``self[id]``."""
        for food_id in self:
            yield food_id, self[food_id]

    def __contains__(self, food_id: object) -> bool:
        if not isinstance(food_id, str):
            return False
        try:
            self._resolve(food_id)
        except KeyError:
            return False
        return True

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        for key in self._base:
            canonical = self._canonical(key)
            if canonical not in seen:
                seen.add(canonical)
                yield canonical

    def __len__(self) -> int:
        return self._size

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FoodCatalog):
            return self._db_path == other._db_path and self._aliases == other._aliases
        return NotImplemented

    def __deepcopy__(self, memo: dict) -> FoodCatalog:
        clone = FoodCatalog.__new__(FoodCatalog)
        clone._base = self._base
        clone._aliases = self._aliases
        clone._db_path = self._db_path
        clone._size = self._size
        memo[id(self)] = clone
        return clone


def iter_catalog_entries(catalog) -> Iterator[tuple[str, dict]]:
    """Read-only ``(food_id, entry)`` scan over a catalog or a plain mapping."""
    scan = getattr(catalog, "iter_entries", None)
    if scan is not None:
        return scan()
    return ((str(food_id), catalog[food_id]) for food_id in catalog)


def _prepend_unique(head: list[dict], tail: list[dict], limit: int) -> list[dict]:
    """Keep ``head`` first, then ``tail``, dropping duplicate food_ids."""
    merged: list[dict] = []
    seen: set[str] = set()
    for row in head + tail:
        food_id = str(row.get("food_id") or "")
        if not food_id or food_id in seen:
            continue
        seen.add(food_id)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged


def _promote_alias_hits(hits: list[dict], terms: list[str]) -> list[dict]:
    """Prefer a staple whose aliases already contain the spoken words."""
    wanted = set(terms)

    def alias_hit(row: dict) -> bool:
        for alias in row.get("aliases") or []:
            if wanted <= set(_tokens(str(alias))):
                return True
        return False

    promoted = [row for row in hits if alias_hit(row)]
    rest = [row for row in hits if not alias_hit(row)]
    return promoted + rest


def _row_to_entry(row: sqlite3.Row) -> dict:
    return {
        "name": row["name"],
        "nutrients": json.loads(row["nutrients"] or "{}"),
        "allergen_tags": json.loads(row["allergen_tags"] or "[]"),
        "aliases": json.loads(row["aliases"] or "[]"),
        "portions": json.loads(row["portions"] or "{}"),
        "fdc_id": int(row["food_id"]) if str(row["food_id"]).isdigit() else row["food_id"],
        "data_type": row["data_type"],
        "category": row["category"],
    }
