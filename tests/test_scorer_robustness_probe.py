"""The tolerance probe perturbs relative to the gold anchor, which is what the band is about."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import scorer_robustness_probe as probe  # noqa: E402

CATALOG = {"oats": {"name": "oats"}, "rice": {"name": "rice"}}


def test_scale_lands_on_the_anchor_not_on_the_models_grams() -> None:
    # 77.5 g against a 78 g anchor: scaling the model's grams by 0.851 lands at 65.95 g,
    # -15.4% of gold, so a perturbation labelled "in band" was rejected correctly.
    actions = [
        {"op": "log_meal", "food_id": "oats", "grams": 70.0},
        {"op": "log_meal", "food_id": "oats", "grams": 77.5},
    ]
    out = probe.scale_grams(actions, 0.851, {"oats": 78.0}, CATALOG)
    assert out[0]["grams"] == 70.0  # the last write is the one that stays
    assert out[1]["grams"] == round(78.0 * 0.851, 3)
    assert actions[1]["grams"] == 77.5


def test_unanchored_or_amended_writes_are_unprobed() -> None:
    log = {"op": "log_meal", "food_id": "rice", "grams": 100.0}
    assert probe.scale_grams([log], 1.1, {"oats": 78.0}, CATALOG) is None
    amend = {"op": "amend_meal", "index": 0, "grams": 90.0}
    assert probe.scale_grams([log, amend], 1.1, {"rice": 100.0}, CATALOG) is None
