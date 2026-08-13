#!/usr/bin/env python3
"""Offline USDA FoodData Central snapshot. Runtime never calls USDA."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "data" / "catalog-snapshot.json"

# Nutrient number → catalog key (FDC / SR).
_NUTRIENT_NUM = {
    208: "kcal",
    203: "protein_g",
    204: "fat_g",
    205: "carb_g",
    291: "fiber_g",
    307: "sodium_mg",
}
_NUTRIENT_ID = {
    1008: "kcal",
    1003: "protein_g",
    1004: "fat_g",
    1005: "carb_g",
    1079: "fiber_g",
    1093: "sodium_mg",
}

# Stable slugs so Generator ids stay valid. query is sent to FDC search.
_STAPLES: list[tuple[str, str, list[str], dict[str, float], list[str]]] = [
    ("peanut_butter", "Peanut butter smooth", ["peanut"], {"tbsp": 16.0, "cup": 258.0}, ["pb", "peanut spread"]),
    ("shrimp", "Shrimp cooked", ["shellfish"], {"piece": 7.0, "cup": 145.0}, ["prawn", "prawns"]),
    ("oats", "Oats rolled dry", [], {"cup": 81.0}, ["oatmeal", "rolled oats"]),
    ("egg", "Egg whole raw", ["egg"], {"piece": 50.0}, ["eggs", "chicken egg"]),
    ("white_rice", "Rice white cooked", [], {"cup": 158.0}, ["rice", "steamed rice"]),
    ("milk_whole", "Milk whole 3.25", ["milk"], {"cup": 244.0, "tbsp": 15.3}, ["milk", "whole milk"]),
    ("chicken_breast", "Chicken breast boneless skinless", [], {"piece": 172.0}, ["chicken", "grilled chicken"]),
    ("almond", "Almonds raw", ["tree_nut"], {"piece": 1.2, "cup": 143.0}, ["almonds"]),
    ("salmon", "Salmon Atlantic", ["fish"], {"piece": 154.0}, ["atlantic salmon"]),
    ("tofu", "Tofu firm", ["soy"], {"cup": 252.0}, ["bean curd"]),
    ("whole_wheat_bread", "Bread whole wheat", ["gluten", "wheat"], {"slice": 32.0}, ["bread", "wholemeal bread"]),
    ("banana", "Banana raw", [], {"piece": 118.0}, ["bananas"]),
    ("broccoli", "Broccoli raw", [], {"cup": 91.0}, ["broccoli florets"]),
    ("greek_yogurt", "Yogurt Greek plain", ["milk"], {"cup": 245.0}, ["yogurt", "greek yoghurt"]),
    ("olive_oil", "Oil olive", [], {"tbsp": 13.5, "tsp": 4.5}, ["olive oil", "evoo"]),
    ("apple", "Apple raw with skin", [], {"piece": 182.0}, ["apples"]),
    ("cheddar", "Cheese cheddar", ["milk"], {"slice": 28.0}, ["cheddar cheese"]),
    ("pasta", "Pasta cooked enriched", ["gluten", "wheat"], {"cup": 140.0}, ["spaghetti", "noodles"]),
    ("beef", "Beef ground 90% lean cooked", [], {"piece": 85.0}, ["ground beef"]),
    ("tuna", "Tuna canned in water", ["fish"], {"can": 165.0}, ["canned tuna"]),
    ("potato", "Potato baked flesh and skin", [], {"piece": 173.0}, ["baked potato"]),
    ("spinach", "Spinach raw", [], {"cup": 30.0}, ["baby spinach"]),
    ("orange", "Orange raw", [], {"piece": 131.0}, ["oranges"]),
    ("avocado", "Avocado raw", [], {"piece": 150.0}, ["avocados"]),
    ("black_beans", "Beans black cooked", [], {"cup": 172.0}, ["black bean"]),
    ("soy_milk", "Soymilk unsweetened", ["soy"], {"cup": 243.0}, ["soy milk"]),
    ("peanut", "Peanuts raw", ["peanut"], {"cup": 146.0}, ["peanuts"]),
]

# Prefer GET /food/{id} (cheaper) when a prior search already resolved the slug.
_FDC_IDS = {
    "peanut_butter": 172458,
    "shrimp": 175180,
    "oats": 172989,
    "egg": 171287,
    "white_rice": 169711,
    "milk_whole": 746782,
    "chicken_breast": 2646170,
    "almond": 2346393,
}


def _api_key() -> str:
    key = os.environ.get("USDA_API_KEY")
    if key:
        return key
    env_path = Path("/home/jzq/Projects/NutriBuddy/.env.local")
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("USDA_API_KEY=") and len(line) > 13:
                return line.split("=", 1)[1].strip()
    return "DEMO_KEY"


def _search(query: str, api_key: str) -> dict | None:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "pageSize": 8,
            "dataType": "Foundation,SR Legacy",
            "api_key": api_key,
        }
    )
    url = f"https://api.nal.usda.gov/fdc/v1/foods/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "nutri-env-ingest/0.1"})
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code != 429 or attempt == 5:
                raise
            time.sleep(8 * (attempt + 1))
    else:
        raise last_err or RuntimeError("search failed")
    foods = payload.get("foods") or []
    if not foods:
        return None
    q_tokens = {t for t in query.lower().split() if len(t) > 2}

    def score(food: dict) -> tuple:
        desc = str(food.get("description") or "").lower()
        penalty = 0
        for bad in ("lunchmeat", "baby food", "infant", "fast food", "restaurant"):
            if bad in desc:
                penalty += 10
        hit = sum(1 for t in q_tokens if t in desc)
        return (penalty, -hit)

    return min(foods, key=score)


def _get_food(fdc_id: int, api_key: str) -> dict | None:
    url = (
        f"https://api.nal.usda.gov/fdc/v1/food/{fdc_id}?"
        + urllib.parse.urlencode({"api_key": api_key})
    )
    req = urllib.request.Request(url, headers={"User-Agent": "nutri-env-ingest/0.1"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 5:
                if exc.code == 404:
                    return None
                raise
            time.sleep(10 * (attempt + 1))
    return None


def _nutrients(food: dict) -> dict[str, float]:
    out = {k: 0.0 for k in ("kcal", "protein_g", "carb_g", "fat_g", "fiber_g", "sodium_mg")}
    for row in food.get("foodNutrients") or []:
        nutrient = row.get("nutrient") if isinstance(row.get("nutrient"), dict) else {}
        nid = row.get("nutrientId") or nutrient.get("id")
        nnum = row.get("nutrientNumber") or nutrient.get("number")
        if isinstance(nnum, str) and nnum.isdigit():
            nnum = int(nnum)
        key = _NUTRIENT_ID.get(nid) or _NUTRIENT_NUM.get(nnum)
        if key is None:
            continue
        raw = row.get("value")
        if raw is None:
            raw = row.get("amount")
        try:
            out[key] = float(raw or 0.0)
        except (TypeError, ValueError):
            continue
    return out


def ingest() -> dict:
    api_key = _api_key()
    foods: dict[str, dict] = {}
    source_rows: list[dict] = []
    if _OUT.is_file():
        prior = json.loads(_OUT.read_text(encoding="utf-8"))
        foods.update(prior.get("foods") or {})
        source_rows.extend(prior.get("meta") or [])
        print(f"resume {len(foods)} foods from {_OUT}")
    for slug, query, allergens, portions, aliases in _STAPLES:
        if slug in foods:
            print(f"skip {slug}")
            continue
        fdc_id = _FDC_IDS.get(slug)
        food = _get_food(fdc_id, api_key) if fdc_id else _search(query, api_key)
        time.sleep(2.5)
        if food is None:
            print(f"miss {slug} ({query})")
            continue
        entry = {
            "name": food.get("description") or slug,
            "nutrients": _nutrients(food),
            "allergen_tags": list(allergens),
            "aliases": aliases,
            "portions": portions,
            "fdc_id": food.get("fdcId"),
            "data_type": food.get("dataType"),
        }
        foods[slug] = entry
        source_rows.append({"slug": slug, "fdc_id": food.get("fdcId"), "query": query})
        print(f"ok   {slug:20} fdc={food.get('fdcId')} {entry['name'][:60]}")
        _write(foods, source_rows)
        time.sleep(1.5)
    print(f"wrote {len(foods)} foods -> {_OUT}")
    return {"version": "usda-fdc-v1", "foods": foods, "meta": source_rows}


def _write(foods: dict, source_rows: list[dict]) -> None:
    snapshot = {
        "version": "usda-fdc-v1",
        "source": "USDA FoodData Central search (Foundation/SR Legacy)",
        "foods": foods,
        "meta": source_rows,
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ingest()
