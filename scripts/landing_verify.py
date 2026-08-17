#!/usr/bin/env python3
"""Post-landing checks for the FNDDS safe-overlay catalog.

Replays realization phrases on gold items that match a Row by query, compares
legacy old-class keys against the live catalog, and runs validate_draft on
the 240-item split. Re-run:

    .venv/bin/python scripts/landing_verify.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "src"))

import build_fdc_catalog as builder  # noqa: E402
from nutrienv.bench.realizations import (  # noqa: E402
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    FUZZY_ROWS,
    LEDGER_GAP_ROWS,
    LEFTOVER_ROWS,
    MULTI_ITEM_LOG_ROWS,
    NEAR_SYNONYM_ROWS,
    RECOMMEND_ROWS,
    UNIT_CONVERT_ROWS,
    UPDATE_ROWS,
)
from nutrienv.bench.split import load_exam, load_split  # noqa: E402
from nutrienv.bench.validator import validate_draft, validate_oracle_grams  # noqa: E402
from nutrienv.world.catalog_store import load_catalog  # noqa: E402
from nutrienv.world.portions import resolve_portion  # noqa: E402

_SPLIT = _ROOT / "data" / "splits" / "v0.5-gold.json"
_V10_SPLIT = _ROOT / "data" / "splits" / "v1.0-gold.json"
_V10_N = 20
_OLD_KEYS = builder._OLD_PORTION_KEYS
_GOLD_SOURCES = (
    ("s0", "ledger"),
    ("oracle", "ledger_tail"),
    ("s0", "last_plan"),
    ("oracle", "last_plan"),
)


def _legacy_portions() -> dict[str, dict[str, float]]:
    """Re-run the unchanged zip-order old-key scan (no overlay)."""
    out: dict[str, dict[str, float]] = {}
    survey = (
        builder._RAW / "fndds.zip"
        if (builder._RAW / "fndds.zip").is_file()
        else builder._RAW / "survey.zip"
    )
    for path in (survey, builder._RAW / "sr_legacy.zip"):
        if not path.is_file():
            continue
        with zipfile.ZipFile(path) as zf:
            collected = builder._collect_portions(zf)
        for fdc_id, portions in collected.items():
            bucket = out.setdefault(fdc_id, {})
            for key, grams in portions.items():
                bucket.setdefault(key, grams)
    return out


def _all_rows() -> list[object]:
    tables = (
        FUZZY_ROWS,
        MULTI_ITEM_LOG_ROWS,
        UNIT_CONVERT_ROWS,
        NEAR_SYNONYM_ROWS,
        LEDGER_GAP_ROWS,
        LEFTOVER_ROWS,
        UPDATE_ROWS,
        CONSTRAIN_ROWS,
        EVALUATE_ROWS,
        RECOMMEND_ROWS,
    )
    return [row for table in tables for row in table]


def _row_phrases(row: object) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    food_id = getattr(row, "food_id", None)
    phrase = getattr(row, "phrase", None)
    if isinstance(food_id, str) and isinstance(phrase, str):
        pairs.append((food_id, phrase))
    items = getattr(row, "items", None)
    if items:
        for food, spoken in items:
            pairs.append((food, spoken))
    missing = getattr(row, "missing", None)
    if missing:
        pairs.append((missing[0], missing[1]))
    return pairs


def _row_queries(row: object) -> list[str]:
    out: list[str] = []
    for attr in ("utterance", "query"):
        value = getattr(row, attr, None)
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
    return out


def _match_row(item: dict, by_query: dict[str, object], by_seed: dict[str, object]):
    query = (item.get("query") or "").strip()
    if query in by_query:
        return by_query[query]
    item_id = item.get("id") or ""
    for prefix, seed_prefix in (
        ("-log-fz-", "fz-"),
        ("-eval-", "ev-"),
        ("-rec-lo-", "lo-"),
        ("-upd-", "up-"),
        ("-cond-", "co-"),
        ("-conf-", "cf-"),
        ("-log-", ""),
        ("-rec-", "rec-"),
    ):
        if prefix in item_id:
            stem = item_id.split(prefix, 1)[1]
            seed = f"{seed_prefix}{stem}" if seed_prefix else stem
            if seed in by_seed:
                return by_seed[seed]
    return None


def _gold_foods(split: dict, aliases: dict[str, str]) -> dict[str, str]:
    used: dict[str, str] = {}
    for item in split.get("items") or []:
        for bucket, field in _GOLD_SOURCES:
            parent = item.get(bucket) or {}
            if not isinstance(parent, dict):
                continue
            for row in parent.get(field) or []:
                if not isinstance(row, dict):
                    continue
                food_id = row.get("food_id")
                if isinstance(food_id, str):
                    used[food_id] = aliases.get(food_id, food_id)
    return dict(sorted(used.items()))


def _load_aliases(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            str(alias): str(food_id)
            for alias, food_id in conn.execute("SELECT alias, food_id FROM aliases")
        }
    finally:
        conn.close()


def _view_with_portions(catalog, portions_by_fid: dict[str, dict[str, float]], aliases):
    """Shallow food-entry overlay so resolve_portion sees a chosen portions table."""
    view: dict = {}
    for food_id in list(aliases) + list(portions_by_fid):
        try:
            entry = dict(catalog[food_id])
        except KeyError:
            continue
        fdc_id = aliases.get(food_id, food_id)
        if fdc_id in portions_by_fid:
            entry["portions"] = dict(portions_by_fid[fdc_id])
        view[food_id] = entry
        if fdc_id != food_id:
            view[fdc_id] = entry
    return view


def _oz_conflicts(survey: Path) -> list[str]:
    """fdc_ids that have both a physical-oz row and a yield-oz row."""
    import csv

    with zipfile.ZipFile(survey) as zf:
        member = builder._zip_member(zf, "food_portion.csv")
        with zf.open(member) as handle:
            rows = list(csv.DictReader(line.decode("utf-8", errors="replace") for line in handle))
    by_food: dict[str, set[str]] = {}
    for row in rows:
        keys = set(builder._overlay_keys(row.get("portion_description") or "", row.get("modifier") or ""))
        kinds = {key for key in keys if key in {"oz", "oz_yield"}}
        if kinds:
            by_food.setdefault(row["fdc_id"], set()).update(kinds)
    return sorted(fid for fid, kinds in by_food.items() if kinds == {"oz", "oz_yield"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, default=_SPLIT)
    parser.add_argument("--catalog", type=Path, default=builder._DB)
    args = parser.parse_args(argv)

    split = json.loads(args.split.read_text(encoding="utf-8"))
    catalog = load_catalog(args.catalog)
    aliases = _load_aliases(args.catalog)
    legacy = _legacy_portions()
    gold_foods = _gold_foods(split, aliases)

    old_key_drifts: list[dict] = []
    for slug, fdc_id in gold_foods.items():
        live = dict((catalog[slug].get("portions") if slug in catalog else {}) or {})
        old_live = {k: live[k] for k in sorted(live) if k in _OLD_KEYS}
        old_legacy = dict(legacy.get(fdc_id) or {})
        if old_live != old_legacy:
            old_key_drifts.append(
                {"food_id": slug, "fdc_id": fdc_id, "legacy": old_legacy, "live": old_live}
            )

    rows = _all_rows()
    by_seed = {row.seed_id: row for row in rows}
    by_query: dict[str, object] = {}
    for row in rows:
        for query in _row_queries(row):
            by_query.setdefault(query, row)

    live_view = catalog
    legacy_view = _view_with_portions(catalog, legacy, aliases)

    replay_ok = 0
    replay_skip = 0
    replay_fail: list[dict] = []
    for item in split.get("items") or []:
        row = _match_row(item, by_query, by_seed)
        phrases = _row_phrases(row) if row is not None else []
        if not phrases:
            replay_skip += 1
            continue
        for food_id, phrase in phrases:
            old_g = resolve_portion(food_id, phrase, legacy_view)
            new_g = resolve_portion(food_id, phrase, live_view)
            if old_g != new_g:
                replay_fail.append(
                    {
                        "item_id": item.get("id"),
                        "food_id": food_id,
                        "phrase": phrase,
                        "old": old_g,
                        "new": new_g,
                    }
                )
            else:
                replay_ok += 1

    tasks = load_split(args.split)
    validate_bad = [(task.id, issues) for task in tasks if (issues := validate_draft(task))]

    survey = (
        builder._RAW / "fndds.zip"
        if (builder._RAW / "fndds.zip").is_file()
        else builder._RAW / "survey.zip"
    )
    conflict_ids = _oz_conflicts(survey)
    oz_bad: list[dict] = []
    for fdc_id in conflict_ids:
        if fdc_id not in catalog:
            continue
        portions = catalog[fdc_id].get("portions") or {}
        if "oz" in portions and "oz_yield" in portions:
            continue
        oz_bad.append({"fdc_id": fdc_id, "portions": dict(portions)})

    print(f"gold foods: {len(gold_foods)}")
    print(f"old-key drifts: {len(old_key_drifts)}")
    print(f"phrase replay: {replay_ok} equal, {len(replay_fail)} differ, {replay_skip} items unmatched/no phrase")
    print(f"validate_draft: {len(tasks)} items, {len(validate_bad)} failing")
    print(f"oz/oz_yield conflicts in FNDDS: {len(conflict_ids)}; unsplitting: {len(oz_bad)}")
    if old_key_drifts:
        print("OLD-KEY DRIFTS:")
        for row in old_key_drifts:
            print(f"  {row['food_id']} {row['legacy']} -> {row['live']}")
    if replay_fail:
        print("REPLAY FAILURES:")
        for row in replay_fail[:20]:
            print(f"  {row['item_id']} {row['food_id']} {row['phrase']!r} {row['old']} -> {row['new']}")
    if validate_bad:
        print("VALIDATE FAILURES:")
        for item_id, issues in validate_bad[:10]:
            print(f"  {item_id} {issues}")
    if oz_bad:
        print("OZ UNSPELT:")
        for row in oz_bad[:10]:
            print(f"  {row['fdc_id']} {row['portions']}")

    v10_n, v10_draft_bad, v10_grams_bad = verify_v10_exam(_V10_SPLIT)
    print(f"v1.0-gold load_exam: {v10_n} items")
    print(f"v1.0-gold validate_draft: {v10_n} items, {len(v10_draft_bad)} failing")
    print(f"v1.0-gold validate_oracle_grams: {v10_n} items, {len(v10_grams_bad)} failing")
    if v10_draft_bad:
        print("V10 VALIDATE FAILURES:")
        for item_id, issues in v10_draft_bad[:10]:
            print(f"  {item_id} {issues}")
    if v10_grams_bad:
        print("V10 ORACLE GRAMS FAILURES:")
        for item_id, issues in v10_grams_bad[:10]:
            print(f"  {item_id} {issues}")

    ok = (
        not old_key_drifts
        and not replay_fail
        and not validate_bad
        and not oz_bad
        and replay_ok > 0
        and v10_n == _V10_N
        and not v10_draft_bad
        and not v10_grams_bad
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def verify_v10_exam(path: Path | None = None) -> tuple[int, list, list]:
    """load_exam the v1.0 split and run validate_draft + oracle-grams on every item."""
    target = Path(path) if path is not None else _V10_SPLIT
    tasks = load_exam(target)
    draft_bad = [(task.id, issues) for task in tasks if (issues := validate_draft(task))]
    grams_bad = [
        (task.id, issues) for task in tasks if (issues := validate_oracle_grams(task))
    ]
    return len(tasks), draft_bad, grams_bad


if __name__ == "__main__":
    raise SystemExit(main())
