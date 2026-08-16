#!/usr/bin/env python3
"""Dry-run a full FNDDS portion ingest against the frozen catalog and gold split.

Does not write ``data/fdc/catalog.sqlite``, does not touch gold JSON, and does
not import or modify ``scripts/build_fdc_catalog.py``. Re-run:

    .venv/bin/python scripts/fndds_dry_run.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import zipfile
from pathlib import Path
from typing import Iterable

_ROOT = Path(__file__).resolve().parents[1]
_SURVEY = _ROOT / "data" / "fdc" / "raw" / "survey.zip"
_DB = _ROOT / "data" / "fdc" / "catalog.sqlite"
_SPLIT = _ROOT / "data" / "splits" / "v0.5-gold.json"
_DRIFT_OUT = _ROOT / "reports" / "dry-run-drift.json"
_SUMMARY_OUT = _ROOT / "reports" / "dry-run-summary.md"

QNS_MODIFIER = "90000"
OLD_KEYS = ("cup", "tbsp", "tsp", "slice", "piece", "can")
NEW_KEYS = ("thick", "thin", "regular", "oz", "fl_oz", "cubic_inch", "serving", "qns")

# Same household patterns as build_fdc_catalog._UNIT_PATTERNS, in that order.
# slice is listed before piece, which is why a lone "1 piece/slice" row currently
# becomes slice and the piece branch is dropped. This dry-run overrides that
# for slash-compounds only (see _portion_keys).
_HOUSEHOLD: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcups?\b"), "cup"),
    (re.compile(r"\btablespoons?\b|\btbsp\b"), "tbsp"),
    (re.compile(r"\bteaspoons?\b|\btsp\b"), "tsp"),
    (re.compile(r"\bslices?\b"), "slice"),
    (re.compile(r"\bpieces?\b|\beach\b"), "piece"),
    (re.compile(r"\bcans?\b"), "can"),
]
_SIZE_AS_PIECE = re.compile(r"\bbanana\b|\begg\b|\bmedium\b|\blarge\b|\bsmall\b")
_PIECE_WORD = re.compile(r"\bpieces?\b")
_SLICE_WORD = re.compile(r"\bslices?\b")
# New keys: more specific patterns first so "1 fl oz" is not stored as "oz",
# and "1 large or thick slice" never reaches here (household slice already won).
_NEW_UNITS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bthick\b"), "thick"),
    (re.compile(r"\bthin\b"), "thin"),
    (re.compile(r"\bregular\b"), "regular"),
    (re.compile(r"\bcubic inch(?:es)?\b"), "cubic_inch"),
    (re.compile(r"\bfl\.?\s*oz\b"), "fl_oz"),
    # Weight-ounce rows ("1 oz", "1 oz yields", "1 oz, cooked"). Skip
    # "5.3 oz container" / bags / bottles — those are packages, not oz.
    (
        re.compile(
            r"\boz\b(?!\s+(?:container|bag|bottle|package|cup)\b)"
        ),
        "oz",
    ),
    (re.compile(r"\b(?:single\s+)?servings?\b"), "serving"),
]

# Factors used to attribute a frozen gold gram value back to a portion key.
_FACTORS = (0.25, 1.0 / 3.0, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)

_GOLD_SOURCES = (
    ("s0", "ledger"),
    ("oracle", "ledger_tail"),
    ("s0", "last_plan"),
    ("oracle", "last_plan"),
)

POLICY = {
    "sort": (
        "All food_portion.csv rows are sorted by "
        "(fdc_id ASC, seq_num ASC as int, portion id ASC as int) before merge. "
        "seq_num is the FNDDS survey instrument order for that food; the portion "
        "id tie-break makes the order independent of zip member iteration."
    ),
    "merge": (
        "first-wins per (fdc_id, key): the first positive gram_weight after the "
        "sort is kept; later rows for the same key are ignored."
    ),
    "piece_slice_compound": (
        "If portion_description contains both a piece word and a slice word "
        "(typically '1 piece/slice, any size'), the row writes BOTH keys with "
        "the same grams. Current build_fdc_catalog._portion_key walks "
        "_UNIT_PATTERNS and hits slice before piece, so the piece branch is "
        "eaten and the row lands only as slice. Dual-write treats the FNDDS "
        "row as one interchangeable household amount. first-wins still applies "
        "independently to each key: an earlier dedicated '1 piece' row keeps "
        "piece; a compound that sorts first will set both."
    ),
    "qns": (
        "modifier == 90000, or portion_description starting with "
        "'quantity not', becomes key 'qns'. gram_weight <= 0 is dropped."
    ),
    "still_dropped": (
        "Guideline-amount rows stay dropped. 'mashed' rows and "
        "'sliced' + 'cup' rows stay dropped, matching the current builder, "
        "so a mashed cup cannot steal the cup key."
    ),
    "old_key_mapping": (
        "cup/tbsp/tsp/slice/piece/can use the current household patterns. "
        "banana/egg/medium/large/small still collapse to piece (current "
        "builder). Household units win over thick/thin/regular/oz so "
        "'1 large or thick slice' stays slice."
    ),
    "new_keys": list(NEW_KEYS),
    "oz_vs_package": (
        "oz matches weight-ounce rows (1 oz / oz yields / oz, cooked). "
        "A trailing container/bag/bottle/package/cup word is not oz "
        "(e.g. '1 5.3 oz container' is skipped, not oz=150)."
    ),
}


def _zip_member(zf: zipfile.ZipFile, suffix: str) -> str:
    for name in zf.namelist():
        if name.rsplit("/", 1)[-1] == suffix:
            return name
    raise FileNotFoundError(suffix)


def _iter_csv(zf: zipfile.ZipFile, suffix: str) -> Iterable[dict[str, str]]:
    member = _zip_member(zf, suffix)
    with zf.open(member) as handle:
        yield from csv.DictReader(
            line.decode("utf-8", errors="replace") for line in handle
        )


def _portion_keys(description: str, modifier: str) -> list[str]:
    """Return catalog keys this FNDDS row should populate."""
    desc = (description or "").strip()
    blob = " ".join(part for part in (desc, modifier or "") if part).lower()
    if (modifier or "") == QNS_MODIFIER or desc.lower().startswith("quantity not"):
        return ["qns"]
    if not blob or "guideline" in blob:
        return []
    if "mashed" in blob or ("sliced" in blob and "cup" in blob):
        return []

    keys: list[str] = []
    compound = bool(_PIECE_WORD.search(blob) and _SLICE_WORD.search(blob))
    if compound:
        keys.extend(("piece", "slice"))

    for pattern, key in _HOUSEHOLD:
        if key in keys:
            continue
        if pattern.search(blob):
            keys.append(key)
            break
    if keys:
        return keys

    if _SIZE_AS_PIECE.search(blob):
        return ["piece"]

    for pattern, key in _NEW_UNITS:
        if pattern.search(blob):
            return [key]
    return []


def _row_sort_key(row: dict[str, str]) -> tuple[str, int, int]:
    try:
        seq = int(row.get("seq_num") or 0)
    except ValueError:
        seq = 0
    try:
        portion_id = int(row.get("id") or 0)
    except ValueError:
        portion_id = 0
    return (row.get("fdc_id") or "", seq, portion_id)


def _merge_portion(portions: dict[str, float], key: str, grams: float) -> None:
    if grams <= 0 or key in portions:
        return
    portions[key] = round(grams, 2)


def collect_full_fndds(
    survey_zip: Path,
) -> tuple[dict[str, dict[str, float]], dict[str, str], int]:
    """Simulated full-FNDDS portions, first-wins after seq_num sort."""
    out: dict[str, dict[str, float]] = {}
    qns_zero_dropped = 0
    with zipfile.ZipFile(survey_zip) as zf:
        rows = list(_iter_csv(zf, "food_portion.csv"))
        names = {
            row["fdc_id"]: (row.get("description") or "").strip()
            for row in _iter_csv(zf, "food.csv")
            if row.get("fdc_id")
        }
    rows.sort(key=_row_sort_key)
    for row in rows:
        fdc_id = row.get("fdc_id") or ""
        keys = _portion_keys(
            row.get("portion_description") or "", row.get("modifier") or ""
        )
        try:
            grams = float(row.get("gram_weight") or "")
        except ValueError:
            continue
        if grams <= 0 and keys == ["qns"]:
            qns_zero_dropped += 1
            continue
        for key in keys:
            _merge_portion(out.setdefault(fdc_id, {}), key, grams)
    return out, names, qns_zero_dropped


def load_catalog(db_path: Path) -> tuple[dict[str, dict], dict[str, str]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        foods: dict[str, dict] = {}
        for row in conn.execute(
            "SELECT food_id, name, data_type, portions FROM foods"
        ):
            foods[row["food_id"]] = {
                "name": row["name"],
                "data_type": row["data_type"],
                "portions": json.loads(row["portions"] or "{}"),
            }
        aliases = {
            str(alias): str(food_id)
            for alias, food_id in conn.execute("SELECT alias, food_id FROM aliases")
        }
    finally:
        conn.close()
    return foods, aliases


def _canonical(food_id: str, aliases: dict[str, str]) -> str:
    return aliases.get(food_id, food_id)


def diff_portions(
    old: dict[str, float], new: dict[str, float]
) -> tuple[dict[str, dict[str, float]], dict[str, float], dict[str, float]]:
    changed: dict[str, dict[str, float]] = {}
    added: dict[str, float] = {}
    removed: dict[str, float] = {}
    for key, old_g in old.items():
        if key not in new:
            removed[key] = old_g
        elif new[key] != old_g:
            changed[key] = {"old": old_g, "new": new[key]}
    for key, new_g in new.items():
        if key not in old:
            added[key] = new_g
    return changed, added, removed


def iter_gold_rows(item: dict) -> Iterable[tuple[str, str, float]]:
    for bucket, field in _GOLD_SOURCES:
        parent = item.get(bucket) or {}
        if not isinstance(parent, dict):
            continue
        rows = parent.get(field) or []
        source = f"{bucket}.{field}"
        for row in rows:
            if not isinstance(row, dict):
                continue
            food_id = row.get("food_id")
            try:
                grams = float(row["grams"])
            except (KeyError, TypeError, ValueError):
                continue
            if isinstance(food_id, str):
                yield source, food_id, grams


def collect_gold_foods(split: dict, aliases: dict[str, str]) -> dict[str, str]:
    used: dict[str, str] = {}
    for item in split.get("items") or []:
        for _source, food_id, _grams in iter_gold_rows(item):
            used[food_id] = _canonical(food_id, aliases)
    return dict(sorted(used.items()))


def _factor_match(grams: float, unit: float) -> float | None:
    if unit <= 0:
        return None
    for factor in _FACTORS:
        if abs(grams - round(factor * unit, 2)) < 1e-9:
            return factor
    return None


def infer_key(
    grams: float, old: dict[str, float]
) -> tuple[str, float, float] | None:
    """Best (key, factor, old_grams) explaining a frozen gold gram value."""
    hits: list[tuple[float, str, float, float]] = []
    for key, old_g in old.items():
        factor = _factor_match(grams, old_g)
        if factor is None:
            continue
        hits.append((abs(factor - 1.0), key, factor, old_g))
    if not hits:
        return None
    hits.sort(
        key=lambda row: (
            row[0],
            OLD_KEYS.index(row[1]) if row[1] in OLD_KEYS else 99,
        )
    )
    _dist, key, factor, old_g = hits[0]
    return key, factor, old_g


def gold_item_drifts(
    split: dict,
    aliases: dict[str, str],
    catalog: dict[str, dict],
    proposed: dict[str, dict[str, float]],
) -> list[dict]:
    out: list[dict] = []
    for item in split.get("items") or []:
        item_id = item.get("id") or ""
        for source, food_id, grams in iter_gold_rows(item):
            fdc_id = _canonical(food_id, aliases)
            old = dict((catalog.get(fdc_id) or {}).get("portions") or {})
            if fdc_id not in catalog and food_id in catalog:
                old = dict(catalog[food_id].get("portions") or {})
            new = proposed.get(fdc_id) or old
            inferred = infer_key(grams, old)
            if inferred is None:
                continue
            key, factor, old_unit = inferred
            new_unit = new.get(key)
            if new_unit is None or new_unit == old_unit:
                continue
            new_grams = round(factor * new_unit, 2)
            if new_grams == grams:
                continue
            out.append(
                {
                    "item_id": item_id,
                    "source": source,
                    "food_id": food_id,
                    "fdc_id": fdc_id,
                    "key": key,
                    "factor": factor,
                    "old_grams": grams,
                    "new_grams": new_grams,
                    "old_unit_g": old_unit,
                    "new_unit_g": new_unit,
                }
            )
    out.sort(key=lambda row: (row["item_id"], row["source"], row["food_id"]))
    return out


def _sorted_floats(mapping: dict[str, float]) -> dict[str, float]:
    return {key: mapping[key] for key in sorted(mapping)}


def build_report(
    *,
    catalog: dict[str, dict],
    aliases: dict[str, str],
    proposed: dict[str, dict[str, float]],
    fndds_names: dict[str, str],
    split: dict,
    survey_zip: Path,
    db_path: Path,
    split_path: Path,
    qns_zero_dropped: int,
) -> dict:
    gold_foods = collect_gold_foods(split, aliases)
    diffs: list[dict] = []
    n_changed_old = 0
    n_only_added = 0
    n_compared = 0
    qns_foods = 0

    fndds_ids = {
        fid
        for fid, entry in catalog.items()
        if entry.get("data_type") == "survey_fndds_food"
    }
    compare_ids = sorted(fndds_ids | set(proposed))
    for fdc_id in compare_ids:
        entry = catalog.get(fdc_id) or {}
        old = dict(entry.get("portions") or {})
        new = dict(proposed.get(fdc_id) or {})
        if not old and not new:
            continue
        n_compared += 1
        if "qns" in new:
            qns_foods += 1
        changed, added, removed = diff_portions(old, new)
        if not changed and not added and not removed:
            continue
        if any(key in OLD_KEYS for key in changed) or any(
            key in OLD_KEYS for key in removed
        ):
            n_changed_old += 1
        elif not changed and not removed and added:
            n_only_added += 1
        diffs.append(
            {
                "fdc_id": fdc_id,
                "name": entry.get("name") or fndds_names.get(fdc_id) or "",
                "data_type": entry.get("data_type") or "survey_fndds_food",
                "old": _sorted_floats(old),
                "new": _sorted_floats(new),
                "changed": {k: changed[k] for k in sorted(changed)},
                "added": _sorted_floats(added),
                "removed": _sorted_floats(removed),
            }
        )

    gold_detail = []
    gold_old_key_hits: list[dict] = []
    for slug, fdc_id in gold_foods.items():
        entry = catalog.get(fdc_id) or catalog.get(slug) or {}
        old = dict(entry.get("portions") or {})
        new = dict(proposed.get(fdc_id) or old)
        changed, added, removed = diff_portions(old, new)
        old_key_changed = {
            key: val for key, val in changed.items() if key in OLD_KEYS
        }
        old_key_removed = {
            key: val for key, val in removed.items() if key in OLD_KEYS
        }
        if old_key_changed or old_key_removed:
            gold_old_key_hits.append(
                {
                    "food_id": slug,
                    "fdc_id": fdc_id,
                    "name": entry.get("name") or "",
                    "changed": old_key_changed,
                    "removed": old_key_removed,
                }
            )
        gold_detail.append(
            {
                "food_id": slug,
                "fdc_id": fdc_id,
                "name": entry.get("name") or "",
                "data_type": entry.get("data_type") or "",
                "in_fndds": fdc_id in proposed,
                "old": _sorted_floats(old),
                "new": _sorted_floats(new),
                "changed": {k: changed[k] for k in sorted(changed)},
                "added": _sorted_floats(added),
                "removed": _sorted_floats(removed),
                "qns": new.get("qns"),
            }
        )

    item_drifts = gold_item_drifts(split, aliases, catalog, proposed)

    # Safe overlay: freeze every old key, only insert keys the catalog lacks.
    safe_proposed = {}
    for fdc_id, new in proposed.items():
        old = dict((catalog.get(fdc_id) or {}).get("portions") or {})
        merged = dict(old)
        for key, grams in new.items():
            merged.setdefault(key, grams)
        safe_proposed[fdc_id] = merged
    safe_item_drifts = gold_item_drifts(split, aliases, catalog, safe_proposed)

    n_fndds_catalog = len(fndds_ids)
    n_zero = n_compared - len(diffs)
    return {
        "meta": {
            "survey": str(survey_zip.relative_to(_ROOT)),
            "catalog": str(db_path.relative_to(_ROOT)),
            "split": str(split_path.relative_to(_ROOT)),
            "split_version": split.get("version"),
            "n_split_items": len(split.get("items") or []),
            "note": (
                "Read-only dry-run. catalog.sqlite, gold JSON, and "
                "build_fdc_catalog.py were not modified."
            ),
        },
        "policy": POLICY,
        "stats": {
            "fndds_foods_in_catalog": n_fndds_catalog,
            "fndds_foods_with_proposed_portions": len(proposed),
            "foods_compared": n_compared,
            "foods_with_any_diff": len(diffs),
            "foods_old_key_changed_or_removed": n_changed_old,
            "foods_only_new_keys_added": n_only_added,
            "foods_zero_drift": n_zero,
            "foods_with_qns": qns_foods,
            "qns_zero_gram_rows_dropped": qns_zero_dropped,
        },
        "gold": {
            "n_foods": len(gold_foods),
            "food_ids": list(gold_foods),
            "old_key_zero_drift": not gold_old_key_hits and not item_drifts,
            "foods_with_old_key_changes": gold_old_key_hits,
            "item_drifts": item_drifts,
            "foods": gold_detail,
            "safe_overlay_item_drifts": safe_item_drifts,
            "safe_overlay_old_key_zero_drift": not safe_item_drifts,
        },
        "diffs": diffs,
    }


def _fmt_portions(portions: dict) -> str:
    if not portions:
        return "—"
    return ", ".join(f"{k}={v:g}" for k, v in portions.items())


def write_summary(report: dict, dest: Path) -> None:
    stats = report["stats"]
    gold = report["gold"]
    policy = report["policy"]
    meta = report["meta"]
    lines: list[str] = [
        "# FNDDS 完整接入 dry-run",
        "",
        "只读对比：未改 `data/fdc/catalog.sqlite`、未改任何 gold JSON、未改 "
        "`scripts/build_fdc_catalog.py`。",
        "",
        f"- survey: `{meta['survey']}`",
        f"- catalog: `{meta['catalog']}`",
        f"- split: `{meta['split']}`（{meta['n_split_items']} 条，version "
        f"`{meta['split_version']}`）",
        "- 复跑: `.venv/bin/python scripts/fndds_dry_run.py`",
        "",
        "## 接入策略",
        "",
        "### 排序（first-wins 之前）",
        "",
        "先把 `food_portion.csv` 全部行按 "
        "`(fdc_id 升序, seq_num 升序, portion id 升序)` 排定，再合并。"
        "`seq_num` 是 FNDDS 问卷里该食物的官方顺序；id 做并列打平，"
        "结果不依赖 zip 内行序。",
        "",
        "### 合并",
        "",
        "每个 `(fdc_id, key)` **first-wins**：排序后第一条 `gram_weight > 0` 留下，"
        "同键后续行丢弃。",
        "",
        "### 复合描述 `1 piece/slice, any size`",
        "",
        "描述里同时出现 piece 与 slice（典型即 `1 piece/slice, any size`）时，"
        "**同一克数双写 `piece` 和 `slice`**。",
        "",
        "当前 `build_fdc_catalog._portion_key` 按 `_UNIT_PATTERNS` 扫描，"
        "`slice` 写在 `piece` 前面，所以这一行的 piece 分支被吃掉、只落成 slice。"
        "双写把该 FNDDS 行当成「piece 与 slice 可互换的同一份量」。"
        "各键仍独立 first-wins：若更早已有独立 `1 piece` 行，piece 不被覆盖；"
        "若复合行排在最前，则两个键都由它定值。",
        "",
        "落地时若要保住冻结 split，应 **旧键冻结后再补缺失的一侧**："
        "已有 slice=30 的牛排只补 piece=30，不会去改 cheddar 已有的 slice=21。",
        "",
        "### QNS",
        "",
        "`modifier == 90000`，或 `portion_description` 以 `quantity not` 开头"
        " → 键 `qns`。`gram_weight <= 0` 丢弃。",
        "",
        "### 旧键映射与仍丢弃的行",
        "",
        "cup/tbsp/tsp/slice/piece/can 沿用当前 builder 的 household 正则；"
        "banana/egg/medium/large/small 仍塌缩为 piece。"
        "household 单位优先于 thick/thin/regular/oz，"
        "因此 `1 large or thick slice` 仍是 slice，不会变成 thick。",
        "",
        "Guideline-amount 行仍丢弃。含 `mashed` 的行、以及同时含 `sliced` 与 `cup`"
        "的行仍丢弃，避免 mashed cup 抢走 cup 键。",
        "",
        "新增键: "
        + ", ".join(f"`{k}`" for k in policy["new_keys"])
        + "。`fl_oz` 与重量 `oz` 分开；"
        "`5.3 oz container` 这类包装行不算 oz。",
        "",
        "## 漂移统计（相对当前 catalog）",
        "",
        f"- 对比食物数: **{stats['foods_compared']}**"
        f"（catalog 内 FNDDS {stats['fndds_foods_in_catalog']}；"
        f"survey 提出份量 {stats['fndds_foods_with_proposed_portions']}）",
        f"- 有任何差异（含仅新增键）: **{stats['foods_with_any_diff']}**",
        f"- 旧键 cup/tbsp/tsp/slice/piece/can 值被改或被删: "
        f"**{stats['foods_old_key_changed_or_removed']}**",
        f"- 仅新增键、旧键原值不动: **{stats['foods_only_new_keys_added']}**",
        f"- 完全零漂移: **{stats['foods_zero_drift']}**",
        "",
        "旧键被改的主因是 **seq_num 排序改变了 first-wins 赢家**："
        "同一食物有多行映到同一旧键时，当前 catalog 按 zip 文件顺序取第一行，"
        "本 dry-run 按 FNDDS `seq_num` 取第一行。典型例子：",
        "",
        "- Cheddar `1 cracker-size slice`（seq 1, 9 g）先于 `1 slice`（seq 2, 21 g）"
        " → `slice` 21→9",
        "- Apple `1 small`（seq 1, 165 g）先于 `1 medium`（seq 2, 200 g）"
        " → `piece` 200→165（small/medium/large 仍按当前 builder 塌缩为 piece）",
        "",
        "## Gold 25 种食物",
        "",
    ]

    if gold["old_key_zero_drift"]:
        lines.append(
            f"**结论：{gold['n_foods']} 种 gold 食物的旧份量键全部不变，"
            "冻结 split 克数零漂移。**"
        )
    else:
        lines.append(
            f"**结论：{gold['n_foods']} 种 gold 食物中，"
            f"{len(gold['foods_with_old_key_changes'])} 种旧键会变；"
            f"{len(gold['item_drifts'])} 条 gold 行的克数会随旧键一起变。"
            "按本策略落地会破坏冻结 split，不允许重建 catalog。**"
        )
    lines += ["", "### 每种食物", "",
              "| food_id | fdc_id | 类型 | 旧键 | 新键变化 | QNS |",
              "|---|---|---|---|---|---|"]
    for row in gold["foods"]:
        delta_bits = []
        for key, pair in row["changed"].items():
            delta_bits.append(f"{key} {pair['old']:g}→{pair['new']:g}")
        for key, grams in row["added"].items():
            delta_bits.append(f"+{key}={grams:g}")
        for key, grams in row["removed"].items():
            delta_bits.append(f"-{key}={grams:g}")
        src = "FNDDS" if row["in_fndds"] else row["data_type"] or "—"
        qns = "—" if row["qns"] is None else f"{row['qns']:g}"
        lines.append(
            f"| `{row['food_id']}` | `{row['fdc_id']}` | {src} | "
            f"{_fmt_portions(row['old'])} | "
            f"{'; '.join(delta_bits) or '零漂移'} | {qns} |"
        )

    lines += ["", "### 旧键被改的 gold 食物", ""]
    if not gold["foods_with_old_key_changes"]:
        lines.append("无。")
    else:
        lines.append("| food_id | 变化 |")
        lines.append("|---|---|")
        for row in gold["foods_with_old_key_changes"]:
            bits = [
                f"{k} {v['old']:g}→{v['new']:g}"
                for k, v in row["changed"].items()
            ]
            bits += [f"{k} 删除（原 {g:g}）" for k, g in row["removed"].items()]
            lines.append(f"| `{row['food_id']}` | {'; '.join(bits)} |")

    lines += ["", "### Gold 克数会变的条目", ""]
    if not gold["item_drifts"]:
        lines.append("无。")
    else:
        lines.append("| item id | 来源 | 食物 | 键 | 旧克数 | 新克数 |")
        lines.append("|---|---|---|---|---|---|")
        for row in gold["item_drifts"]:
            lines.append(
                f"| `{row['item_id']}` | `{row['source']}` | `{row['food_id']}` | "
                f"`{row['key']}` × {row['factor']:g} | "
                f"{row['old_grams']:g} | {row['new_grams']:g} |"
            )

    n_gold_fndds = sum(1 for row in gold["foods"] if row["in_fndds"])
    n_gold_qns = sum(1 for row in gold["foods"] if row["qns"] is not None)
    qns_eq: list[str] = []
    qns_ne: list[str] = []
    for row in gold["foods"]:
        qns = row["qns"]
        if qns is None:
            continue
        old = row["old"]
        default = next((old[k] for k in ("piece", "slice", "cup") if k in old), None)
        label = f"`{row['food_id']}` QNS={qns:g}"
        if default is None:
            qns_ne.append(f"{label}（无 piece/slice/cup）")
        elif default == qns:
            qns_eq.append(f"{label} = {next(k for k in ('piece','slice','cup') if k in old)} {default:g}")
        else:
            qns_ne.append(
                f"{label} ≠ serving-default "
                f"{next(k for k in ('piece','slice','cup') if k in old)}={default:g}"
            )

    lines += [
        "",
        "## QNS 覆盖",
        "",
        f"- FNDDS 对比集里带 `qns` 键的食物: **{stats['foods_with_qns']}** / "
        f"{stats['foods_compared']}",
        f"- Gold 25 种里来自 FNDDS 的: **{n_gold_fndds}**；其中有 QNS 的: "
        f"**{n_gold_qns}**（其余为 SR Legacy，survey.zip 无行，本 dry-run 不动它们）",
        "",
        "QNS 与当前 serving 回退（piece→slice→cup）一致的 gold 食物:",
        "",
    ]
    if qns_eq:
        lines += [f"- {line}" for line in qns_eq]
    else:
        lines.append("- （无）")
    lines += ["", "QNS 与 serving 回退不一致（日后改 serving 回退时的灰区候选）:", ""]
    if qns_ne:
        lines += [f"- {line}" for line in qns_ne]
    else:
        lines.append("- （无）")

    safe_ok = gold["safe_overlay_old_key_zero_drift"]
    lines += [
        "",
        "## 落地建议（本脚本未改 builder）",
        "",
        "按本 dry-run 的 seq_num + first-wins **不能**直接重建 catalog："
        f"gold 旧键非零漂移，{len(gold['item_drifts'])} 条冻结克数会变。",
        "",
        "若要完整接入且冻结 split 零漂移，builder 应改成 **旧键冻结、只追加新键**：",
        "cup/tbsp/tsp/slice/piece/can 保持当前 catalog 值；"
        "只插入当前没有的 thick/thin/regular/oz/fl_oz/cubic_inch/serving/qns。",
        f"该「安全叠加」下 gold 条目漂移数为 "
        f"**{len(gold['safe_overlay_item_drifts'])}**"
        + ("，旧键零漂移成立。" if safe_ok else "，仍有漂移，需再查。"),
        "",
        "复合 `piece/slice` 建议在落地时采用本脚本的双写规则，但 **不得覆盖** "
        "已经存在的 piece/slice 值（先冻结旧键，再双写缺失的那一侧）。"
        "这样牛排一类食物会补上 `piece=30`（与现有 `slice=30` 相同），"
        "而 cheddar 的 `slice=21` 不会被 seq 1 的 cracker-size 9 g 抢走。",
        "",
        "seq_num 排序适合作为新键的稳定顺序，不适合用来重选旧键赢家。",
        "",
    ]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey", type=Path, default=_SURVEY)
    parser.add_argument("--catalog", type=Path, default=_DB)
    parser.add_argument("--split", type=Path, default=_SPLIT)
    parser.add_argument("--drift-out", type=Path, default=_DRIFT_OUT)
    parser.add_argument("--summary-out", type=Path, default=_SUMMARY_OUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.survey.is_file():
        raise FileNotFoundError(args.survey)
    if not args.catalog.is_file():
        raise FileNotFoundError(args.catalog)
    if not args.split.is_file():
        raise FileNotFoundError(args.split)

    proposed, fndds_names, qns_zero_dropped = collect_full_fndds(args.survey)
    catalog, aliases = load_catalog(args.catalog)
    split = json.loads(args.split.read_text(encoding="utf-8"))
    report = build_report(
        catalog=catalog,
        aliases=aliases,
        proposed=proposed,
        fndds_names=fndds_names,
        split=split,
        survey_zip=args.survey,
        db_path=args.catalog,
        split_path=args.split,
        qns_zero_dropped=qns_zero_dropped,
    )

    args.drift_out.parent.mkdir(parents=True, exist_ok=True)
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.drift_out.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_summary(report, args.summary_out)

    gold = report["gold"]
    stats = report["stats"]
    print(f"wrote {args.drift_out}")
    print(f"wrote {args.summary_out}")
    print(
        f"compared {stats['foods_compared']} foods; "
        f"{stats['foods_old_key_changed_or_removed']} old-key drifts; "
        f"{stats['foods_only_new_keys_added']} add-only; "
        f"qns on {stats['foods_with_qns']}"
    )
    if gold["old_key_zero_drift"]:
        print(
            f"gold: ZERO drift across {gold['n_foods']} foods / "
            f"{report['meta']['n_split_items']} items"
        )
    else:
        print(
            f"gold: NOT zero-drift — "
            f"{len(gold['foods_with_old_key_changes'])} foods, "
            f"{len(gold['item_drifts'])} item rows would change grams"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
