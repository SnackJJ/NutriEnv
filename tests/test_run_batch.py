"""S1: run_batch through injectable fakes. External behaviour only."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nutrienv.bench.pipeline import catalog_digest, pass_through_reviewer, run_batch
from nutrienv.bench.pipeline.run_batch import quota_ledger
from nutrienv.bench.realize import Oracle, Task
from nutrienv.bench.split import load_exam, load_split
from nutrienv.bench.validator import validate_draft

V05 = Path("data/splits/archive/v0.5-gold.json")


def _catalog() -> dict:
    return {
        "apple": {
            "name": "Apple, raw",
            "portions": {"piece": 182.0},
            "aliases": ["apple", "apples"],
            "allergen_tags": [],
        },
        "orange": {
            "name": "Orange, raw",
            "portions": {"piece": 131.0},
            "aliases": ["orange", "oranges"],
            "allergen_tags": [],
        },
        "milk_whole": {
            "name": "Milk, whole",
            "portions": {"cup": 244.0},
            "aliases": ["milk", "whole milk"],
            "allergen_tags": ["milk"],
        },
        "oats": {
            "name": "Oats, rolled",
            "portions": {"cup": 81.0},
            "aliases": ["oatmeal", "oats"],
            "allergen_tags": [],
        },
        "banana": {
            "name": "Banana, raw",
            "portions": {"piece": 118.0},
            "aliases": ["banana", "bananas"],
            "allergen_tags": [],
        },
        "egg": {
            "name": "Egg, whole",
            "portions": {"piece": 50.0},
            "aliases": ["eggs", "egg"],
            "allergen_tags": ["egg"],
        },
        "white_rice": {
            "name": "Rice, white",
            "portions": {"cup": 158.0},
            "aliases": ["rice"],
            "allergen_tags": [],
        },
        "broccoli": {
            "name": "Broccoli, cooked",
            "portions": {"cup": 156.0},
            "aliases": ["broccoli"],
            "allergen_tags": [],
        },
        "chicken_breast": {
            "name": "Chicken breast",
            "portions": {"piece": 172.0},
            "aliases": ["chicken"],
            "allergen_tags": [],
        },
        "tofu": {
            "name": "Tofu, firm",
            "portions": {"piece": 80.0},
            "aliases": ["tofu"],
            "allergen_tags": ["soy"],
        },
    }


def _ok_judge(_food: str, _grams: float) -> str:
    return "ok"


def _suspect_judge(_food: str, _grams: float) -> str:
    return "suspect"


def _expander(payloads):
    def expand(_pool, *, persona, family):
        return payloads

    return expand


def _spec(tmp_path: Path, catalog, **overrides) -> dict:
    spec = {
        "seed": 7,
        "sampler_rule_version": "sampler-v1",
        "catalog_sha": catalog_digest(catalog),
        "persona": "everyday",
        "family_quotas": {"log": 1},
        "model_route": {},
        "catalog": "fixture",
        "output_path": tmp_path / "batch.json",
    }
    spec.update(overrides)
    return spec


def _run(tmp_path: Path, payloads, *, judge=_ok_judge, catalog=None, **overrides):
    foods = catalog if catalog is not None else _catalog()
    return run_batch(
        _spec(tmp_path, foods, **overrides),
        expander=_expander(payloads),
        judge=judge,
        reviewer=pass_through_reviewer,
        catalog=foods,
    )


_PASS = {
    "items": [{"food": "milk_whole", "expression": "a cup"}],
    "query": "Please log a cup of milk for lunch.",
}


def test_resolvable_candidate_passes_end_to_end(tmp_path: Path) -> None:
    result = _run(tmp_path, [_PASS])
    assert len(result.accepted) == 1
    task = result.accepted[0]
    assert task.family == "log"
    assert task.oracle.ledger_tail
    assert task.oracle.ledger_tail[0].grams == 244.0
    assert result.path is not None and result.path.is_file()
    assert result.payload["version"] == "pipeline-draft"
    assert result.review["anomalies"] == []


def _fndds_shortname_catalog() -> dict:
    """Eight speakable foods so the sampler puts every id in the pool."""
    catalog = {
        key: value
        for key, value in _catalog().items()
        if key
        in {
            "apple",
            "orange",
            "milk_whole",
            "banana",
            "egg",
            "white_rice",
            "broccoli",
        }
    }
    catalog["2708838"] = {
        "name": "Pasta with tomato-based sauce and meat, home recipe",
        "portions": {"cup": 250.0, "qns": 250.0},
        "aliases": [],
        "allergen_tags": [],
    }
    return catalog


def test_run_batch_resolves_fndds_comma_head_short_name(tmp_path: Path) -> None:
    """Expander-valid short names (catalog-v2 FNDDS descriptions) must resolve."""
    payload = {
        "items": [
            {
                "food": "Pasta with tomato-based sauce and meat",
                "expression": "a cup",
            }
        ],
        "query": "Please log a cup of pasta with tomato-based sauce and meat.",
    }
    result = _run(tmp_path, [payload], catalog=_fndds_shortname_catalog())
    assert len(result.accepted) == 1
    row = result.accepted[0].oracle.ledger_tail[0]
    assert row.food_id == "2708838"
    assert row.grams == 250.0


def test_unresolvable_expression_is_rejected(tmp_path: Path) -> None:
    bad = {
        "items": [{"food": "milk_whole", "expression": "a slice"}],
        "query": "Please log a slice of milk for lunch.",
    }
    result = _run(tmp_path, [bad])
    assert result.accepted == []
    assert any(item.reason == "unresolvable" for item in result.rejected)
    assert result.path is None


def test_absurd_grams_rejected_by_judge(tmp_path: Path) -> None:
    off_table = {
        "items": [{"food": "milk_whole", "expression": "30 g"}],
        "query": "Please log 30 g of milk for lunch.",
    }
    result = _run(tmp_path, [off_table], judge=_suspect_judge)
    assert result.accepted == []
    assert any(item.reason == "implausible" for item in result.rejected)


@pytest.mark.parametrize(
    "query",
    [
        "Please log a cup of milk_whole for lunch.",
        "Please log a cup of milk. kcal 1800",
    ],
    ids=["slug", "window"],
)
def test_leaking_query_is_rejected(tmp_path: Path, query: str) -> None:
    leak = {"items": [{"food": "milk_whole", "expression": "a cup"}], "query": query}
    result = _run(tmp_path, [leak])
    assert result.accepted == []
    assert any(item.reason == "leak" for item in result.rejected)


def test_query_backresolve_mismatch_is_rejected_by_default(tmp_path: Path) -> None:
    rewritten = {
        "items": [{"food": "milk_whole", "expression": "a cup"}],
        "query": "Please log some milk for lunch.",
    }
    result = _run(tmp_path, [rewritten])
    assert result.accepted == []
    assert any(item.reason == "backresolve" for item in result.rejected)


def test_skip_gram_backresolve_admits_unresolvable_query_phrasing(tmp_path: Path) -> None:
    rewritten = {
        "items": [{"food": "milk_whole", "expression": "a cup"}],
        "query": "Please log some milk for lunch.",
    }
    result = _run(tmp_path, [rewritten], skip_gram_backresolve=True)
    assert len(result.accepted) == 1
    assert result.accepted[0].oracle.ledger_tail[0].grams == 244.0


def test_near_duplicate_pools_are_deduped(tmp_path: Path) -> None:
    first = {
        "items": [{"food": "milk_whole", "expression": "a cup"}],
        "query": "Please log a cup of milk for lunch.",
    }
    second = {
        "items": [{"food": "whole milk", "expression": "one cup"}],
        "query": "Log one cup of whole milk at lunch.",
    }
    result = _run(tmp_path, [first, second], family_quotas={"log": 1})
    assert len(result.accepted) == 1
    assert any(item.reason == "duplicate" for item in result.rejected)


def test_same_seed_frozen_output_is_byte_identical(tmp_path: Path) -> None:
    catalog = _catalog()
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _run(first_dir, [_PASS], catalog=catalog)
    second = _run(second_dir, [_PASS], catalog=catalog)
    assert first.path is not None and second.path is not None
    left = first.path.read_bytes()
    right = second.path.read_bytes()
    assert left == right
    assert hashlib.sha256(left).hexdigest() == hashlib.sha256(right).hexdigest()


def test_catalog_sha_mismatch_raises(tmp_path: Path) -> None:
    catalog = _catalog()
    spec = _spec(tmp_path, catalog)
    spec["catalog_sha"] = "0" * 64
    with pytest.raises(ValueError, match="catalog sha256 mismatch"):
        run_batch(
            spec,
            expander=_expander([_PASS]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=catalog,
        )


def test_archived_v05_is_rejected_by_load_exam() -> None:
    assert V05.is_file()
    with pytest.raises(ValueError, match="version"):
        load_exam(V05)
    payload = V05.read_text(encoding="utf-8")
    assert '"version": "v0.5-gold"' in payload
    assert "data/fdc/archive/catalog.sqlite" in payload


def _ledger_item(composite: bool):
    oracle = Oracle(sub_oracles=(Oracle(), Oracle())) if composite else Oracle()
    return Task("t", "log", "q", object(), oracle)


def test_quota_ledger_enforces_adr_0016_ceilings() -> None:
    full = [_ledger_item(True)] * 36 + [_ledger_item(False)] * 204
    ledger = quota_ledger(full, (("log", 204), ("composite", 36)))
    assert ledger["composite_accepted"] == 36
    with pytest.raises(ValueError, match="admission slots"):
        quota_ledger([_ledger_item(True)] * 37, (("composite", 37),))
    with pytest.raises(ValueError, match="240-item exam"):
        quota_ledger([_ledger_item(False)] * 241, (("log", 241),))


def test_quota_ledger_counts_recommend_and_update_against_the_exam() -> None:
    def _family(family: str):
        return Task("t", family, "q", object(), Oracle())

    tasks = [_family("recommend")] * 200 + [_family("update")] * 40
    ledger = quota_ledger(tasks, (("recommend", 200), ("update", 40)))
    assert ledger["single_family_accepted"] == {"recommend": 200, "update": 40}
    assert ledger["composite_accepted"] == 0
    with pytest.raises(ValueError, match="240-item exam"):
        quota_ledger(tasks + [_family("recommend")], (("recommend", 201),))


_RECOMMEND = {
    "items": [{"food": "milk_whole", "expression": "a cup"}],
    "query": "What should I eat along with a cup of milk for dinner?",
}

_UPDATE = {
    "items": [{"food": "egg", "expression": "a piece"}],
    "query": "Please remember, I am now allergic to egg, so no more egg.",
}

# fitting_plan searches staples for an allergen-safe plan inside the judged
# windows, so the fixture staples need nutrient tables.
_STAPLE_NUTRIENTS = {
    "white_rice": {"kcal": 130.0, "protein_g": 2.7},
    "chicken_breast": {"kcal": 165.0, "protein_g": 31.0},
}


def _nutrient_catalog() -> dict:
    catalog = _catalog()
    for food_id, nutrients in _STAPLE_NUTRIENTS.items():
        catalog[food_id]["nutrients"] = dict(nutrients)
    # The roster profile carries a peanut allergy; every oracle allergy must
    # be a catalog tag, so the fixture needs a peanut carrier too.
    catalog["peanut_butter"] = {
        "name": "Peanut butter",
        "portions": {"tbsp": 16.0},
        "aliases": ["peanut butter"],
        "allergen_tags": ["peanut"],
        "nutrients": {"kcal": 588.0, "protein_g": 25.0},
    }
    return catalog


def test_recommend_family_job_yields_a_recommend_task(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [_RECOMMEND],
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"recommend": 1},
    )
    assert result.rejected == []
    assert len(result.accepted) == 1
    task = result.accepted[0]
    assert task.family == "recommend"
    assert task.oracle.last_plan == []
    assert task.oracle.plan_must_be_safe
    assert task.oracle.plan_must_fit_windows
    assert task.oracle.plan_windows is not None


def test_update_family_job_yields_an_add_allergy_update_task(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [_UPDATE],
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"update": 1},
    )
    assert result.rejected == []
    assert len(result.accepted) == 1
    task = result.accepted[0]
    assert task.family == "update"
    added = set(task.oracle.profile.allergies) - set(task.s0.profile.allergies)
    assert added == {"egg"}
    assert task.oracle.ledger is not None
    assert task.oracle.update_band is None


def test_occasion_less_recommend_is_rejected_not_dinner_defaulted(tmp_path: Path) -> None:
    payload = {
        "items": [{"food": "milk_whole", "expression": "a cup"}],
        "query": "Given the cup of milk I already had, what should I eat?",
    }
    result = _run(
        tmp_path,
        [payload],
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"recommend": 1},
    )
    assert result.accepted == []
    assert [(r.reason, r.family) for r in result.rejected] == [
        ("unresolvable", "recommend")
    ]


def test_recommend_context_food_absent_from_query_is_containment_rejected(
    tmp_path: Path,
) -> None:
    payload = {
        "items": [{"food": "egg", "expression": "a piece"}],
        "query": "What should I eat along with a cup of milk for dinner?",
    }
    result = _run(
        tmp_path,
        [payload],
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"recommend": 1},
    )
    assert result.accepted == []
    assert [(r.reason, r.family) for r in result.rejected] == [
        ("containment", "recommend")
    ]


_EVALUATE_FIT = {
    "items": [{"food": "milk_whole", "expression": "a cup"}],
    "query": "Evaluate this as my plan: a cup of milk.",
}


def _knife_catalog() -> dict:
    """Compact catalog: every food lands in every pool, so the allergy
    knife deterministically finds its peanut carrier."""
    catalog = _nutrient_catalog()
    keep = {"milk_whole", "egg", "chicken_breast", "white_rice", "peanut_butter"}
    return {food_id: entry for food_id, entry in catalog.items() if food_id in keep}


def test_empty_family_recipes_behave_like_today(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [_EVALUATE_FIT],
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"evaluate": 1},
        family_recipes={"evaluate": {}},
    )
    assert result.accepted != []
    task = result.accepted[0]
    assert task.family == "evaluate"
    assert task.tier == ""
    assert task.oracle.last_verdict is None or task.oracle.last_verdict == "accept"
    assert all(r.reason != "unresolvable" for r in result.rejected)


def test_tier_recipe_is_carried_into_the_frozen_output(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [_EVALUATE_FIT],
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"evaluate": 1},
        family_recipes={"evaluate": {"tier": "pair"}},
    )
    assert result.rejected == [] or all(
        r.reason != "unresolvable" for r in result.rejected
    )
    assert result.accepted, result.rejected
    task = result.accepted[0]
    assert task.tier == "pair"
    item = next(i for i in result.payload["items"] if i["id"] == task.id)
    assert item["tier"] == "pair"


def test_knife_recipe_produces_an_evaluate_unfit(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [_EVALUATE_FIT],
        judge=_ok_judge,
        catalog=_knife_catalog(),
        family_quotas={"evaluate": 1},
        family_recipes={"evaluate": {"knife": "allergy", "occasion": "dinner"}},
    )
    assert len(result.accepted) == 1, [
        (r.reason, r.family) for r in result.rejected
    ]
    (task,) = result.accepted
    assert task.oracle.last_verdict == "reject"
    assert task.oracle.evaluated_plan
    assert task.oracle.last_plan == []
    assert task.oracle.last_reasons
    assert validate_draft(task) == []


def test_unknown_recipe_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown recipe key"):
        run_batch(
            _spec(
                tmp_path,
                _catalog(),
                family_quotas={"evaluate": 1},
                family_recipes={"evaluate": {"bogus": "x"}},
            ),
            expander=_expander([_EVALUATE_FIT]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=_catalog(),
        )


def test_leftover_scene_recipe_for_recommend_is_rejected_cleanly(
    tmp_path: Path,
) -> None:
    # scene="leftover" needs prior_logs: the batch's leftover carrier is
    # composite log+recommend; single-family leftover stays generate_one-only.
    result = _run(
        tmp_path,
        [_RECOMMEND],
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"recommend": 1},
        family_recipes={"recommend": {"scene": "leftover"}},
    )
    assert result.accepted == []
    assert [(r.reason, r.family) for r in result.rejected] == [
        ("unresolvable", "recommend")
    ]
