#!/usr/bin/env python3
"""Download official USDA FoodData Central CSV zips. Runtime never uses these."""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RAW = _ROOT / "data" / "fdc" / "raw"

_URLS = {
    "sr_legacy": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip",
    "fndds": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_survey_food_csv_2024-10-31.zip",
    "branded": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_branded_food_csv_2024-10-31.zip",
}


def download(names: list[str]) -> None:
    _RAW.mkdir(parents=True, exist_ok=True)
    for name in names:
        url = _URLS[name]
        dest = _RAW / f"{name}.zip"
        print(f"GET {url} -> {dest}")
        urllib.request.urlretrieve(url, dest)
        print(f"  {dest.stat().st_size} bytes")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sets",
        nargs="+",
        choices=sorted(_URLS),
        default=["sr_legacy", "fndds"],
    )
    args = parser.parse_args()
    download(args.sets)


if __name__ == "__main__":
    main()
