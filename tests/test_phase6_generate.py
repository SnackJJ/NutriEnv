"""Phase-6 orchestration: 20-pool plan, QNS cross-check, quantifier stats."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase6_generate as phase6  # noqa: E402


def test_plan_slots_is_14_log_and_6_evaluate() -> None:
    slots = phase6.plan_slots(seed=20260818)
    assert len(slots) == 20
    assert sum(slot.family == "log" for slot in slots) == 14
    assert sum(slot.family == "evaluate" for slot in slots) == 6


def test_plan_slots_mixes_everyday_and_gym() -> None:
    slots = phase6.plan_slots(seed=20260818)
    personas = {slot.persona for slot in slots}
    assert personas == {"everyday", "gym"}
    assert sum(slot.persona == "everyday" for slot in slots) == 10
    assert sum(slot.persona == "gym" for slot in slots) == 10


def test_plan_slots_assigns_model_quotas_that_sum_to_20() -> None:
    slots = phase6.plan_slots(seed=20260818)
    counts: dict[str, int] = {}
    for slot in slots:
        counts[slot.model] = counts.get(slot.model, 0) + 1
    assert sum(counts.values()) == 20
    assert "qwen3.8-max" in counts
    assert "deepseek-v4-flash-0731" in counts
    assert all(count > 0 for count in counts.values())


def test_plan_slots_is_reproducible_and_seed_sensitive() -> None:
    a = phase6.plan_slots(seed=20260818)
    b = phase6.plan_slots(seed=20260818)
    c = phase6.plan_slots(seed=99)
    assert a == b
    assert [slot.model for slot in a] != [slot.model for slot in c]


def test_plan_slots_marks_one_qns_isolation_reserve() -> None:
    slots = phase6.plan_slots(seed=20260818)
    reserved = [slot for slot in slots if slot.reserved == "qns_isolation"]
    assert len(reserved) == 1
    assert reserved[0].family in {"log", "evaluate"}


def test_qns_cross_check_records_first_wins_vs_qns() -> None:
    catalog = {
        "chicken_breast": {
            "name": "Chicken breast",
            "portions": {"piece": 105.0, "qns": 120.0, "cup": 135.0},
        },
        "tuna": {"name": "Tuna", "portions": {"can": 75.0, "qns": 85.0, "cup": 135.0}},
        "beef": {"name": "Beef", "portions": {"piece": 65.0, "qns": 85.0, "cup": 125.0}},
    }
    rows = phase6.qns_cross_check(catalog)
    by_slug = {row["slug"]: row for row in rows}
    assert by_slug["chicken_breast"]["first_wins_key"] == "piece"
    assert by_slug["chicken_breast"]["first_wins_g"] == 105.0
    assert by_slug["chicken_breast"]["qns_g"] == 120.0
    assert by_slug["tuna"]["first_wins_key"] == "can"
    assert by_slug["tuna"]["first_wins_g"] == 75.0
    assert by_slug["tuna"]["qns_g"] == 85.0
    assert by_slug["beef"]["first_wins_key"] == "piece"
    assert by_slug["beef"]["first_wins_g"] == 65.0
    assert by_slug["beef"]["qns_g"] == 85.0


def test_quantifier_distribution_counts_spoken_keys() -> None:
    records = [
        {"items": [{"portion_key": "cup"}, {"portion_key": "piece"}]},
        {"items": [{"portion_key": "qns"}, {"portion_key": "cup"}]},
        {"items": [{"portion_key": "tbsp"}]},
    ]
    dist = phase6.quantifier_distribution(records)
    assert dist == {"cup": 2, "piece": 1, "qns": 1, "tbsp": 1}


def test_find_qns_isolation_requires_qns_distinct_from_other_keys() -> None:
    catalog = {
        "2707198": {"name": "Omelet", "portions": {"piece": 55.0, "qns": 110.0, "cup": 135.0}},
        "banana": {"name": "Banana", "portions": {"piece": 126.0, "qns": 126.0}},
    }
    omelet = {
        "id": "p6-log-0001",
        "items": [{"food_id": "2707198", "portion_key": "qns", "grams": 110.0}],
    }
    banana = {
        "id": "p6-log-0002",
        "items": [{"food_id": "banana", "portion_key": "qns", "grams": 126.0}],
    }
    piece = {
        "id": "p6-log-0003",
        "items": [{"food_id": "2707198", "portion_key": "piece", "grams": 55.0}],
    }
    assert phase6.find_qns_isolation([banana, piece], catalog) is None
    hit = phase6.find_qns_isolation([banana, omelet], catalog)
    assert hit is not None
    assert hit["id"] == "p6-log-0001"
    assert hit["food_id"] == "2707198"


def test_phase6_cli_synthetic_writes_manifest(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.json"
    manifest = tmp_path / "manifest.json"
    code = phase6.main(
        [
            "--synthetic",
            "--seed",
            "20260818",
            "--workers",
            "2",
            "--output",
            str(candidates),
            "--manifest",
            str(manifest),
            "--force",
        ]
    )
    assert code == 0
    assert candidates.is_file()
    assert manifest.is_file()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["seed"] == 20260818
    assert payload["catalog"].endswith("catalog-v2.sqlite")
    assert payload["n_slots"] == 20
    assert "qns_cross_check" in payload
    assert "quantifiers" in payload
    assert "fallbacks" in payload