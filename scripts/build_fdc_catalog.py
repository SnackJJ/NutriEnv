#!/usr/bin/env python3
"""Build the local FDC sqlite catalog from official CSV zips.

Runtime reads only ``data/fdc/catalog.sqlite``. This script is the freeze step.
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
) -> None:
    nutrients = _collect_nutrients(zf)
    portions = _collect_portions(zf)
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


def _assign_staples(foods: dict[str, dict]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    names = {fid: entry["name"].lower() for fid, entry in foods.items()}
    for slug, needles in _STAPLES.items():
        chosen = None
        pinned = _STAPLE_FDC.get(slug)
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


def build(include_branded: bool, dest: Path | None = None) -> Path:
    foods: dict[str, dict] = {}
    packs = [
        (_RAW / "fndds.zip" if (_RAW / "fndds.zip").is_file() else _RAW / "survey.zip", "survey_fndds_food", False),
        (_RAW / "sr_legacy.zip", "sr_legacy_food", False),
    ]
    if include_branded:
        packs.append((_RAW / "branded.zip", "branded_food", True))
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
                _ingest_pack(zf, default_type=default_type, foods=foods)
    aliases = _assign_staples(foods)
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branded", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    build(include_branded=args.branded, dest=args.out)


if __name__ == "__main__":
    main()
