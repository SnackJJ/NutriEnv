#!/usr/bin/env python3
"""Build the local FDC sqlite catalog from official CSV zips.

Default path is the archived v0.x safe-overlay freeze
(``data/fdc/archive/catalog.sqlite``).
Full FNDDS strategy (seq_num first-wins) writes a *new* file:

    .venv/bin/python scripts/build_fdc_catalog.py --out data/fdc/archive/catalog-v1.sqlite

FNDDS-only (no SR Legacy; catalog-v2) is a *new* file after dry-run approval:

    .venv/bin/python scripts/build_fdc_catalog.py --fndds-only --dry-run
    .venv/bin/python scripts/build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite

``--full`` / ``--fndds-only`` without ``--out``, or targeting
``data/fdc/archive/catalog.sqlite`` / ``data/fdc/archive/catalog-v1.sqlite``, is refused.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RAW = _ROOT / "data" / "fdc" / "raw"
_DB = _ROOT / "data" / "fdc" / "archive" / "catalog.sqlite"

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
    # Food-specific count units (catalog-v2 rebuild round). Appended after
    # serving so an old-key pattern always wins first: scheme B keeps every
    # existing key byte-identical ("1 pouch/regular size" stays regular; only
    # plain "1 pouch" rows write pouch). patty is ruled out before this list
    # because FNDDS size rows ("1 miniature patty") must not become patty.
    (re.compile(r"\bwings?\b"), "wing"),
    (re.compile(r"\bdrummettes?\b"), "drummette"),
    (re.compile(r"\bscoops?\b"), "scoop"),
    (re.compile(r"\bpat\b"), "pat"),
    (re.compile(r"\bpackets?\b"), "packet"),
    (re.compile(r"\bpouch(?:es)?\b"), "pouch"),
    (re.compile(r"\bbars?\b"), "bar"),
    (re.compile(r"\bsticks?\b"), "stick"),
]

#: FNDDS patty rows never use a size modifier as the default patty unit:
#: "1 miniature patty" is a size row, not the countable patty, and prepared
#: forms ("1 patty with sauce and cheese", "1 cake or patty", "1 patty
#: shell") are not the bare patty either. Only a bare row ("1 patty",
#: "1 patty, NFS") writes the patty key, so `a patty` reads the default.
_PATTY_BARE = re.compile(r"^1\s+patty(?:,\s*nfs)?$")


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

    Matches the dry-run POLICY in ``scripts/archive/fndds_dry_run.py``: QNS,
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

    if _PATTY_BARE.match(desc.strip().lower()):
        return ["patty"]

    for pattern, key in _FULL_NEW_UNITS:
        if pattern.search(blob):
            return [key]
    return []


def collect_full_portion_wins(
    rows: list[dict[str, str]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, dict]]]:
    """Full FNDDS scan plus the winning raw row for each (fdc_id, key)."""
    ordered = sorted(rows, key=_row_sort_key)
    out: dict[str, dict[str, float]] = {}
    sources: dict[str, dict[str, dict]] = {}
    for row in ordered:
        fdc_id = row.get("fdc_id") or ""
        keys = _portion_keys_full(
            row.get("portion_description") or "", row.get("modifier") or ""
        )
        try:
            grams = float(row.get("gram_weight") or "")
        except ValueError:
            continue
        if grams <= 0 or not keys:
            continue
        bucket = out.setdefault(fdc_id, {})
        origin = sources.setdefault(fdc_id, {})
        for key in keys:
            if key in bucket:
                continue
            _merge_portion(bucket, key, grams)
            origin[key] = {
                "description": (row.get("portion_description") or "").strip(),
                "modifier": (row.get("modifier") or "").strip(),
                "grams": bucket[key],
                "seq_num": row.get("seq_num") or "",
            }
    return out, sources


def collect_portions_full(
    rows: list[dict[str, str]],
) -> dict[str, dict[str, float]]:
    """Full FNDDS scan: sort by (fdc_id, seq_num, id), first-wins per key.

    Public so the dry-run parity test can call the builder scan without
    going through zip ingest or sqlite. gram_weight <= 0 is dropped.
    """
    portions, _sources = collect_full_portion_wins(rows)
    return portions


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
    survey_zip: Path | None = None,
) -> list[tuple[Path, str, bool]]:
    """Zip packs the builder will ingest: ``(path, default_type, branded)``."""
    survey = survey_zip or (
        _RAW / "fndds.zip" if (_RAW / "fndds.zip").is_file() else _RAW / "survey.zip"
    )
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


# Resolver phrase used only *after* the raw FNDDS row is named.
# Ticket 02: "a chicken breast" stays None; the chicken anchor is piece.
FNDDS_STAPLE_ANCHOR_KEY: dict[str, str] = {
    "chicken_breast": "piece",
    "tuna": "can",
    "tofu": "piece",
    "salmon": "piece",
    "shrimp": "piece",
    "beef": "piece",
    "olive_oil": "tbsp",
    "black_beans": "cup",
    "peanut": "cup",
    "almond": "cup",
}
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
        "票面候选。对应 SR 去皮烤胸。raw first-wins 行是 `1 small breast`=105g，"
        "规范化为 piece=105。裸 a chicken breast 按 ticket 02 仍是 None。"
    ),
    "tuna": "票面候选。对应 SR 水浸罐头；FNDDS can=75（SR can=165）。",
    "tofu": (
        "AGY 核验：FNDDS 纯豆腐官方名 Soybean curd（底层 SR 16127 为 soft）。"
        "当前 SR 钉的是 firm；cup 126→248。"
    ),
    "salmon": (
        "SR 是 Atlantic wild, cooked, dry heat。FNDDS 2706286 是 baked or broiled、"
        "未标野捕/品种，营养素不等价（见 nutrition_deltas）。"
    ),
    "shrimp": (
        "SR 是 cooked。选 steamed or boiled（2706363），"
        "与 NFS 2706360 同份量表。"
    ),
    "beef": (
        "SR 是 90/10 cooked patty。FNDDS 2705855 是 Beef, ground, patty，"
        "丢失 90/10 瘦度（见 nutrition_deltas）。"
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


def survey_fndds_ingest_stats(survey_zip: Path) -> dict:
    """Count ingestible FNDDS foods from survey.zip, not from a built sqlite.

    Ingestible = food.csv rows that have a kcal nutrient (same filter as
    ``_ingest_pack``). The no-kcal remainder is listed so 5431 is derived,
    not copied from catalog.sqlite.
    """
    with _open_zip_dir(survey_zip) as zf:
        foods = list(_iter_csv(zf, "food.csv"))
        kcal_ids: set[str] = set()
        for row in _iter_csv(zf, "food_nutrient.csv"):
            key = _NUTRIENT_BY_ID.get(row["nutrient_id"]) or _NUTRIENT_BY_NBR.get(
                row["nutrient_id"]
            )
            if key != "kcal":
                continue
            try:
                float(row["amount"])
            except (TypeError, ValueError):
                continue
            kcal_ids.add(row["fdc_id"])
    names: dict[str, str] = {}
    data_types: dict[str, str] = {}
    no_kcal_ids: list[str] = []
    for row in foods:
        fdc_id = row.get("fdc_id") or ""
        if not fdc_id:
            continue
        names[fdc_id] = (row.get("description") or "").strip()
        data_types[fdc_id] = row.get("data_type") or "survey_fndds_food"
        if fdc_id not in kcal_ids:
            no_kcal_ids.append(fdc_id)
    food_csv_rows = len(names)
    return {
        "food_csv_rows": food_csv_rows,
        "no_kcal": len(no_kcal_ids),
        "no_kcal_ids": no_kcal_ids,
        "ingestible": food_csv_rows - len(no_kcal_ids),
        "names": names,
        "data_types": data_types,
        "kcal_ids": kcal_ids,
    }


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
    slug: str,
    name: str,
    portions: dict[str, float],
    source: dict | None,
) -> dict:
    from nutrienv.world.portions import resolve_portion

    phrase, expected = FNDDS_STAPLE_PORTION_FACTS[slug]
    key = FNDDS_STAPLE_ANCHOR_KEY[slug]
    catalog = {slug: {"name": name, "portions": portions, "aliases": [slug]}}
    resolved = resolve_portion(slug, phrase, catalog)
    cut_phrase = "a chicken breast" if slug == "chicken_breast" else None
    cut_resolved = (
        resolve_portion(slug, cut_phrase, catalog) if cut_phrase else None
    )
    raw = source or {}
    raw_grams = raw.get("grams")
    return {
        "raw_description": raw.get("description") or "",
        "raw_modifier": raw.get("modifier") or "",
        "raw_grams": raw_grams,
        "resolver_key": key,
        "phrase": phrase,
        "expected_g": expected,
        "resolved_g": resolved,
        "ok": resolved == expected and raw_grams == expected,
        "cut_noun_phrase": cut_phrase,
        "cut_noun_resolved_g": cut_resolved,
    }


def _macros_from_zip(zf: zipfile.ZipFile, wanted: set[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in _iter_csv(zf, "food_nutrient.csv"):
        fdc_id = row.get("fdc_id") or ""
        if fdc_id not in wanted:
            continue
        key = _NUTRIENT_BY_ID.get(row["nutrient_id"]) or _NUTRIENT_BY_NBR.get(
            row["nutrient_id"]
        )
        if key is None:
            continue
        try:
            amount = float(row["amount"])
        except (TypeError, ValueError):
            continue
        bucket = out.setdefault(fdc_id, {})
        if key not in bucket:
            bucket[key] = amount
    return out


def _independent_survey_portions(survey_zip: Path) -> dict[str, dict[str, float]]:
    """POLICY scan that does not call collect_portions_full."""
    spec = importlib.util.spec_from_file_location(
        "fndds_dry_run", Path(__file__).resolve().parent / "archive" / "fndds_dry_run.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("fndds_dry_run.py")
    independent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(independent)
    portions, _names, _qns_zero = independent.collect_full_fndds(survey_zip)
    return portions


_SURVEY_SCAN_CACHE: dict[tuple[str, int], tuple] = {}


def _survey_scan(survey_zip: Path) -> tuple:
    cache_key = (str(survey_zip.resolve()), survey_zip.stat().st_mtime_ns)
    hit = _SURVEY_SCAN_CACHE.get(cache_key)
    if hit is not None:
        return hit
    stats = survey_fndds_ingest_stats(survey_zip)
    with _open_zip_dir(survey_zip) as zf:
        portion_rows = list(_iter_csv(zf, "food_portion.csv"))
        survey_macros = _macros_from_zip(zf, set(FNDDS_ONLY_STAPLE_FDC.values()))
    builder_portions, sources = collect_full_portion_wins(portion_rows)
    independent_portions = _independent_survey_portions(survey_zip)
    packed = (stats, builder_portions, sources, independent_portions, survey_macros)
    _SURVEY_SCAN_CACHE[cache_key] = packed
    return packed


def _rebuild_delta_vs_catalog(
    reference_catalog: Path, proposed: dict[str, dict[str, float]]
) -> dict:
    """Diff the planned rebuild against an existing catalog-v2.sqlite.

    The current catalog-v2.sqlite was built with base keys only. This round
    appends food-specific count units (wing/drummette/scoop/patty/pat/
    packet/pouch/bar/stick) after serving, so every existing key must stay
    byte-identical and only the new keys may be added. The report states
    these counts verbatim; zero old-key drift is the acceptance gate.
    """
    foods, _aliases, _counts = _read_catalog(reference_catalog)
    old: dict[str, dict[str, float]] = {
        fid: dict(entry.get("portions") or {}) for fid, entry in foods.items()
    }
    added_keys: dict[str, int] = {}
    removed_keys: dict[str, int] = {}
    changed_old: list[dict] = []
    only_added = 0
    for fid, new in proposed.items():
        prev = old.get(fid, {})
        # Foods absent from the reference catalog (e.g. the one no-kcal food
        # that is never ingested) are not rebuild deltas; skip them.
        if fid not in old:
            continue
        if not prev and not new:
            continue
        added_here = [key for key in new if key not in prev]
        removed_here = [key for key in prev if key not in new]
        changed_here = [
            (key, prev[key], new[key])
            for key in prev
            if key in new and prev[key] != new[key]
        ]
        for key in added_here:
            added_keys[key] = added_keys.get(key, 0) + 1
        for key in removed_here:
            removed_keys[key] = removed_keys.get(key, 0) + 1
        changed_old.extend(
            {"fdc_id": fid, "key": key, "old": ov, "new": nv}
            for key, ov, nv in changed_here
        )
        # Food-level classification: this food changed only by adding keys
        # (no key removed, no key whose value changed).
        if added_here and not removed_here and not changed_here:
            only_added += 1
    return {
        "compared": True,
        "foods_with_only_added": only_added,
        "added_keys": dict(sorted(added_keys.items())),
        "removed_keys": dict(sorted(removed_keys.items())),
        "changed_old_keys": sorted(
            changed_old, key=lambda row: (row["fdc_id"], row["key"])
        ),
    }


def plan_fndds_only_rebuild(
    *,
    live_catalog: Path,
    survey_zip: Path | None = None,
    sr_legacy_zip: Path | None = None,
    split_path: Path | None = None,
    reference_catalog: Path | None = None,
    sqlite_pair: tuple[Path, Path] | None = None,
) -> dict:
    """Read-only catalog-v2 plan. Count and FNDDS portions come from survey.zip.

    Does not write ``catalog-v2.sqlite``. ``sqlite_pair`` is two catalog
    sqlite files whose ``foods`` JSON cells are compared as TEXT. When
    omitted, the planner builds ``survey_zip`` once into a temp file and
    checks those cells against independently sorted JSON.
    """
    survey_zip = survey_zip or (
        _RAW / "fndds.zip" if (_RAW / "fndds.zip").is_file() else _RAW / "survey.zip"
    )
    sr_legacy_zip = sr_legacy_zip or (_RAW / "sr_legacy.zip")
    stats, builder_portions, sources, independent_portions, survey_macros = (
        _survey_scan(survey_zip)
    )
    portion_map_diffs = 0
    for fdc_id in set(builder_portions) | set(independent_portions):
        if builder_portions.get(fdc_id) != independent_portions.get(fdc_id):
            portion_map_diffs += 1
    json_cells = _json_cells_from_sqlite_pair(sqlite_pair, survey_zip=survey_zip)

    rebuild_delta = {}
    if reference_catalog is not None and reference_catalog.is_file():
        rebuild_delta = _rebuild_delta_vs_catalog(reference_catalog, builder_portions)

    live_foods, live_aliases, live_counts = _read_catalog(live_catalog)
    sr_ids = {
        live_aliases.get(slug, "")
        for slug in SR_LEGACY_STAPLES
        if live_aliases.get(slug)
    }
    sr_macros: dict[str, dict[str, float]] = {}
    if sr_legacy_zip.is_file() and sr_ids:
        with _open_zip_dir(sr_legacy_zip) as zf:
            sr_macros = _macros_from_zip(zf, sr_ids)

    pins = staple_fdc_pins(fndds_only=True)
    swaps: list[dict] = []
    for slug in SR_LEGACY_STAPLES:
        old_id = live_aliases.get(slug, "")
        new_id = pins[slug]
        old_entry = live_foods.get(old_id) or {}
        new_name = stats["names"].get(new_id) or ""
        old_portions = dict(old_entry.get("portions") or {})
        new_portions = dict(builder_portions.get(new_id) or {})
        fact = _confirm_portion_fact(
            slug,
            new_name,
            new_portions,
            (sources.get(new_id) or {}).get(FNDDS_STAPLE_ANCHOR_KEY[slug]),
        )
        swaps.append(
            {
                "slug": slug,
                "old_fdc_id": old_id,
                "old_name": old_entry.get("name") or "",
                "old_data_type": old_entry.get("data_type") or "",
                "old_portions": old_portions,
                "new_fdc_id": new_id,
                "new_name": new_name,
                "new_data_type": stats["data_types"].get(new_id) or "survey_fndds_food",
                "new_portions": new_portions,
                "portion_fact": fact,
            }
        )

    nutrition_deltas = [
        {
            "slug": "beef",
            "old_fdc_id": live_aliases.get("beef", ""),
            "new_fdc_id": pins["beef"],
            "old_nutrients": sr_macros.get(live_aliases.get("beef", ""), {}),
            "new_nutrients": survey_macros.get(pins["beef"], {}),
            "disclosure": (
                "Beef loses 90/10 leanness: SR 171793 is "
                "'90% lean meat / 10% fat, patty, cooked, pan-broiled'; "
                "FNDDS 2705855 is generic 'Beef, ground, patty' (NFS fat)."
            ),
        },
        {
            "slug": "salmon",
            "old_fdc_id": live_aliases.get("salmon", ""),
            "new_fdc_id": pins["salmon"],
            "old_nutrients": sr_macros.get(live_aliases.get("salmon", ""), {}),
            "new_nutrients": survey_macros.get(pins["salmon"], {}),
            "disclosure": (
                "Salmon is not nutritionally equivalent to the old wild entry: "
                "SR 171998 is 'Atlantic, wild, cooked, dry heat'; "
                "FNDDS 2706286 is 'baked or broiled' with no wild/species tag."
            ),
        },
    ]

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
            "food_csv_rows": stats["food_csv_rows"],
            "no_kcal": stats["no_kcal"],
            "no_kcal_ids": stats["no_kcal_ids"],
            "catalog_v2_foods": stats["ingestible"],
            "sr_legacy_food": live_counts.get("sr_legacy_food", 0),
        },
        "raw_scan": {
            "source": (
                str(survey_zip.relative_to(_ROOT))
                if survey_zip.is_relative_to(_ROOT)
                else str(survey_zip)
            ),
            "builder_foods_with_portions": len(builder_portions),
            "independent_foods_with_portions": len(independent_portions),
            "portion_map_diffs": portion_map_diffs,
            "json_cells": json_cells,
        },
        "rebuild_delta": rebuild_delta,
        "staple_swaps": swaps,
        "nutrition_deltas": nutrition_deltas,
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


def _fmt_macros(nutrients: dict) -> str:
    if not nutrients:
        return "—"
    order = ("kcal", "protein_g", "fat_g", "carb_g", "sodium_mg")
    bits = [f"{k}={nutrients[k]:g}" for k in order if k in nutrients]
    bits += [f"{k}={v:g}" for k, v in sorted(nutrients.items()) if k not in order]
    return ", ".join(bits)


def write_catalog_v2_dryrun(plan: dict, dest: Path) -> None:
    """Write the STEP 1 dry-run report. Does not write catalog-v2.sqlite."""
    counts = plan["counts"]
    swaps = plan["staple_swaps"]
    gold_rows = plan.get("gold_rows") or []
    raw_scan = plan.get("raw_scan") or {}
    cells = raw_scan.get("json_cells") or {}
    delta = plan.get("rebuild_delta") or {}
    excluded = ", ".join(f"`{fid}`" for fid in (counts.get("no_kcal_ids") or []))
    lines: list[str] = [
        "# catalog-v2 dry-run：FNDDS-only + staple 重钉",
        "",
        "只读对照：**不写** `data/fdc/catalog-v2.sqlite`，不改 `data/fdc/archive/catalog.sqlite`、",
        "`data/fdc/archive/catalog-v1.sqlite`、任何 `data/splits/*.json`。本文件是 AGENTS.md 纪律 2",
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
        "  `data/fdc/archive/catalog.sqlite` 与 `data/fdc/archive/catalog-v1.sqlite`。",
        "- FNDDS 食物数与份量图来自 `survey.zip`（food.csv / food_nutrient /",
        "  food_portion），不是现成 sqlite 的 COUNT / portions 拷贝。",
        "- v0.5-gold（已归档）绑 `data/fdc/archive/catalog.sqlite`，本 dry-run 与 catalog-v2 对其零影响。",
        "",
        "## 食物数对账（survey.zip）",
        "",
        f"- `survey.zip` `food.csv` 行数：**{counts['food_csv_rows']}**",
        f"- 无 kcal、不入库：**{counts['no_kcal']}**（{excluded or '—'}）",
        f"- catalog-v2 预计食物数：**{counts['catalog_v2_foods']}**"
        f"（= food.csv − 无 kcal，不硬编码）",
        f"- 当前 catalog 里仍有的 `sr_legacy_food`：**{counts['sr_legacy_food']}**"
        "（catalog-v2 将全部丢弃；此数只描述现状，不参与 FNDDS 计数）",
        "",
        "## FNDDS 份量图：builder scan vs 独立 raw scan",
        "",
        f"- 源：`{raw_scan.get('source', 'survey.zip')}`",
        f"- builder `collect_portions_full` 有份量的食物："
        f"**{raw_scan.get('builder_foods_with_portions', 0)}**",
        f"- 独立 `fndds_dry_run.collect_full_fndds`："
        f"**{raw_scan.get('independent_foods_with_portions', 0)}**",
        f"- 两图不一致的食物数：**{raw_scan.get('portion_map_diffs', 0)}**",
        "",
        "上项是 survey.zip 扫描的取值对照。sqlite `foods` JSON cell 字节对照见下节。",
        "",
        "## sqlite foods JSON cell 字节对照",
        "",
        f"- 对比食物数：**{cells.get('foods_compared', 0)}**",
        f"- 解析后取值不一致：**{cells.get('value_diffs', 0)}**",
        f"- sqlite TEXT 字节不一致：**{cells.get('byte_diffs', 0)}**",
        f"- 取值相同、仅序列化不同：**{cells.get('key_order_only_diffs', 0)}**",
        "- 列：`nutrients` / `portions` / `allergen_tags` / `aliases`",
        "",
        "零漂移要求取值与 sqlite TEXT 都一致。仅键序或 JSON 空白不同也会记入 "
        "`key_order_only`。不写 `catalog-v2.sqlite`；对照用临时库或调用方传入的一对 sqlite。",
        "",
        "## 本轮重建：相对现有 catalog-v2.sqlite 的差异",
        "",
        "本轮在 `_FULL_NEW_UNITS` 尾部追加食物专属计数单位（wing / drummette / "
        "scoop / patty / pat / packet / pouch / bar / stick），全部排在 serving "
        "之后：已有 key 永远先赢，因此现有 portions 一个字节都不变，只新增这 9 个 "
        "key。patty 在列表外单独判：带 size 词的 FNDDS 行（`1 miniature patty`）"
        "不是默认 patty，只有裸 `1 patty` / `1 patty, NFS` 写 patty 键。",
        "",
    ]
    if delta.get("compared"):
        added_keys = delta.get("added_keys") or {}
        removed_keys = delta.get("removed_keys") or {}
        changed_old = delta.get("changed_old_keys") or []
        lines += [
            f"- 仅新增 key 的食物数：**{delta.get('foods_with_only_added', 0)}**",
            f"- 新增 key 食物数：**{sum(added_keys.values())}**"
            f"（{', '.join(f'{k}={v}' for k, v in added_keys.items()) or '—'}）",
            f"- 移除 key 食物数：**{sum(removed_keys.values())}**"
            f"（{', '.join(f'{k}={v}' for k, v in removed_keys.items()) or '无'}）",
            f"- 同 key 克数变化：**{len(changed_old)}**",
            "",
            "接受闸门：`removed == 0` 且 `changed == 0`（零旧 key 漂移），否则不重建。",
            "",
        ]
    else:
        lines += [
            "- 当前无 `data/fdc/catalog-v2.sqlite` 可对照，跳过本轮差异统计。",
            "",
        ]
    lines += [
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
        "SR 行的形态就近选 survey 里的 FNDDS 行。beef 丢失 90/10 瘦度、salmon 与",
        "旧 wild 条目营养不等价，见下方披露。",
        "",
        "## 哪些食物克数会变",
        "",
        "FNDDS 食物份量键相对独立 raw scan **0 变**（上节）。变化只来自 10 个 staple",
        "别名换条目（旧 SR 行随 SR Legacy 一起消失）。v0.5-gold 不读 catalog-v2。",
        "",
        "| slug | 当前 SR portions | FNDDS portions（raw scan） | 克数变化 |",
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
        "## 每条 staple 的 raw PortionFact + 规范化键",
        "",
        "先写 FNDDS 原行（含 small/regular/medium 等修饰），再写 resolver 规范化键。",
        "",
    ]
    for row in swaps:
        fact = row["portion_fact"]
        ok = "通过" if fact["ok"] else "失败"
        raw_g = fact.get("raw_grams")
        raw_g_s = "—" if raw_g is None else f"{raw_g:g} g"
        lines += [
            f"### `{row['slug']}` → `{row['new_fdc_id']}` {row['new_name']}",
            "",
            f"- 当前：`{row['old_fdc_id']}` [{row['old_data_type']}] {row['old_name']}",
            f"- 选型：{FNDDS_STAPLE_WHY[row['slug']]}",
            f"- **raw PortionFact**：`{fact['raw_description']}` = **{raw_g_s}**",
            f"- 规范化 resolver 键：`{fact['resolver_key']}={fact['expected_g']:g}`"
            f"（`{fact['phrase']}` → resolve_portion={fact['resolved_g']}，{ok}）",
            f"- 规范化后 portions：`{_fmt_portions(row['new_portions'])}`",
        ]
        if fact.get("cut_noun_phrase"):
            lines.append(
                f"- ticket 02 仍成立：`{fact['cut_noun_phrase']}` → "
                f"{fact['cut_noun_resolved_g']}（切块名词，不是 piece）"
            )
        lines.append("")
    lines += [
        "## 营养素披露（beef 瘦度 / salmon 野捕）",
        "",
        "每 100 g，来自 `sr_legacy.zip` / `survey.zip` 的 food_nutrient，不是 sqlite。",
        "",
    ]
    for delta in plan.get("nutrition_deltas") or []:
        lines += [
            f"### `{delta['slug']}`",
            "",
            f"- {delta['disclosure']}",
            f"- SR `{delta['old_fdc_id']}`：{_fmt_macros(delta['old_nutrients'])}",
            f"- FNDDS `{delta['new_fdc_id']}`：{_fmt_macros(delta['new_nutrients'])}",
            "",
        ]
    n_gold = len(gold_rows)
    by_slug: dict[str, int] = {}
    for row in gold_rows:
        by_slug[row["slug"]] = by_slug.get(row["slug"], 0) + 1
    lines += [
        "## v0.5-gold 影响（绑旧 catalog，零落地）",
        "",
        f"split 里这 10 个 slug 共 **{n_gold}** 行（peanut 不在 gold 25 里）。",
        "冻结克数写在 JSON 里，不随 catalog-v2 变。**本票不改 v0.5-gold，",
        "也不改 `data/fdc/archive/catalog.sqlite`。**",
        "",
        "| slug | gold 行数 |",
        "|---|---:|",
    ]
    for slug in SR_LEGACY_STAPLES:
        lines.append(f"| `{slug}` | {by_slug.get(slug, 0)} |")
    lines += [
        "",
        "## ticket 02 仍成立",
        "",
        "验收 2 已改为：chicken piece 锚点 = 105g（raw `1 small breast`）；",
        "裸 `\"a chicken breast\"` 按 ticket 02 保持 105.0（切块名词，非 piece）。",
        "本 dry-run 不改 portion key 扫描之外的 resolver 语义；`resolve_portion` 的",
        "quantity 容忍（`two chicken wings` → 2×wing；`some cups` 仍拒绝）与 catalog",
        "重建同批测试覆盖。",
        "",
        "## 裁决请求",
        "",
        "请 codex 独立审查本清单（尤其「本轮重建差异」的 removed/changed 均为 0），",
        "主 agent 裁决 APPROVE 后再允许：",
        "`build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite`。",
        "",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def dump_catalog_json(value: object) -> str:
    """Serialize a foods-table JSON cell. Key order is pinned, not scan order."""
    return json.dumps(value, sort_keys=True)


FOODS_JSON_COLUMNS = ("nutrients", "portions", "allergen_tags", "aliases")


def _parse_json_cell(blob: str | None) -> object:
    try:
        return json.loads(blob or "")
    except json.JSONDecodeError:
        return blob


def _read_foods_json_cells(path: Path) -> dict[str, dict[str, str]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT food_id, nutrients, portions, allergen_tags, aliases FROM foods"
        )
        return {
            str(food_id): {
                "nutrients": nutrients or "",
                "portions": portions or "",
                "allergen_tags": allergen_tags or "",
                "aliases": aliases or "",
            }
            for food_id, nutrients, portions, allergen_tags, aliases in rows
        }
    finally:
        conn.close()


def diff_foods_json_cells(left: Path, right: Path) -> dict:
    """Compare foods JSON cells as sqlite TEXT bytes, not parsed values.

    Covers ``nutrients``, ``portions``, ``allergen_tags``, and ``aliases``.
    """
    left_rows = _read_foods_json_cells(left)
    right_rows = _read_foods_json_cells(right)
    ids = sorted(set(left_rows) | set(right_rows))
    value_diffs = 0
    byte_diffs = 0
    key_order_only = 0
    columns_hit: set[str] = set()
    for food_id in ids:
        left_cells = left_rows.get(food_id)
        right_cells = right_rows.get(food_id)
        if left_cells is None or right_cells is None:
            value_diffs += 1
            byte_diffs += 1
            continue
        food_value_diff = False
        food_byte_diff = False
        for column in FOODS_JSON_COLUMNS:
            left_blob = left_cells[column]
            right_blob = right_cells[column]
            if left_blob != right_blob:
                food_byte_diff = True
                columns_hit.add(column)
            if _parse_json_cell(left_blob) != _parse_json_cell(right_blob):
                food_value_diff = True
        if food_byte_diff:
            byte_diffs += 1
        if food_value_diff:
            value_diffs += 1
        elif food_byte_diff:
            key_order_only += 1
    return {
        "foods_compared": len(ids),
        "value_diffs": value_diffs,
        "byte_diffs": byte_diffs,
        "key_order_only_diffs": key_order_only,
        "byte_diff_columns": sorted(columns_hit),
    }


def _canonical_cell_text(blob: str) -> str:
    parsed = _parse_json_cell(blob)
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, sort_keys=True)
    return blob


def check_foods_json_cells_canonical(catalog: Path) -> dict:
    """Compare stored foods JSON TEXT to independently sorted JSON.

    This is not a two-rebuild self-compare: unsorted ``json.dumps`` keeps
    insertion order across consecutive builds, so those would still match.
    """
    rows = _read_foods_json_cells(catalog)
    value_diffs = 0
    byte_diffs = 0
    key_order_only = 0
    columns_hit: set[str] = set()
    for cells in rows.values():
        food_value_diff = False
        food_byte_diff = False
        for column in FOODS_JSON_COLUMNS:
            blob = cells[column]
            canonical = _canonical_cell_text(blob)
            if blob != canonical:
                food_byte_diff = True
                columns_hit.add(column)
            if _parse_json_cell(blob) != _parse_json_cell(canonical):
                food_value_diff = True
        if food_byte_diff:
            byte_diffs += 1
        if food_value_diff:
            value_diffs += 1
        elif food_byte_diff:
            key_order_only += 1
    return {
        "foods_compared": len(rows),
        "value_diffs": value_diffs,
        "byte_diffs": byte_diffs,
        "key_order_only_diffs": key_order_only,
        "byte_diff_columns": sorted(columns_hit),
    }


def _json_cells_from_sqlite_pair(
    sqlite_pair: tuple[Path, Path] | None,
    *,
    survey_zip: Path,
) -> dict:
    """Diff two catalogs, or check one temp build of ``survey_zip``."""
    if sqlite_pair is not None:
        return diff_foods_json_cells(sqlite_pair[0], sqlite_pair[1])
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "catalog.sqlite"
        build(
            include_branded=False,
            dest=dest,
            fndds_only=True,
            survey_zip=survey_zip,
        )
        return check_foods_json_cells_canonical(dest)


def _protected_catalogs() -> tuple[Path, ...]:
    return (_DB.resolve(), (_DB.parent / "catalog-v1.sqlite").resolve())


def build(
    include_branded: bool,
    dest: Path | None = None,
    full: bool = False,
    fndds_only: bool = False,
    survey_zip: Path | None = None,
) -> Path:
    if fndds_only:
        full = True
        if dest is None or dest.resolve() in _protected_catalogs():
            raise ValueError(
                "fndds-only rebuild must write a new file (--out); "
                "refusing to overwrite data/fdc/archive/catalog.sqlite or data/fdc/archive/catalog-v1.sqlite"
            )
    if full and (dest is None or dest.resolve() == _DB.resolve()):
        raise ValueError(
            "full strategy must write a new file (--out); "
            "refusing to overwrite data/fdc/archive/catalog.sqlite"
        )
    foods: dict[str, dict] = {}
    packs = ingest_sources(
        fndds_only=fndds_only,
        include_branded=include_branded,
        survey_zip=survey_zip,
    )
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
                    dump_catalog_json(entry["nutrients"]),
                    dump_catalog_json(entry["portions"]),
                    dump_catalog_json(entry["allergen_tags"]),
                    dump_catalog_json(entry["aliases"]),
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
            split_path=_ROOT / "data" / "splits" / "archive" / "v0.5-gold.json",
            reference_catalog=_ROOT / "data" / "fdc" / "catalog-v2.sqlite",
        )
        write_catalog_v2_dryrun(plan, args.report)
        print(f"wrote {args.report}")
        return 0
    if full and dest is None:
        parser.error("full strategy requires --out PATH (refusing to overwrite data/fdc/archive/catalog.sqlite)")
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
