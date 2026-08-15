#!/usr/bin/env python3
"""Build the offline catalog from NutriMind's already-downloaded USDA dump.

Does not call the USDA API. Runtime still never opens this database; Env
reads only ``data/catalog-snapshot.json``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SRC = Path("/home/jzq/Projects/NutriMind/data/usda.db")
_DB_OUT = _ROOT / "data" / "usda.db"
_SNAP_OUT = _ROOT / "data" / "catalog-snapshot.json"

# slug -> (fdc_id, allergen_tags, portions, aliases)
# Prefer SR Legacy rows with complete energy. Foundation ids 2646170 / 2346393
# exist in the source db but store energy as 0.
_STAPLES: dict[str, tuple[int, list[str], dict[str, float], list[str]]] = {
    "peanut_butter": (172458, ["peanut"], {"tbsp": 16.0, "cup": 258.0}, ["pb", "peanut spread"]),
    "shrimp": (175180, ["shellfish"], {"piece": 7.0, "cup": 145.0}, ["prawn", "prawns"]),
    "oats": (172989, [], {"cup": 81.0}, ["oatmeal", "rolled oats"]),
    "egg": (171287, ["egg"], {"piece": 50.0}, ["eggs", "chicken egg"]),
    "white_rice": (169711, [], {"cup": 158.0}, ["rice", "steamed rice"]),
    "milk_whole": (746782, ["milk"], {"cup": 244.0, "tbsp": 15.3}, ["milk", "whole milk"]),
    "chicken_breast": (
        171477,
        [],
        {"piece": 172.0},
        ["chicken", "grilled chicken"],
    ),
    "almond": (170567, ["tree_nut"], {"piece": 1.2, "cup": 143.0}, ["almonds"]),
    "salmon": (175168, ["fish"], {"piece": 154.0}, ["atlantic salmon"]),
    "tofu": (172448, ["soy"], {"cup": 252.0}, ["bean curd"]),
    "whole_wheat_bread": (
        172688,
        ["gluten", "wheat"],
        {"slice": 32.0},
        ["bread", "wholemeal bread"],
    ),
    "banana": (173944, [], {"piece": 118.0}, ["bananas"]),
    "broccoli": (170379, [], {"cup": 91.0}, ["broccoli florets"]),
    "greek_yogurt": (
        330137,
        ["milk"],
        {"cup": 245.0, "tbsp": 15.3},
        ["yogurt", "greek yoghurt"],
    ),
    "olive_oil": (171413, [], {"tbsp": 13.5, "tsp": 4.5}, ["olive oil", "evoo"]),
    "apple": (171688, [], {"piece": 182.0}, ["apples"]),
    "cheddar": (328637, ["milk"], {"slice": 28.0}, ["cheddar cheese"]),
    "pasta": (169737, ["gluten", "wheat"], {"cup": 140.0}, ["spaghetti", "noodles"]),
    "beef": (174031, [], {"piece": 85.0}, ["ground beef"]),
    "tuna": (334194, ["fish"], {"can": 165.0}, ["canned tuna"]),
    "potato": (170093, [], {"piece": 173.0}, ["baked potato"]),
    "spinach": (168462, [], {"cup": 30.0}, ["baby spinach"]),
    "orange": (169097, [], {"piece": 131.0}, ["oranges"]),
    "avocado": (171705, [], {"piece": 150.0}, ["avocados"]),
    "black_beans": (173735, [], {"cup": 172.0}, ["black bean"]),
    "soy_milk": (172446, ["soy"], {"cup": 243.0}, ["soy milk"]),
    "peanut": (172430, ["peanut"], {"cup": 146.0}, ["peanuts"]),
}


def _copy_foods_table(src: Path, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    incoming = sqlite3.connect(src)
    outgoing = sqlite3.connect(dest)
    try:
        incoming.execute("SELECT 1 FROM foods LIMIT 1")
        outgoing.execute("ATTACH DATABASE ? AS src", (str(src),))
        outgoing.execute("CREATE TABLE foods AS SELECT * FROM src.foods")
        outgoing.execute("CREATE UNIQUE INDEX idx_foods_fdc_id ON foods(fdc_id)")
        outgoing.execute("CREATE INDEX idx_foods_description ON foods(description)")
        outgoing.commit()
        count = outgoing.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
    finally:
        incoming.close()
        outgoing.close()
    return int(count)


def _nutrients(row: sqlite3.Row) -> dict[str, float]:
    return {
        "kcal": float(row["energy_kcal"] or 0.0),
        "protein_g": float(row["protein_g"] or 0.0),
        "carb_g": float(row["carbohydrate_g"] or 0.0),
        "fat_g": float(row["total_fat_g"] or 0.0),
        "fiber_g": float(row["fiber_g"] or 0.0),
        "sodium_mg": float(row["sodium_mg"] or 0.0),
    }


def build(src: Path = _DEFAULT_SRC) -> dict:
    if not src.is_file():
        raise FileNotFoundError(f"NutriMind USDA db not found: {src}")
    copied = _copy_foods_table(src, _DB_OUT)
    conn = sqlite3.connect(_DB_OUT)
    conn.row_factory = sqlite3.Row
    foods: dict[str, dict] = {}
    meta: list[dict] = []
    try:
        for slug, (fdc_id, allergens, portions, aliases) in _STAPLES.items():
            row = conn.execute(
                "SELECT * FROM foods WHERE fdc_id = ?", (fdc_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"fdc_id {fdc_id} for {slug} missing in { _DB_OUT}")
            nutrients = _nutrients(row)
            if nutrients["kcal"] <= 0:
                raise ValueError(f"{slug} fdc={fdc_id} has no energy; pick another row")
            foods[slug] = {
                "name": row["description"],
                "nutrients": nutrients,
                "allergen_tags": list(allergens),
                "aliases": list(aliases),
                "portions": dict(portions),
                "fdc_id": int(row["fdc_id"]),
                "data_type": "SR Legacy" if int(row["fdc_id"]) < 1_000_000 else "Foundation",
                "category": row["category"],
            }
            meta.append({"slug": slug, "fdc_id": int(row["fdc_id"])})
    finally:
        conn.close()
    snapshot = {
        "version": "usda-local-v1",
        "source": (
            "NutriMind data/usda.db (SR Legacy + Foundation, already downloaded). "
            "Allergen tags and household portions are local overlays, not USDA fields."
        ),
        "foods": foods,
        "meta": meta,
        "db_foods": copied,
    }
    _SNAP_OUT.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(f"copied {copied} foods -> {_DB_OUT}")
    print(f"wrote {len(foods)} staples -> {_SNAP_OUT}")
    return snapshot


if __name__ == "__main__":
    build()
