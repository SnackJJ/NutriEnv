"""The split freezer rejects Oracle grams without a deterministic anchor."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from nutrienv.world.catalog_store import load_catalog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import materialize_split  # noqa: E402


def _payload(grams: float) -> dict:
    return {
        "version": "test-gold",
        "items": [
            {
                "id": "test-log-milk",
                "family": "log",
                "persona": "everyday",
                "situations": ["fuzzy_portion"],
                "query": "I drank half a cup of milk.",
                "s0": {
                    "profile": {"user_id": "test-user"},
                    "ledger": [],
                },
                "oracle": {
                    "ledger_tail": [
                        {
                            "food_id": "milk_whole",
                            "grams": grams,
                            "eaten_at": "today-breakfast",
                        }
                    ]
                },
            }
        ],
    }


def test_freeze_split_accepts_portion_anchored_oracle(tmp_path: Path) -> None:
    target = tmp_path / "valid.json"
    payload = _payload(122.0)

    materialize_split.freeze_split(payload, target, load_catalog())

    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_freeze_split_rejects_unanchored_oracle_before_writing(
    tmp_path: Path,
) -> None:
    target = tmp_path / "invalid.json"
    payload = deepcopy(_payload(122.0))
    payload["items"][0]["oracle"]["ledger_tail"][0]["grams"] = 123.0

    with pytest.raises(ValueError, match=r"test-log-milk.*portion table"):
        materialize_split.freeze_split(payload, target, load_catalog())

    assert not target.exists()


def test_freeze_split_accepts_existing_v02_through_v05_items(
    tmp_path: Path,
) -> None:
    source = ROOT / "data" / "splits" / "archive" / "v0.5-gold.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    target = tmp_path / "v0.5-gold.json"

    # v0.5 items were authored against the frozen legacy catalog, not the
    # active catalog-v2 snapshot.
    legacy_catalog = ROOT / "data" / "fdc" / "archive" / "catalog.sqlite"
    materialize_split.freeze_split(payload, target, load_catalog(legacy_catalog))

    assert target.is_file()
