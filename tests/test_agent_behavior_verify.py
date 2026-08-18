"""Ticket 08: ReAct exam behavior against catalog-v2.

Public seams:

- ``NutriEnv.step({op: search_foods|get_food})`` with catalog-v2.sqlite in S0
- ``runner._run_episode`` — Pass ⇔ end state == Oracle
- ``resolve_portion`` + ``react_manual("v1")`` handbook symmetry
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nutrienv.bench import Oracle, Scorer, Task
from nutrienv.bench.realize import GOLD_WINDOWS
from nutrienv.env import NutriEnv
from nutrienv.harness.react import react_manual
from nutrienv.harness.runner import _run_episode
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, Profile, WorldState

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


def test_search_foods_chicken_returns_catalog_v2_entries(catalog_v2) -> None:
    env = _env(catalog_v2)
    hits = env.step({"op": "search_foods", "q": "chicken"})["observation"]["results"]
    assert hits
    for row in hits:
        assert row["food_id"] not in OLD_SR_IDS
        food = env.step({"op": "get_food", "food_id": row["food_id"]})["observation"]["food"]
        assert food["data_type"] == "survey_fndds_food"
        assert food["food_id"] == row["food_id"]


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


def _spoken_span(query: str) -> str:
    """Drop the log imperative; resolve_portion reads the remainder."""
    text = query.strip().rstrip(".")
    for prefix in ("Please log that I ate ", "Please log ", "Log "):
        if text.lower().startswith(prefix.lower()):
            return text[len(prefix) :]
    return text


class _HandbookLogHarness:
    """Exam stand-in: search → get_food → convert the spoken span from observation.

    Not a live LLM. Grams come from the get_food portions table plus the
    query's spoken measure, via ``resolve_portion`` (the v1 handbook rules).
    """

    def __init__(self, search_q: str, food_id: str) -> None:
        self.search_q = search_q
        self.food_id = food_id

    def act(self, observation: dict, query: str, history: list) -> dict:
        ops = [
            event["action"].get("op")
            for event in history
            if isinstance(event.get("action"), dict)
        ]
        if "search_foods" not in ops:
            return {"op": "search_foods", "q": self.search_q}
        if "get_food" not in ops:
            return {"op": "get_food", "food_id": self.food_id}
        if "log_meal" not in ops:
            food = observation.get("food")
            if not isinstance(food, dict):
                return {"op": "finish"}
            observed = {str(food["food_id"]): food}
            grams = resolve_portion(
                str(food["food_id"]), _spoken_span(query), observed
            )
            if grams is None:
                return {"op": "finish"}
            return {
                "op": "log_meal",
                "food_id": food["food_id"],
                "grams": grams,
            }
        return {"op": "finish"}


def _log_task(catalog, query: str, food_id: str, grams: float | None) -> Task:
    s0 = WorldState(
        profile=Profile(user_id="verify", windows=dict(GOLD_WINDOWS)),
        ledger=[],
        catalog=catalog,
    )
    if grams is None:
        oracle = Oracle(ledger=())
    else:
        oracle = Oracle(
            ledger_tail=[
                LedgerRow(catalog.canonical_id(food_id), grams, "now")
            ]
        )
    return Task("verify-oral", "log", query, s0, oracle, situations=("fuzzy_portion",))


@pytest.mark.parametrize(
    ("query", "search_q", "food_id", "grams"),
    [
        ("Please log a piece of chicken.", "chicken", "chicken_breast", 105.0),
        (
            "Please log that I ate 150 g of chicken.",
            "chicken",
            "chicken_breast",
            150.0,
        ),
        ("Please log one apple.", "apple", "apple", 165.0),
        (
            "Please log half a cup of milk.",
            "milk",
            "milk_whole",
            122.0,  # cup=244 / 2; milk qns is the same 244 g table row
        ),
    ],
)
def test_runner_oral_queries_match_oracle(
    catalog_v2, query, search_q, food_id, grams
) -> None:
    task = _log_task(catalog_v2, query, food_id, grams)
    harness = _HandbookLogHarness(search_q, food_id)
    passed, tag, ops = _run_episode(task, harness, Scorer(), max_steps=8)
    assert "search_foods" in ops and "get_food" in ops
    assert "log_meal" in ops
    assert passed is True
    assert tag == "pass"


def test_runner_bare_chicken_breast_does_not_invent_grams(catalog_v2) -> None:
    task = _log_task(
        catalog_v2,
        "Please log a chicken breast.",
        "chicken_breast",
        None,
    )
    harness = _HandbookLogHarness("chicken breast", "chicken_breast")
    passed, tag, ops = _run_episode(task, harness, Scorer(), max_steps=8)
    assert "search_foods" in ops and "get_food" in ops
    assert "log_meal" not in ops
    assert passed is True
    assert tag == "pass"
    assert resolve_portion("chicken_breast", "a chicken breast", catalog_v2) is None


def test_handbook_matches_resolve_portion_on_catalog_v2(catalog_v2) -> None:
    manual = react_manual("v1")
    for phrase in (
        "one apple",
        "a banana",
        "two eggs",
        "a chicken breast",
        "portions.piece",
        "portions.qns",
    ):
        assert phrase in manual
    assert resolve_portion("chicken_breast", "a piece of chicken", catalog_v2) == 105.0
    assert resolve_portion("chicken_breast", "150 g of chicken", catalog_v2) == 150.0
    assert resolve_portion("apple", "one apple", catalog_v2) == 165.0
    assert resolve_portion("milk_whole", "half a cup of milk", catalog_v2) == 122.0
    assert resolve_portion("chicken_breast", "a chicken breast", catalog_v2) is None
    assert resolve_portion("tuna", "a can", catalog_v2) == 75.0


def test_gray_zone_portion_pairs_hold_on_catalog_v2(catalog_v2) -> None:
    """Rerun the judge-gate triples: sandwich 1.5× / lasagna 1.2× / omelet 2.0×."""
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
