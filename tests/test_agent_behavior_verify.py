"""Ticket 08: catalog-v2 tool + handbook seams.

Live ReAct trajectories are recorded by ``scripts/agent_behavior_verify.py``
into ``reports/agent-behavior-verify.json``. This file does not stand in for
the agent with ``resolve_portion``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nutrienv.env import NutriEnv
from nutrienv.harness.react import react_manual
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import Profile, WorldState

ROOT = Path(__file__).resolve().parents[1]
CATALOG_V2 = ROOT / "data" / "fdc" / "catalog-v2.sqlite"

# Ticket 06 first-wins oral anchors (raw FNDDS rows, not QNS).
CHICKEN_FNDDS = "2705956"
TUNA_FNDDS = "2706311"
OLD_SR_IDS = (
    "171477",  # chicken_breast
    "171986",  # tuna
    "172448",  # tofu
    "171998",  # salmon
    "175180",  # shrimp
    "171793",  # beef
    "171413",  # olive_oil
    "173735",  # black_beans
    "172430",  # peanut
    "168592",  # almond
)


@pytest.fixture(scope="module")
def catalog_v2():
    if not CATALOG_V2.is_file():
        pytest.fail("data/fdc/catalog-v2.sqlite is missing; ticket 06 must land first")
    return load_catalog(CATALOG_V2)


def _env(catalog) -> NutriEnv:
    env = NutriEnv()
    env.reset(WorldState(profile=Profile(user_id="verify"), catalog=catalog))
    return env


def test_search_foods_chicken_returns_catalog_v2_staple(catalog_v2) -> None:
    env = _env(catalog_v2)
    hits = env.step({"op": "search_foods", "q": "chicken"})["observation"]["results"]
    assert hits
    ids = [row["food_id"] for row in hits]
    assert CHICKEN_FNDDS in ids
    assert ids[0] == CHICKEN_FNDDS
    for row in hits:
        assert row["food_id"] not in OLD_SR_IDS
        food = env.step({"op": "get_food", "food_id": row["food_id"]})["observation"]["food"]
        assert food["data_type"] == "survey_fndds_food"
        assert food["food_id"] == row["food_id"]
    staple = env.step({"op": "get_food", "food_id": ids[0]})["observation"]["food"]
    assert staple["portions"]["piece"] == 105.0


def test_recorded_live_results_cover_required_cases() -> None:
    """Evidence file exists; does not claim the live agent matched oracle."""
    import json
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import agent_behavior_verify as verify  # noqa: E402

    path = ROOT / "reports" / "agent-behavior-verify.json"
    assert path.is_file(), "run scripts/agent_behavior_verify.py to record live ReAct"
    payload = json.loads(path.read_text(encoding="utf-8"))
    got = {row["id"] for row in payload["cases"]}
    assert got == {case.id for case in verify.CASES}
    for row in payload["cases"]:
        assert isinstance(row.get("ops"), list)
        assert isinstance(row.get("actions"), list)
        assert "passed" in row
        assert "ledger" in row


def test_cut_noun_observation_file_is_multi_model() -> None:
    """Observation evidence only — does not require empty-ledger Pass."""
    import json

    path = ROOT / "reports" / "agent-behavior-cut-noun.json"
    assert path.is_file(), "re-run cut-noun observation (n>=3, >=2 models)"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload.get("oracle") == "empty ledger"
    assert payload.get("resolve_portion") is None
    runs = payload.get("runs") or []
    assert len(runs) >= 3
    models = {row["model"] for row in runs}
    assert len(models) >= 2
    for row in runs:
        assert "passed" in row
        assert "ops" in row
        assert "ledger" in row


def test_get_food_exposes_catalog_v2_oral_portion_tiers(catalog_v2) -> None:
    env = _env(catalog_v2)
    chicken = env.step({"op": "get_food", "food_id": CHICKEN_FNDDS})["observation"]["food"]
    tuna = env.step({"op": "get_food", "food_id": TUNA_FNDDS})["observation"]["food"]
    assert chicken["data_type"] == "survey_fndds_food"
    assert chicken["portions"]["piece"] == 105.0
    assert tuna["data_type"] == "survey_fndds_food"
    assert tuna["portions"]["can"] == 75.0
    slug = env.step({"op": "get_food", "food_id": "chicken_breast"})["observation"]["food"]
    assert slug["food_id"] == CHICKEN_FNDDS
    assert slug["portions"]["piece"] == 105.0


def test_handbook_matches_resolve_portion_on_catalog_v2(catalog_v2) -> None:
    manual = react_manual("v1")
    for phrase in (
        "one apple",
        "a banana",
        "two eggs",
        "a chicken breast",
        "portions.piece",
        "portions.qns",
        "do not log it, finish without logging that food",
    ):
        assert phrase in manual
    assert "ask for grams" not in manual
    assert resolve_portion("chicken_breast", "a piece of chicken", catalog_v2) == 105.0
    assert resolve_portion("chicken_breast", "150 g of chicken", catalog_v2) == 150.0
    assert resolve_portion("apple", "one apple", catalog_v2) == 165.0
    assert resolve_portion("milk_whole", "half a cup of milk", catalog_v2) == 122.0
    assert resolve_portion("chicken_breast", "a chicken breast", catalog_v2) is None
    assert resolve_portion("tuna", "a can", catalog_v2) == 75.0


def test_gray_zone_portion_pairs_hold_on_catalog_v2(catalog_v2) -> None:
    """Ground-truth table values on catalog-v2. Live judge is the verify script."""
    sandwich = catalog_v2["2706880"]["portions"]
    lasagna = catalog_v2["2708750"]["portions"]
    omelet = catalog_v2["2707198"]["portions"]
    assert sandwich["piece"] == 175.0
    assert sandwich["qns"] == 115.0
    assert lasagna["piece"] == 206.0
    assert lasagna["qns"] == 250.0
    assert omelet["piece"] == 55.0
    assert omelet["qns"] == 110.0
    assert resolve_portion("2706880", "a piece", catalog_v2) == 175.0
    assert resolve_portion("2706880", "a sandwich", catalog_v2) == 115.0
    assert resolve_portion("2708750", "a piece", catalog_v2) == 206.0
    assert resolve_portion("2708750", "a serving of lasagna", catalog_v2) == 250.0
    assert resolve_portion("2707198", "a piece", catalog_v2) == 55.0
    assert resolve_portion("2707198", "an omelet", catalog_v2) == 110.0


def test_old_sr_ids_do_not_appear_in_catalog_v2_exam(catalog_v2) -> None:
    env = _env(catalog_v2)
    for food_id in OLD_SR_IDS:
        assert food_id not in catalog_v2
        out = env.step({"op": "get_food", "food_id": food_id})
        assert out["ok"] is False
        assert out["error"]["code"] == "unknown_food"
    for needle in ("chicken", "tuna", "tofu", "salmon", "shrimp", "beef"):
        hits = env.step({"op": "search_foods", "q": needle})["observation"]["results"]
        assert hits
        assert all(row["food_id"] not in OLD_SR_IDS for row in hits)


def test_qns_differs_from_first_wins_oral_anchors(catalog_v2) -> None:
    """Ticket 06 Opus follow-through: QNS is not the spoken piece/can anchor."""
    chicken = catalog_v2["chicken_breast"]["portions"]
    tuna = catalog_v2["tuna"]["portions"]
    beef = catalog_v2["beef"]["portions"]
    assert chicken["qns"] == 120.0
    assert chicken["piece"] == 105.0
    assert tuna["qns"] == 85.0
    assert tuna["can"] == 75.0
    assert beef["qns"] == 85.0
    assert beef["piece"] == 65.0
    assert resolve_portion("chicken_breast", "a piece", catalog_v2) == 105.0
    assert resolve_portion("chicken_breast", "a serving", catalog_v2) == 120.0
    assert resolve_portion("tuna", "a can", catalog_v2) == 75.0
    assert resolve_portion("tuna", "a serving", catalog_v2) == 85.0
    assert resolve_portion("beef", "a piece", catalog_v2) == 65.0
    assert resolve_portion("beef", "a serving", catalog_v2) == 85.0
