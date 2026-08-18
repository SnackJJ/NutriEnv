#!/usr/bin/env python3
"""Build the local FDC sqlite catalog from official CSV zips.

Default path is the v0.5 safe-overlay freeze (``data/fdc/catalog.sqlite``).
Full FNDDS strategy (seq_num first-wins) writes a *new* file:

    .venv/bin/python scripts/build_fdc_catalog.py --out data/fdc/catalog-v1.sqlite

FNDDS-only (no SR Legacy; catalog-v2) is a *new* file after dry-run approval:

    .venv/bin/python scripts/build_fdc_catalog.py --fndds-only --dry-run
    .venv/bin/python scripts/build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite

``--full`` / ``--fndds-only`` without ``--out``, or targeting catalog.sqlite /
catalog-v1.sqlite, is refused.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RAW = _ROOT / "data" / "fdc" / "raw"
_DB = _ROOT / "data" / "fdc" / "catalog.sqlite"

_NUTRIENT_BY_ID = {
    "1008": "kcal",
    "1003": "protein_g",
    "1004": "fat_g",
    "1005": "carb_g",
    "1079": "fiber_g",
    "1093": "sodium_mg",
}
_NUTRIENT_BY_NBR = {
    "208": "kcal",
    "203": "protein_g",
    "204": "fat_g",
    "205": "carb_g",
    "291": "fiber_g",
    "307": "sodium_mg",
}

# Pinned FDC ids for staples whose name-match previously picked the wrong food.
_STAPLE_FDC: dict[str, str] = {
    "oats": "2708489",
    "chicken_breast": "171477",
    "greek_yogurt": "2705424",
    "white_rice": "2708408",
}

# SR Legacy staples re-pinned when ingesting FNDDS-only (catalog-v2).
# Ticket-named: tofu 2707435, chicken 2705956, tuna 2706311.
# Remaining six: closest FNDDS form to the current SR row (see dry-run).
SR_LEGACY_STAPLES: tuple[str, ...] = (
    "chicken_breast",
    "tuna",
    "tofu",
    "salmon",
    "shrimp",
    "beef",
    "olive_oil",
    "black_beans",
    "peanut",
    "almond",
)
FNDDS_ONLY_STAPLE_FDC: dict[str, str] = {
    "chicken_breast": "2705956",
    "tuna": "2706311",
    "tofu": "2707435",
    "salmon": "2706286",
    "shrimp": "2706363",
    "beef": "2705855",
    "olive_oil": "2710186",
    "black_beans": "2707361",
    "peanut": "2707514",
    "almond": "2707486",
}


def staple_fdc_pins(*, fndds_only: bool = False) -> dict[str, str]:
    """Pinned FDC ids the builder uses for staple aliases."""
    if not fndds_only:
        return dict(_STAPLE_FDC)
    pins = dict(_STAPLE_FDC)
    pins.update(FNDDS_ONLY_STAPLE_FDC)
    return pins


# slug -> preferred official description fragments (FNDDS first, then SR).
_STAPLES: dict[str, tuple[str, ...]] = {
    "peanut_butter": ("Peanut butter",),
    "shrimp": ("Shrimp, cooked", "Crustaceans, shrimp, cooked"),
    "oats": ("Oatmeal, regular", "Oats, rolled"),
    "egg": ("Egg, whole, raw", "Egg, whole, raw, fresh"),
    "white_rice": ("Rice, white, cooked", "Rice, white, long-grain, regular, cooked"),
    "milk_whole": ("Milk, whole", "Milk, whole, 3.25%"),
    "chicken_breast": ("Chicken, breast, NS as to skin", "Chicken, broilers or fryers, breast"),
    "almond": ("Almonds, raw", "Nuts, almonds"),
    "salmon": ("Salmon, raw", "Fish, salmon, Atlantic"),
    "tofu": ("Tofu, firm", "Tofu, raw, firm"),
    "whole_wheat_bread": ("Bread, whole wheat",),
    "banana": ("Banana, raw", "Bananas, raw"),
    "broccoli": ("Broccoli, raw",),
    "greek_yogurt": ("Yogurt, Greek, plain", "Yogurt, Greek, plain, nonfat"),
    "olive_oil": ("Oil, olive",),
    "apple": ("Apple, raw", "Apples, raw, with skin"),
    "cheddar": ("Cheese, cheddar",),
    "pasta": ("Pasta, cooked", "Pasta, cooked, enriched"),
    "beef": ("Ground beef, cooked", "Beef, ground, 90% lean meat"),
    "tuna": ("Tuna, canned", "Fish, tuna, light, canned in water"),
    "potato": ("Potato, baked", "Potatoes, baked, flesh and skin"),
    "spinach": ("Spinach, raw",),
    "orange": ("Orange, raw", "Oranges, raw, navels"),
    "avocado": ("Avocado, raw", "Avocados, raw, all commercial varieties"),
    "black_beans": ("Black beans, cooked", "Beans, black, mature seeds, cooked"),
    "soy_milk": ("Soy milk", "Soymilk, original"),
    "peanut": ("Peanuts, raw", "Peanuts, all types, raw"),
}

_ALIAS_EXTRA: dict[str, list[str]] = {
    "peanut_butter": ["pb", "peanut spread"],
    "shrimp": ["prawn", "prawns"],
    "oats": ["oatmeal", "rolled oats"],
    "egg": ["eggs", "chicken egg"],
    "white_rice": ["rice", "steamed rice", "cooked rice"],
    "milk_whole": ["milk", "whole milk", "full fat milk"],
    "chicken_breast": ["chicken", "grilled chicken"],
    "almond": ["almonds", "raw almonds"],
    "salmon": ["atlantic salmon", "baked salmon"],
    "tofu": ["bean curd", "firm tofu"],
    "whole_wheat_bread": ["bread", "wholemeal bread", "brown bread"],
    "banana": ["bananas", "ripe banana"],
    "broccoli": ["broccoli florets"],
    "greek_yogurt": ["yogurt", "greek yoghurt", "plain yogurt"],
    "olive_oil": ["olive oil", "evoo", "oil"],
    "apple": ["apples"],
    "cheddar": ["cheddar cheese"],
    "pasta": ["spaghetti", "noodles"],
    "beef": ["ground beef"],
    "tuna": ["canned tuna"],
    "potato": ["baked potato"],
    "spinach": ["baby spinach"],
    "orange": ["oranges"],
    "avocado": ["avocados"],
    "black_beans": ["black bean"],
    "soy_milk": ["soy milk"],
    "peanut": ["peanuts"],
}

_ALLERGEN_RULES: list[tuple[tuple[str, ...], str]] = [
    (("peanut",), "peanut"),
    (("shrimp", "prawn", "crab", "lobster", "shellfish", "crayfish"), "shellfish"),
    (("salmon", "tuna", "cod", "tilapia", "fish, "), "fish"),
    (("almond", "walnut", "cashew", "pecan", "hazelnut", "pistachio"), "tree_nut"),
    (("soy milk", "soymilk", "tofu", "soybean", "soy sauce"), "soy"),
    (("yogurt", "cheddar", "cheese", "milk, ", "milk whole", "whey"), "milk"),
    (("egg, ", "egg whole", "eggs,"), "egg"),
    (("wheat", "flour", "pasta", "bread, ", "noodle"), "wheat"),
    (("wheat", "flour", "pasta", "bread, "), "gluten"),
]

_UNIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcups?\b"), "cup"),
    (re.compile(r"\btablespoons?\b|\btbsp\b"), "tbsp"),
    (re.compile(r"\bteaspoons?\b|\btsp\b"), "tsp"),
    (re.compile(r"\bslices?\b"), "slice"),
    (re.compile(r"\bpieces?\b|\beach\b"), "piece"),
    (re.compile(r"\bcans?\b"), "can"),
    (re.compile(r"\bbanana\b|\begg\b|\bmedium\b|\blarge\b|\bsmall\b"), "piece"),
]

# Safe-overlay policy (adjudication trap A, strict option (a)):
# Old-class keys are frozen by the legacy _collect_portions scan (zip file
# order, first-wins). Ordinary overlay rows must never insert a missing
# old-class key. The only extra write path for an old-class key is a
# compound FNDDS "piece/slice" row filling the side the legacy scan missed.
_OLD_PORTION_KEYS = frozenset({"cup", "tbsp", "tsp", "slice", "piece", "can"})
# serving is not written this round. resolve_portion already maps
# serving/portion/bowl/plate/order onto portions["serving"] and falls
# back to piece→slice→cup when that key is absent. Wiring a catalog
# serving value is a later standalone project (react.py handbook +
# phrase→key→grams tests must land in the same change).
_NEW_PORTION_KEYS = frozenset(
    {
        "thick",
        "thin",
        "regular",
        "oz",
        "oz_yield",
        "fl_oz",
        "cubic_inch",
        "qns",
    }
)
_QNS_MODIFIER = "90000"
_HOUSEHOLD_UNITS: list[tuple[re.Pattern[str], str]] = _UNIT_PATTERNS[:6]
_PIECE_WORD = re.compile(r"\bpieces?\b")
_SLICE_WORD = re.compile(r"\bslices?\b")
_FL_OZ_UNIT_ROW = re.compile(r"^1\s+fl\.?\s*oz\b")
_CUBIC_INCH = re.compile(r"\bcubic inch(?:es)?\b")
_OZ_UNIT_ROW = re.compile(r"^1\s+oz\b")
_SIZE_AS_PIECE = re.compile(r"\bbanana\b|\begg\b|\bmedium\b|\blarge\b|\bsmall\b")
# Full-strategy new keys (catalog-v1). Household units win first, so
# "1 large or thick slice" never reaches this list. fl_oz is listed
# before oz so "1 fl oz" is not stored as oz. oz skips package rows.
_FULL_NEW_UNITS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bthick\b"), "thick"),
    (re.compile(r"\bthin\b"), "thin"),
    (re.compile(r"\bregular\b"), "regular"),
    (re.compile(r"\bcubic inch(?:es)?\b"), "cubic_inch"),
    (re.compile(r"\bfl\.?\s*oz\b"), "fl_oz"),
    (
        re.compile(r"\boz\b(?!\s+(?:container|bag|bottle|package|cup)\b)"),
        "oz",
    ),
    (re.compile(r"\b(?:single\s+)?servings?\b"), "serving"),
]


def _open_zip_dir(zip_path: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(zip_path)


def _zip_has(zf: zipfile.ZipFile, suffix: str) -> bool:
    return any(name.rsplit("/", 1)[-1] == suffix for name in zf.namelist())


def _zip_member(zf: zipfile.ZipFile, suffix: str) -> str:
    for name in zf.namelist():
        if name.rsplit("/", 1)[-1] == suffix:
            return name
    raise FileNotFoundError(suffix)


def _iter_csv(zf: zipfile.ZipFile, suffix: str):
    name = _zip_member(zf, suffix)
    with zf.open(name) as handle:
        reader = csv.DictReader(line.decode("utf-8", errors="replace") for line in handle)
        yield from reader


def _allergens(name: str) -> list[str]:
    lower = name.lower()
    tags: set[str] = set()
    if "peanut butter" in lower:
        return ["peanut"]
    for needles, tag in _ALLERGEN_RULES:
        if any(needle in lower for needle in needles):
            tags.add(tag)
    return sorted(tags)


def _portion_key(text: str) -> str | None:
    blob = text.lower().strip()
    if not blob or blob.startswith("quantity not") or "guideline" in blob:
        return None
    if "mashed" in blob or "sliced" in blob and "cup" in blob:
        return None
    for pattern, key in _UNIT_PATTERNS:
        if pattern.search(blob):
            return key
    return None


def _merge_portion(portions: dict[str, float], key: str, grams: float) -> None:
    if grams <= 0 or key in portions:
        return
    portions[key] = round(grams, 2)


def _collect_portions(zf: zipfile.ZipFile) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if not _zip_has(zf, "food_portion.csv"):
        return out
    for row in _iter_csv(zf, "food_portion.csv"):
        fdc_id = row["fdc_id"]
        grams_raw = row.get("gram_weight") or ""
        try:
            grams = float(grams_raw)
        except ValueError:
            continue
        text = " ".join(
            part for part in (row.get("portion_description"), row.get("modifier")) if part
        )
        key = _portion_key(text)
        if key is None:
            continue
        _merge_portion(out.setdefault(fdc_id, {}), key, grams)
    return out


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


def _overlay_keys(description: str, modifier: str) -> list[str]:
    """Keys the safe overlay may write from one FNDDS row.

    Compound ``piece/slice`` is the only path that may emit an old-class key.
    Physical ounce rows (``1 oz, cooked``) and yield rows (``1 oz yields``)
    are split so they cannot first-wins into the same ``oz`` key (trap B).
    ``fl_oz`` is only the true unit row that starts with ``1 fl oz``;
    container totals such as ``1 soda (10 fl oz)`` are not per-fl_oz grams.
    """
    desc = (description or "").strip()
    desc_l = desc.lower()
    blob = " ".join(part for part in (desc_l, (modifier or "").strip()) if part)
    if (modifier or "") == _QNS_MODIFIER or desc_l.startswith("quantity not"):
        return ["qns"]
    if not blob or "guideline" in blob:
        return []
    if "mashed" in blob or ("sliced" in blob and "cup" in blob):
        return []
    if _PIECE_WORD.search(desc_l) and _SLICE_WORD.search(desc_l):
        return ["piece", "slice"]
    if any(pattern.search(blob) for pattern, _key in _HOUSEHOLD_UNITS):
        return []
    if _FL_OZ_UNIT_ROW.match(desc_l):
        return ["fl_oz"]
    if _OZ_UNIT_ROW.match(desc_l):
        return ["oz_yield"] if "yield" in desc_l else ["oz"]
    if _CUBIC_INCH.search(desc_l):
        return ["cubic_inch"]
    if re.search(r"\bthick\b", desc_l):
        return ["thick"]
    if re.search(r"\bthin\b", desc_l):
        return ["thin"]
    if re.search(r"\bregular\b", desc_l):
        return ["regular"]
    return []


def _apply_safe_overlay(
    zf: zipfile.ZipFile, portions: dict[str, dict[str, float]]
) -> None:
    """Append new FNDDS keys onto already-frozen old-class portions.

    New keys first-win after a stable ``(fdc_id, seq_num, portion id)`` sort.
    Existing keys are never overwritten (``_merge_portion`` first-wins).
    """
    if not _zip_has(zf, "food_portion.csv"):
        return
    rows = list(_iter_csv(zf, "food_portion.csv"))
    rows.sort(key=_row_sort_key)
    for row in rows:
        try:
            grams = float(row.get("gram_weight") or "")
        except ValueError:
            continue
        keys = _overlay_keys(
            row.get("portion_description") or "", row.get("modifier") or ""
        )
        if not keys:
            continue
        bucket = portions.setdefault(row["fdc_id"], {})
        for key in keys:
            if key in _OLD_PORTION_KEYS and key not in {"piece", "slice"}:
                raise RuntimeError(f"safe overlay must not write old-class key {key!r}")
            if key not in _OLD_PORTION_KEYS and key not in _NEW_PORTION_KEYS:
                raise RuntimeError(f"unknown overlay key {key!r}")
            _merge_portion(bucket, key, grams)


def _portion_keys_full(description: str, modifier: str) -> list[str]:
    """Keys one FNDDS row writes under the full (catalog-v1) strategy.

    Matches the dry-run POLICY in ``scripts/fndds_dry_run.py``: QNS,
    compound piece/slice dual-write, household before size/new units,
    ``oz`` not ``oz_yield``, package rows not oz.
    """
    desc = (description or "").strip()
    blob = " ".join(part for part in (desc, modifier or "") if part).lower()
    if (modifier or "") == _QNS_MODIFIER or desc.lower().startswith("quantity not"):
        return ["qns"]
    if not blob or "guideline" in blob:
        return []
    if "mashed" in blob or ("sliced" in blob and "cup" in blob):
        return []

    keys: list[str] = []
    if _PIECE_WORD.search(blob) and _SLICE_WORD.search(blob):
        keys.extend(("piece", "slice"))

    for pattern, key in _HOUSEHOLD_UNITS:
        if key in keys:
            continue
        if pattern.search(blob):
            keys.append(key)
            break
    if keys:
        return keys

    if _SIZE_AS_PIECE.search(blob):
        return ["piece"]

    for pattern, key in _FULL_NEW_UNITS:
        if pattern.search(blob):
            return [key]
    return []


def collect_portions_full(
    rows: list[dict[str, str]],
) -> dict[str, dict[str, float]]:
    """Full FNDDS scan: sort by (fdc_id, seq_num, id), first-wins per key.

    Public so the dry-run parity test can call the builder scan without
    going through zip ingest or sqlite. gram_weight <= 0 is dropped.
    """
    ordered = sorted(rows, key=_row_sort_key)
    out: dict[str, dict[str, float]] = {}
    for row in ordered:
        fdc_id = row.get("fdc_id") or ""
        keys = _portion_keys_full(
            row.get("portion_description") or "", row.get("modifier") or ""
        )
        try:
            grams = float(row.get("gram_weight") or "")
        except ValueError:
            continue
        for key in keys:
            _merge_portion(out.setdefault(fdc_id, {}), key, grams)
    return out


def _collect_portions_full(zf: zipfile.ZipFile) -> dict[str, dict[str, float]]:
    if not _zip_has(zf, "food_portion.csv"):
        return {}
    return collect_portions_full(list(_iter_csv(zf, "food_portion.csv")))


def _collect_nutrients(zf: zipfile.ZipFile) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in _iter_csv(zf, "food_nutrient.csv"):
        key = _NUTRIENT_BY_ID.get(row["nutrient_id"]) or _NUTRIENT_BY_NBR.get(
            row["nutrient_id"]
        )
        if key is None:
            continue
        try:
            amount = float(row["amount"])
        except (TypeError, ValueError):
            continue
        bucket = out.setdefault(row["fdc_id"], {})
        if key not in bucket:
            bucket[key] = amount
    return out


def _ingest_pack(
    zf: zipfile.ZipFile,
    *,
    default_type: str,
    foods: dict[str, dict],
    overlay: bool = False,
    full: bool = False,
) -> None:
    nutrients = _collect_nutrients(zf)
    if full:
        portions = _collect_portions_full(zf)
    else:
        portions = _collect_portions(zf)
        if overlay:
            _apply_safe_overlay(zf, portions)
    for row in _iter_csv(zf, "food.csv"):
        fdc_id = row["fdc_id"]
        name = (row.get("description") or "").strip()
        if not name:
            continue
        macros = nutrients.get(fdc_id) or {}
        if "kcal" not in macros:
            continue
        foods[fdc_id] = {
            "food_id": fdc_id,
            "name": name,
            "data_type": row.get("data_type") or default_type,
            "category": row.get("food_category_id") or "",
            "nutrients": macros,
            "portions": portions.get(fdc_id) or {},
            "allergen_tags": _allergens(name),
            "aliases": [],
        }


def _ingest_branded(zf: zipfile.ZipFile, foods: dict[str, dict]) -> None:
    brands: dict[str, dict] = {}
    try:
        for row in _iter_csv(zf, "branded_food.csv"):
            brands[row["fdc_id"]] = row
    except FileNotFoundError:
        return
    _ingest_pack(zf, default_type="branded_food", foods=foods)
    for fdc_id, row in brands.items():
        entry = foods.get(fdc_id)
        if entry is None:
            continue
        extras = []
        for field in ("brand_owner", "brand_name", "gtin_upc", "ingredients"):
            value = (row.get(field) or "").strip()
            if value:
                extras.append(value)
        if extras:
            entry["aliases"] = extras[:4]
        serving = row.get("serving_size")
        unit = (row.get("serving_size_unit") or "").lower()
        try:
            grams = float(serving) if serving else 0.0
        except ValueError:
            grams = 0.0
        if grams > 0 and unit in {"g", "grm"}:
            entry["portions"].setdefault("piece", grams)


def ingest_sources(
    *,
    fndds_only: bool = False,
    include_branded: bool = False,
) -> list[tuple[Path, str, bool]]:
    """Zip packs the builder will ingest: ``(path, default_type, branded)``."""
    survey = _RAW / "fndds.zip" if (_RAW / "fndds.zip").is_file() else _RAW / "survey.zip"
    packs: list[tuple[Path, str, bool]] = [
        (survey, "survey_fndds_food", False),
    ]
    if not fndds_only:
        packs.append((_RAW / "sr_legacy.zip", "sr_legacy_food", False))
    if include_branded:
        packs.append((_RAW / "branded.zip", "branded_food", True))
    return packs


def assign_staples(
    foods: dict[str, dict], *, fndds_only: bool = False
) -> dict[str, str]:
    """Map staple slugs onto ``food_id``s present in ``foods``."""
    aliases: dict[str, str] = {}
    names = {fid: entry["name"].lower() for fid, entry in foods.items()}
    pins = staple_fdc_pins(fndds_only=fndds_only)
    for slug, needles in _STAPLES.items():
        chosen = None
        pinned = pins.get(slug)
        if pinned and pinned in foods:
            chosen = pinned
        for needle in needles if chosen is None else ():
            needle_l = needle.lower()
            fndds = [
                fid
                for fid, name in names.items()
                if foods[fid]["data_type"] == "survey_fndds_food"
                and (name == needle_l or name.startswith(needle_l + ",") or name.startswith(needle_l + " "))
            ]
            if not fndds:
                compact = needle_l.replace(",", "")
                fndds = [
                    fid
                    for fid, name in names.items()
                    if foods[fid]["data_type"] == "survey_fndds_food"
                    and name.startswith(compact)
                ]
            if fndds:
                chosen = sorted(fndds)[0]
                break
            if fndds_only:
                continue
            sr = [
                fid
                for fid, name in names.items()
                if needle_l in name and foods[fid]["data_type"] == "sr_legacy_food"
            ]
            if sr:
                chosen = sorted(sr)[0]
                break
        if chosen is None:
            print(f"warning: no FDC row for staple {slug}")
            continue
        aliases[slug] = chosen
        extra = list(_ALIAS_EXTRA.get(slug, []))
        extra.append(slug)
        entry = foods[chosen]
        have = {a.lower() for a in entry["aliases"]}
        for alias in extra:
            if alias.lower() not in have:
                entry["aliases"].append(alias)
                have.add(alias.lower())
    return aliases


# Representative spoken forms used to confirm each re-pin has a PortionFact.
# "a chicken breast" is a cut noun and stays None (ticket 02); the chicken
# fact is the piece row (105 g) on 2705956.
FNDDS_STAPLE_PORTION_FACTS: dict[str, tuple[str, float]] = {
    "chicken_breast": ("a piece", 105.0),
    "tuna": ("a can", 75.0),
    "tofu": ("a piece", 120.0),
    "salmon": ("a piece", 140.0),
    "shrimp": ("a piece", 10.0),
    "beef": ("a piece", 65.0),
    "olive_oil": ("a tablespoon", 14.0),
    "black_beans": ("a cup", 180.0),
    "peanut": ("a cup", 146.0),
    "almond": ("a cup", 141.0),
}

# Reviewer notes: why this FNDDS row, not a sibling. Not gram facts.
FNDDS_STAPLE_WHY: dict[str, str] = {
    "chicken_breast": (
        "票面候选。对应 SR 去皮烤胸；piece=105 是 catalog-v1 完整策略对 "
        "2705956 的 first-wins 行。"
    ),
    "tuna": "票面候选。对应 SR 水浸罐头；FNDDS can=75（SR can=165）。",
    "tofu": (
        "AGY 核验：FNDDS 纯豆腐官方名 Soybean curd（底层 SR 16127 为 soft）。"
        "当前 SR 钉的是 firm；cup 126→248。"
    ),
    "salmon": (
        "SR 是 cooked dry heat。选 baked or broiled（2706286），"
        "与 NFS 2706285 同份量表；不用 raw 2706284（无 piece）。"
    ),
    "shrimp": (
        "SR 是 cooked。选 steamed or boiled（2706363），"
        "与 NFS 2706360 同份量表。"
    ),
    "beef": (
        "SR 是 90/10 cooked patty。选 Beef, ground, patty（2705855，piece=65）；"
        "不用无 piece 的 2705854 Beef, ground。"
    ),
    "olive_oil": "FNDDS 唯一纯橄榄油行 2710186。tbsp 13.5→14；无 tsp。",
    "black_beans": (
        "SR 是 boiled without salt。选 from dried, no added fat（2707361）；"
        "不用 NFS 2707359（cup=185）或 canned。"
    ),
    "peanut": "SR 是 raw。选 unroasted 2707514；cup 仍 146，补 oz/qns。",
    "almond": (
        "当前 SR 168592 是 honey roasted（name-match 误伤）。"
        "针写 Almonds, raw → unroasted 2707486。"
    ),
}

_GOLD_SOURCES = (
    ("s0", "ledger"),
    ("oracle", "ledger_tail"),
    ("s0", "last_plan"),
    ("oracle", "last_plan"),
)


def _read_catalog(
    db_path: Path,
) -> tuple[dict[str, dict], dict[str, str], dict[str, int]]:
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
        counts: dict[str, int] = {}
        for data_type, n in conn.execute(
            "SELECT data_type, COUNT(*) FROM foods GROUP BY data_type"
        ):
            counts[str(data_type)] = int(n)
    finally:
        conn.close()
    return foods, aliases, counts


def _confirm_portion_fact(
    slug: str, name: str, portions: dict[str, float]
) -> dict:
    from nutrienv.world.portions import resolve_portion

    phrase, expected = FNDDS_STAPLE_PORTION_FACTS[slug]
    catalog = {slug: {"name": name, "portions": portions, "aliases": [slug]}}
    resolved = resolve_portion(slug, phrase, catalog)
    cut_phrase = "a chicken breast" if slug == "chicken_breast" else None
    cut_resolved = (
        resolve_portion(slug, cut_phrase, catalog) if cut_phrase else None
    )
    return {
        "phrase": phrase,
        "expected_g": expected,
        "resolved_g": resolved,
        "ok": resolved == expected,
        "cut_noun_phrase": cut_phrase,
        "cut_noun_resolved_g": cut_resolved,
    }


def plan_fndds_only_rebuild(
    *,
    live_catalog: Path,
    reference_catalog: Path,
    split_path: Path | None = None,
) -> dict:
    """Read-only catalog-v2 plan. Does not write any sqlite."""
    live_foods, live_aliases, live_counts = _read_catalog(live_catalog)
    ref_foods, _ref_aliases, ref_counts = _read_catalog(reference_catalog)
    pins = staple_fdc_pins(fndds_only=True)
    swaps: list[dict] = []
    for slug in SR_LEGACY_STAPLES:
        old_id = live_aliases.get(slug, "")
        new_id = pins[slug]
        old_entry = live_foods.get(old_id) or {}
        new_entry = ref_foods.get(new_id) or {}
        old_portions = dict(old_entry.get("portions") or {})
        new_portions = dict(new_entry.get("portions") or {})
        fact = _confirm_portion_fact(
            slug, str(new_entry.get("name") or ""), new_portions
        )
        swaps.append(
            {
                "slug": slug,
                "old_fdc_id": old_id,
                "old_name": old_entry.get("name") or "",
                "old_data_type": old_entry.get("data_type") or "",
                "old_portions": old_portions,
                "new_fdc_id": new_id,
                "new_name": new_entry.get("name") or "",
                "new_data_type": new_entry.get("data_type") or "",
                "new_portions": new_portions,
                "portion_fact": fact,
            }
        )
    survey_n = live_counts.get("survey_fndds_food", 0)
    gold_rows: list[dict] = []
    if split_path is not None:
        split = json.loads(split_path.read_text(encoding="utf-8"))
        slugs = set(SR_LEGACY_STAPLES)
        for item in split.get("items") or []:
            for bucket, field in _GOLD_SOURCES:
                parent = item.get(bucket) or {}
                if not isinstance(parent, dict):
                    continue
                for row in parent.get(field) or []:
                    if not isinstance(row, dict):
                        continue
                    food_id = row.get("food_id")
                    if food_id not in slugs:
                        continue
                    try:
                        grams = float(row["grams"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    gold_rows.append(
                        {
                            "item_id": item.get("id") or "",
                            "source": f"{bucket}.{field}",
                            "slug": food_id,
                            "grams": grams,
                        }
                    )
    return {
        "wrote_catalog_v2": False,
        "counts": {
            "survey_fndds_food": survey_n,
            "sr_legacy_food": live_counts.get("sr_legacy_food", 0),
            "catalog_v2_foods": survey_n,
            "reference_survey_fndds_food": ref_counts.get("survey_fndds_food", 0),
        },
        "staple_swaps": swaps,
        "gold_rows": gold_rows,
    }


def _fmt_portions(portions: dict) -> str:
    if not portions:
        return "—"
    return ", ".join(f"{k}={v:g}" for k, v in sorted(portions.items()))


def _portion_deltas(old: dict, new: dict) -> list[str]:
    bits: list[str] = []
    keys = sorted(set(old) | set(new))
    for key in keys:
        if key in old and key in new and old[key] != new[key]:
            bits.append(f"{key} {old[key]:g}→{new[key]:g}")
        elif key in old and key not in new:
            bits.append(f"-{key}={old[key]:g}")
        elif key not in old and key in new:
            bits.append(f"+{key}={new[key]:g}")
    return bits


def write_catalog_v2_dryrun(plan: dict, dest: Path) -> None:
    """Write the STEP 1 dry-run report. Does not write catalog-v2.sqlite."""
    counts = plan["counts"]
    swaps = plan["staple_swaps"]
    gold_rows = plan.get("gold_rows") or []
    lines: list[str] = [
        "# catalog-v2 dry-run：FNDDS-only + staple 重钉",
        "",
        "只读对照：**不写** `data/fdc/catalog-v2.sqlite`，不改 `catalog.sqlite`、",
        "`catalog-v1.sqlite`、任何 `data/splits/*.json`。本文件是 AGENTS.md 纪律 2",
        "要求的落地前清单，供 codex 审查 + 主 agent 裁决后再重建。",
        "",
        "复跑：",
        "",
        "```",
        ".venv/bin/python scripts/build_fdc_catalog.py --fndds-only --dry-run",
        "```",
        "",
        "## 框定",
        "",
        "- catalog-v2 是新文件（`data/fdc/catalog-v2.sqlite`），不覆盖",
        "  `catalog.sqlite` 与 `catalog-v1.sqlite`。",
        "- 构建策略与 catalog-v1 相同（`--full`：seq_num first-wins），只是不 ingest",
        "  SR Legacy，并把 10 个 SR staple 重钉到 FNDDS 等价条目。",
        "- v0.5-gold 绑 `catalog.sqlite`（sha 见该 split 的 `catalog_sha256`），",
        "  本 dry-run 与日后 catalog-v2 对其零影响。",
        "",
        "## 食物数对账",
        "",
        f"- 当前 `catalog.sqlite` / `catalog-v1.sqlite` 的 `survey_fndds_food`："
        f"**{counts['survey_fndds_food']}**",
        f"- 当前 `sr_legacy_food`：**{counts['sr_legacy_food']}**（catalog-v2 将全部丢弃）",
        f"- catalog-v2 预计食物数：**{counts['catalog_v2_foods']}**（= 对账后的 FNDDS 数）",
        f"- catalog-v1 内 `survey_fndds_food`：**{counts['reference_survey_fndds_food']}**",
        "  （与 live 一致则对账闭合）",
        "",
        "票面曾写 5432：那是 `survey.zip` `food.csv` 行数。其中 `2705383` Milk, human",
        "无 kcal，builder 不入库，所以 catalog 实测是 **5431**。catalog-v2 用 5431，",
        "不硬编码 5432。",
        "",
        "## 哪些 staple 换条目",
        "",
        "| slug | 当前 SR id | 当前名 | FNDDS id | FNDDS 名 |",
        "|---|---|---|---|---|",
    ]
    for row in swaps:
        lines.append(
            f"| `{row['slug']}` | `{row['old_fdc_id']}` | {row['old_name']} | "
            f"`{row['new_fdc_id']}` | {row['new_name']} |"
        )
    lines += [
        "",
        "选型说明：tofu / chicken / tuna 用票面已点名的 FNDDS id；其余 7 个按当前",
        "SR 行的形态就近选 catalog-v1 里已有的 FNDDS 行（cooked patty / unroasted /",
        "olive oil / dried no-fat beans）。详见每条 PortionFact。",
        "",
        "## 哪些食物克数会变",
        "",
        "相对 **catalog-v1**（同 `--full` 策略）：FNDDS 食物份量键 **0 变**。变化只来自",
        "10 个 staple 别名换条目（旧 SR 行随 7793 条 SR 一起消失）。",
        "",
        "相对 **catalog.sqlite**（v0.5 safe-overlay）：FNDDS 旧键还有 catalog-v1 已记录",
        "的 861 处取值变化（见 `reports/catalog-v1-dryrun.md`）。那些变化已经在",
        "catalog-v1 落地；catalog-v2 继承 catalog-v1 的 FNDDS 份量，不再另变。",
        "v0.5-gold 不读 catalog-v2，冻结 JSON 克数不动。",
        "",
        "| slug | 当前 portions | FNDDS portions | 克数变化 |",
        "|---|---|---|---|",
    ]
    for row in swaps:
        delta = _portion_deltas(row["old_portions"], row["new_portions"])
        change = "; ".join(delta) if delta else "无同键取值变化"
        lines.append(
            f"| `{row['slug']}` | {_fmt_portions(row['old_portions'])} | "
            f"{_fmt_portions(row['new_portions'])} | {change} |"
        )
    lines += [
        "",
        "## 每条 staple 的 FNDDS target + PortionFact",
        "",
    ]
    for row in swaps:
        fact = row["portion_fact"]
        ok = "通过" if fact["ok"] else "失败"
        lines += [
            f"### `{row['slug']}` → `{row['new_fdc_id']}` {row['new_name']}",
            "",
            f"- 当前：`{row['old_fdc_id']}` [{row['old_data_type']}] {row['old_name']}",
            f"- 新 portions：`{_fmt_portions(row['new_portions'])}`",
            f"- 选型：{FNDDS_STAPLE_WHY[row['slug']]}",
            f"- PortionFact：`{fact['phrase']}` → **{fact['expected_g']:g} g**"
            f"（resolve_portion={fact['resolved_g']}，{ok}）",
        ]
        if fact.get("cut_noun_phrase"):
            lines.append(
                f"- 票面例句 `{fact['cut_noun_phrase']}`：resolve_portion="
                f"{fact['cut_noun_resolved_g']}（ticket 02 切块名词保持 None；"
                f"piece=105 可解析的是 `a piece`，不是裸 `a chicken breast`）"
            )
        lines.append("")
    n_gold = len(gold_rows)
    by_slug: dict[str, int] = {}
    for row in gold_rows:
        by_slug[row["slug"]] = by_slug.get(row["slug"], 0) + 1
    lines += [
        "## v0.5-gold 影响（绑旧 catalog，零落地）",
        "",
        f"split 里这 10 个 slug 共 **{n_gold}** 行（peanut 不在 gold 25 里）。",
        "冻结克数写在 JSON 里，不随 catalog-v2 变。若有人误把 v0.5 指到 catalog-v2，",
        "别名会换 FDC id、营养素与份量表都会变；household 克数（tuna can 165、",
        "tofu cup 126、black_beans cup 172、olive_oil tbsp 13.5 / tsp 4.5）将不再",
        "等于新表。**本票不改 v0.5-gold，也不改 catalog.sqlite。**",
        "",
        "| slug | gold 行数 |",
        "|---|---:|",
    ]
    for slug in SR_LEGACY_STAPLES:
        lines.append(f"| `{slug}` | {by_slug.get(slug, 0)} |")
    lines += [
        "",
        "## 验收冲突（STEP 1 记下，不改 resolve_portion）",
        "",
        "ticket 06 验收 2 写 chicken `\"a chicken breast\"` → piece 105g。",
        "ticket 02 已把 `breast` 列为切块名词：无同名 portion 键则 `resolve_portion`",
        "返回 None（`tests/test_portions.py` 钉死）。2705956 的 PortionFact 是",
        "`piece=105`；`a piece` 解析为 105g，裸 `a chicken breast` 仍是 None。",
        "STEP 2 落地前由主 agent 裁定是否改语法，本 dry-run 不猜。",
        "",
        "## 裁决请求",
        "",
        "请 codex 独立审查本清单，主 agent 裁决 APPROVE 后再允许：",
        "`build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite`。",
        "",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _protected_catalogs() -> tuple[Path, ...]:
    return (_DB.resolve(), (_DB.parent / "catalog-v1.sqlite").resolve())


def build(
    include_branded: bool,
    dest: Path | None = None,
    full: bool = False,
    fndds_only: bool = False,
) -> Path:
    if fndds_only:
        full = True
        if dest is None or dest.resolve() in _protected_catalogs():
            raise ValueError(
                "fndds-only rebuild must write a new file (--out); "
                "refusing to overwrite catalog.sqlite or catalog-v1.sqlite"
            )
    if full and (dest is None or dest.resolve() == _DB.resolve()):
        raise ValueError(
            "full strategy must write a new file (--out); "
            "refusing to overwrite catalog.sqlite"
        )
    foods: dict[str, dict] = {}
    packs = ingest_sources(fndds_only=fndds_only, include_branded=include_branded)
    for path, default_type, branded in packs:
        if not path.is_file():
            if branded:
                print(f"skip missing {path}")
                continue
            raise FileNotFoundError(f"download {path} first (scripts/download_fdc.py)")
        print(f"ingest {path}")
        with _open_zip_dir(path) as zf:
            if branded:
                _ingest_branded(zf, foods)
            else:
                use_full = full and default_type == "survey_fndds_food"
                _ingest_pack(
                    zf,
                    default_type=default_type,
                    foods=foods,
                    overlay=default_type == "survey_fndds_food" and not use_full,
                    full=use_full,
                )
    aliases = assign_staples(foods, fndds_only=fndds_only)
    out = dest or _DB
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    conn = sqlite3.connect(out)
    try:
        conn.execute(
            "CREATE TABLE foods ("
            "food_id TEXT PRIMARY KEY, name TEXT NOT NULL, data_type TEXT, "
            "category TEXT, nutrients TEXT, portions TEXT, allergen_tags TEXT, "
            "aliases TEXT)"
        )
        conn.execute("CREATE TABLE aliases (alias TEXT PRIMARY KEY, food_id TEXT NOT NULL)")
        conn.execute(
            "CREATE VIRTUAL TABLE food_fts USING fts5("
            "food_id, name, aliases, tokenize='unicode61')"
        )
        rows = []
        fts_rows = []
        for fdc_id, entry in foods.items():
            alias_text = " ".join(entry["aliases"])
            rows.append(
                (
                    fdc_id,
                    entry["name"],
                    entry["data_type"],
                    entry["category"],
                    json.dumps(entry["nutrients"]),
                    json.dumps(entry["portions"]),
                    json.dumps(entry["allergen_tags"]),
                    json.dumps(entry["aliases"]),
                )
            )
            fts_rows.append((fdc_id, entry["name"], f"{alias_text} {entry['name']}"))
        conn.executemany(
            "INSERT INTO foods VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        conn.executemany(
            "INSERT INTO aliases(alias, food_id) VALUES (?, ?)",
            list(aliases.items()),
        )
        conn.executemany(
            "INSERT INTO food_fts(food_id, name, aliases) VALUES (?, ?, ?)", fts_rows
        )
        conn.commit()
    finally:
        conn.close()
    print(f"wrote {len(foods)} foods, {len(aliases)} staple aliases -> {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branded", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full FNDDS strategy (seq_num first-wins). Requires --out.",
    )
    parser.add_argument(
        "--fndds-only",
        action="store_true",
        help="Skip SR Legacy. Requires --out (catalog-v2) or --dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List staple swaps and gram deltas; do not write a catalog.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=_ROOT / "reports" / "catalog-v2-dryrun.md",
        help="Dry-run markdown path (default reports/catalog-v2-dryrun.md).",
    )
    args = parser.parse_args(argv)
    dest = args.out
    fndds_only = args.fndds_only or (
        dest is not None and dest.name == "catalog-v2.sqlite"
    )
    full = (
        args.full
        or fndds_only
        or (dest is not None and dest.name == "catalog-v1.sqlite")
    )
    if args.dry_run:
        if not fndds_only:
            parser.error("--dry-run currently supports --fndds-only only")
        plan = plan_fndds_only_rebuild(
            live_catalog=_DB,
            reference_catalog=_DB.parent / "catalog-v1.sqlite",
            split_path=_ROOT / "data" / "splits" / "v0.5-gold.json",
        )
        write_catalog_v2_dryrun(plan, args.report)
        print(f"wrote {args.report}")
        return 0
    if full and dest is None:
        parser.error("full strategy requires --out PATH (refusing to overwrite catalog.sqlite)")
    if fndds_only and dest is None:
        parser.error("fndds-only requires --out PATH or --dry-run")
    build(
        include_branded=args.branded,
        dest=dest,
        full=full,
        fndds_only=fndds_only,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
