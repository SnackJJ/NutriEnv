"""S1: run_batch through injectable fakes. External behaviour only."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nutrienv.bench.pipeline import catalog_digest, pass_through_reviewer, run_batch
from nutrienv.bench.pipeline.expander import synthetic_expander
from nutrienv.bench.pipeline.run_batch import quota_ledger
from nutrienv.bench.realize import Oracle, Task, bind_evaluate_reasons
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


def _run(
    tmp_path: Path,
    payloads,
    *,
    judge=_ok_judge,
    catalog=None,
    expander=None,
    **overrides,
):
    foods = catalog if catalog is not None else _catalog()
    return run_batch(
        _spec(tmp_path, foods, **overrides),
        expander=expander if expander is not None else _expander(payloads),
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
    "olive_oil": {"kcal": 884.0, "protein_g": 0.0},
}


def _nutrient_catalog() -> dict:
    catalog = _catalog()
    for food_id, nutrients in _STAPLE_NUTRIENTS.items():
        catalog.setdefault(food_id, {"name": food_id.replace("_", " ")})
        catalog[food_id]["nutrients"] = dict(nutrients)
    catalog["olive_oil"] = {
        "name": "Oil, olive",
        "portions": {"tbsp": 13.5},
        "aliases": ["olive oil"],
        "allergen_tags": [],
        "nutrients": {"kcal": 884.0, "protein_g": 0.0},
    }
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
    "items": [
        {"food": "white_rice", "expression": "two cups"},
        {"food": "olive_oil", "expression": "two tablespoons"},
    ],
    "query": (
        "Evaluate what I should eat for dinner: two cups of rice, "
        "and two tablespoons of olive oil."
    ),
}


def _knife_catalog() -> dict:
    """Compact catalog: every food lands in every pool, so the allergy
    knife deterministically finds its peanut carrier."""
    catalog = _nutrient_catalog()
    keep = {
        "white_rice", "olive_oil", "peanut_butter",
    }
    return {food_id: entry for food_id, entry in catalog.items() if food_id in keep}


def test_empty_family_recipes_behave_like_today(tmp_path: Path) -> None:
    def _run_once(recipes):
        result = _run(
            tmp_path,
            [_EVALUATE_FIT],
            judge=_ok_judge,
            catalog=_nutrient_catalog(),
            family_quotas={"evaluate": 1},
            family_recipes=recipes,
        )
        assert result.rejected == [], [(r.reason, r.family) for r in result.rejected]
        (task,) = result.accepted
        return task

    plain = _run_once(None)
    empty = _run_once({"evaluate": {}})
    assert empty == plain
    assert empty.tier == ""
    assert empty.family == "evaluate"


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
    from nutrienv.bench.pipeline.freezer import freeze_tasks
    from nutrienv.bench.quality_gates import evaluate_unfits

    result = _run(
        tmp_path,
        [_EVALUATE_FIT],
        judge=_ok_judge,
        catalog=_knife_catalog(),
        family_quotas={"evaluate": 1},
        family_recipes={
            "evaluate": {"knife": "allergy", "tier": "single"},
        },
    )
    assert len(result.accepted) == 1, [
        (r.reason, r.family) for r in result.rejected
    ]
    (task,) = result.accepted
    oracle = task.oracle
    # ADR 0017 fit->knife: reject envelope over the knifed plate, reasons ==
    # bind of that plate against the SAME windows the input was confirmed on.
    assert oracle.last_verdict == "reject"
    assert oracle.last_plan == []
    assert oracle.evaluated_plan
    assert "allergy" in oracle.last_reasons
    assert set(oracle.last_reasons) == set(
        bind_evaluate_reasons(
            oracle.evaluated_plan,
            oracle.plan_windows,
            task.s0.catalog,
            task.s0.profile.allergies,
        )
    )
    assert validate_draft(task) == []
    assert evaluate_unfits([task]) == (task.id,)
    # Gram-exact speech: every evaluated item is spoken with its table grams.
    for item in oracle.evaluated_plan:
        amount = int(item["grams"])
        assert f"{amount} g of" in task.query
    # Reloadable end to end.
    _, target = freeze_tasks(
        [task], catalog=task.s0.catalog, output_path=tmp_path / "knife.json"
    )
    (loaded,) = load_split(target, catalog=task.s0.catalog)
    assert loaded.tier == "single"
    assert loaded.oracle.last_verdict == "reject"
    assert validate_draft(loaded) == []


def test_knife_input_that_does_not_fit_is_rejected(tmp_path: Path) -> None:
    # A plate that is already unfit (half a cup of rice is kcal_lo for the
    # dinner slot) never reaches the knife: ADR 0017 needs fit -> knife.
    starving = {
        "items": [{"food": "white_rice", "expression": "half a cup"}],
        "query": "Evaluate this as dinner: half a cup of rice.",
    }
    result = _run(
        tmp_path,
        [starving],
        judge=_ok_judge,
        catalog=_knife_catalog(),
        family_quotas={"evaluate": 1},
        family_recipes={"evaluate": {"knife": "allergy"}},
    )
    assert result.accepted == []
    assert [(r.reason, r.family) for r in result.rejected] == [
        ("unresolvable", "evaluate")
    ]


def test_swap_knife_recipe_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="swap"):
        run_batch(
            _spec(
                tmp_path,
                _catalog(),
                family_quotas={"evaluate": 1},
                family_recipes={"evaluate": {"knife": "swap"}},
            ),
            expander=_expander([_EVALUATE_FIT]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=_catalog(),
        )


def test_recipe_null_value_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        run_batch(
            _spec(
                tmp_path,
                _catalog(),
                family_quotas={"evaluate": 1},
                family_recipes={"evaluate": {"tier": None}},
            ),
            expander=_expander([_EVALUATE_FIT]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=_catalog(),
        )


def test_recipe_for_unrequested_family_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not among the requested"):
        run_batch(
            _spec(
                tmp_path,
                _catalog(),
                family_quotas={"log": 1},
                family_recipes={"evaluate": {"tier": "pair"}},
            ),
            expander=_expander([_PASS]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=_catalog(),
        )


def test_recommend_shell_and_scene_recipes_are_refused_at_parse(
    tmp_path: Path,
) -> None:
    # Narrowed design authority: shell/scene are generate_one-only until
    # resolver semantics exist.
    for recipe in ({"shell": "rec-named-dish"}, {"scene": "leftover"}):
        with pytest.raises(ValueError, match="not supported for 'recommend'"):
            run_batch(
                _spec(
                    tmp_path,
                    _nutrient_catalog(),
                    family_quotas={"recommend": 1},
                    family_recipes={"recommend": recipe},
                ),
                expander=_expander([_RECOMMEND]),
                judge=_ok_judge,
                reviewer=pass_through_reviewer,
                catalog=_nutrient_catalog(),
            )


def test_bogus_tier_recipe_is_refused_at_parse(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tier must be one of"):
        run_batch(
            _spec(
                tmp_path,
                _catalog(),
                family_quotas={"evaluate": 1},
                family_recipes={"evaluate": {"tier": "bogus-tier"}},
            ),
            expander=_expander([_EVALUATE_FIT]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=_catalog(),
        )


def test_tier_recipe_is_evaluate_only(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not supported for 'log'"):
        run_batch(
            _spec(
                tmp_path,
                _nutrient_catalog(),
                family_quotas={"log": 1},
                family_recipes={"log": {"tier": "single"}},
            ),
            expander=_expander([_PASS]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=_nutrient_catalog(),
        )


def test_evaluate_occasion_knob_is_no_longer_accepted(tmp_path: Path) -> None:
    # evaluate.occasion was a silent no-op on the fit path; the knife branch
    # reads the occasion from the spoken query instead, so the knob is gone.
    with pytest.raises(ValueError, match="not supported for 'evaluate'"):
        run_batch(
            _spec(
                tmp_path,
                _nutrient_catalog(),
                family_quotas={"evaluate": 1},
                family_recipes={"evaluate": {"occasion": "breakfast"}},
            ),
            expander=_expander([_EVALUATE_FIT]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=_nutrient_catalog(),
        )


def test_items_recipe_produces_an_n_food_evaluate_plate(tmp_path: Path) -> None:
    from nutrienv.bench.pipeline.freezer import freeze_tasks
    from nutrienv.bench.split import load_split

    result = _run(
        tmp_path,
        None,
        expander=synthetic_expander,
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"evaluate": 1},
        family_recipes={"evaluate": {"items": "3", "tier": "triple"}},
    )
    assert result.rejected == []
    (task,) = result.accepted
    assert task.tier == "triple"
    assert len(task.oracle.last_plan) == 3
    assert validate_draft(task) == []
    _, target = freeze_tasks(
        [task], catalog=task.s0.catalog, output_path=tmp_path / "triple.json"
    )
    (loaded,) = load_split(target, catalog=task.s0.catalog)
    assert loaded.tier == "triple"
    assert len(loaded.oracle.last_plan) == 3


def test_explicit_grams_recipe_speaks_gram_amounts(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        None,
        expander=synthetic_expander,
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"evaluate": 1},
        family_recipes={
            "evaluate": {"amount_path": "explicit_grams", "tier": "explicit_grams"},
        },
    )
    assert result.rejected == []
    (task,) = result.accepted
    assert task.tier == "explicit_grams"
    assert " g of " in task.query
    for item in task.oracle.evaluated_plan or task.oracle.last_plan:
        assert f"{item['grams']:g} g" in task.query
    assert validate_draft(task) == []


def test_items_shortfall_is_a_clean_rejection(tmp_path: Path) -> None:
    thin = {
        food_id: entry
        for food_id, entry in _nutrient_catalog().items()
        if food_id in {"white_rice", "olive_oil"}
    }
    result = _run(
        tmp_path,
        None,
        expander=synthetic_expander,
        judge=_ok_judge,
        catalog=thin,
        family_quotas={"evaluate": 1},
        family_recipes={"evaluate": {"items": "3"}},
    )
    assert result.accepted == []
    assert [(r.reason, r.family) for r in result.rejected] == [
        ("schema", "evaluate")
    ]


def test_items_and_amount_path_recipes_are_validated(tmp_path: Path) -> None:
    cases = [
        ({"items": "0"}, "items must be a positive integer"),
        ({"items": "abc"}, "items must be a positive integer"),
        ({"items": "-1"}, "items must be a positive integer"),
        ({"amount_path": "bogus"}, "amount_path must be one of"),
        ({"amount_path": "named_measure"}, "amount_path must be one of"),
        ({"amount_path": "unspecified"}, "amount_path must be one of"),
    ]
    for recipe, message in cases:
        with pytest.raises(ValueError, match=message):
            run_batch(
                _spec(
                    tmp_path,
                    _catalog(),
                    family_quotas={"evaluate": 1},
                    family_recipes={"evaluate": dict(recipe)},
                ),
                expander=_expander([_EVALUATE_FIT]),
                judge=_ok_judge,
                reviewer=pass_through_reviewer,
                catalog=_catalog(),
            )


def test_recommend_tier_recipe_stays_refused(tmp_path: Path) -> None:
    # R-1 regression guard: tier is evaluate-only authoring data.
    with pytest.raises(ValueError, match="not supported for 'recommend'"):
        run_batch(
            _spec(
                tmp_path,
                _nutrient_catalog(),
                family_quotas={"recommend": 1},
                family_recipes={"recommend": {"tier": "pair"}},
            ),
            expander=_expander([_RECOMMEND]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=_nutrient_catalog(),
        )


def test_items_and_amount_path_hints_require_the_synthetic_expander(
    tmp_path: Path,
) -> None:
    # Fail closed on real (LLM) runs instead of silently ignoring the knobs.
    for recipe in ({"items": "3"}, {"amount_path": "explicit_grams"}):
        with pytest.raises(ValueError, match="require the synthetic expander"):
            run_batch(
                _spec(
                    tmp_path,
                    _nutrient_catalog(),
                    family_quotas={"evaluate": 1},
                    family_recipes={"evaluate": dict(recipe)},
                ),
                expander=_expander([_EVALUATE_FIT]),
                judge=_ok_judge,
                reviewer=pass_through_reviewer,
                catalog=_nutrient_catalog(),
            )


def test_expander_hint_mismatch_fails_at_entry_before_any_job(tmp_path: Path) -> None:
    """N-1: a mixed-quota real batch fails at run_batch entry -- before
    sampling or any expander call -- so recipe-free jobs waste no LLM calls."""
    calls = []

    def fake_llm_expander(_pool, *, persona, family):
        calls.append((family, persona))
        return {"items": [], "query": ""}

    with pytest.raises(ValueError, match="require the synthetic expander"):
        _run(
            tmp_path,
            None,
            expander=fake_llm_expander,
            judge=_ok_judge,
            catalog=_nutrient_catalog(),
            family_quotas={"evaluate": 1, "log": 5},
            family_recipes={"evaluate": {"items": "3"}},
        )
    assert calls == []


def test_person_recipe_uses_the_chosen_roster_profile(tmp_path: Path) -> None:
    """cam (egg allergy, cut phase) replaces ROSTER[0] on the knife path.

    Her cut-phase dinner slot is smaller ([390.2, 520.3] kcal), so the plate
    is two cups of rice; the allergy knife then adds the peanut carrier.
    """
    rice_plate = {
        "items": [{"food": "white_rice", "expression": "two cups"}],
        "query": "Evaluate what I should eat for dinner: two cups of rice.",
    }
    catalog = {
        "white_rice": {
            "name": "Rice, white",
            "portions": {"cup": 158.0},
            "aliases": ["rice"],
            "allergen_tags": [],
            "nutrients": {"kcal": 130.0, "protein_g": 2.7},
        },
        # cam's allergy tag is egg: the carrier the allergy knife needs.
        "egg": {
            "name": "Egg, whole",
            "portions": {"piece": 50.0},
            "aliases": ["eggs", "egg"],
            "allergen_tags": ["egg"],
            "nutrients": {"kcal": 165.0, "protein_g": 31.0},
        },
    }
    result = _run(
        tmp_path,
        [rice_plate],
        judge=_ok_judge,
        catalog=catalog,
        family_quotas={"evaluate": 1},
        family_recipes={
            "evaluate": {
                "knife": "allergy",
                "tier": "single",
                "person": "roster-cam",
            },
        },
    )
    assert len(result.accepted) == 1, [
        (r.reason, r.family) for r in result.rejected
    ]
    (task,) = result.accepted
    assert task.oracle.last_verdict == "reject"
    assert task.s0.profile.phase == "cut"
    assert "egg" in task.s0.profile.allergies
    assert "allergy" in task.oracle.last_reasons
    assert validate_draft(task) == []


def _person_catalog() -> dict:
    """Foods without fay/cam allergen carriers, so their plates never clash."""
    return {
        food_id: entry
        for food_id, entry in _nutrient_catalog().items()
        if food_id not in {"milk_whole", "egg"}
    }


def test_recommend_person_recipe_carries_the_allergy(tmp_path: Path) -> None:
    from nutrienv.bench.quality_gates import recommend_coverage

    fay = _run(
        tmp_path,
        None,
        expander=synthetic_expander,
        judge=_ok_judge,
        catalog=_person_catalog(),
        family_quotas={"recommend": 2},
        family_recipes={"recommend": {"person": "roster-fay"}},
        overwrite=True,
    )
    assert fay.rejected == []
    coverage = recommend_coverage(fay.accepted, personas=("everyday",))
    assert coverage.missing_personas == ()
    assert "milk" not in coverage.missing_allergens


def test_mixed_person_recipes_cover_cut_and_both_allergens(tmp_path: Path) -> None:
    from nutrienv.bench.quality_gates import recommend_coverage

    cam = _run(
        tmp_path,
        None,
        expander=synthetic_expander,
        judge=_ok_judge,
        catalog=_person_catalog(),
        family_quotas={"recommend": 1},
        family_recipes={"recommend": {"person": "roster-cam"}},
    )
    fay = _run(
        tmp_path,
        None,
        expander=synthetic_expander,
        judge=_ok_judge,
        catalog=_person_catalog(),
        family_quotas={"recommend": 1},
        family_recipes={"recommend": {"person": "roster-fay"}},
        overwrite=True,
    )
    tasks = [*cam.accepted, *fay.accepted]
    report = recommend_coverage(tasks, personas=("cut", "everyday"))
    assert report.missing_personas == ()
    assert "egg" not in report.missing_allergens
    assert "milk" not in report.missing_allergens


def test_unknown_roster_person_is_refused_at_parse(tmp_path: Path) -> None:
    for bad in ("roster-bogus", "999"):
        with pytest.raises(ValueError, match="roster"):
            run_batch(
                _spec(
                    tmp_path,
                    _nutrient_catalog(),
                    family_quotas={"recommend": 1},
                    family_recipes={"recommend": {"person": bad}},
                ),
                expander=_expander([_RECOMMEND]),
                judge=_ok_judge,
                reviewer=pass_through_reviewer,
                catalog=_nutrient_catalog(),
            )


def test_person_index_recipe_resolves(tmp_path: Path) -> None:
    # roster index 2 == roster-cam.
    result = _run(
        tmp_path,
        [_RECOMMEND],
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"recommend": 1},
        family_recipes={"recommend": {"person": "2"}},
    )
    assert len(result.accepted) == 1
    (task,) = result.accepted
    assert task.s0.profile.user_id == "roster-cam"


def test_log_person_recipe_is_refused(tmp_path: Path) -> None:
    # log has no person semantics resolver-side.
    with pytest.raises(ValueError, match="not supported for 'log'"):
        run_batch(
            _spec(
                tmp_path,
                _nutrient_catalog(),
                family_quotas={"log": 1},
                family_recipes={"log": {"person": "roster-cam"}},
            ),
            expander=_expander([_PASS]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=_nutrient_catalog(),
        )


def test_evaluate_fit_person_honours_the_roster_profile(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [_EVALUATE_FIT],
        judge=_ok_judge,
        catalog=_knife_catalog(),
        family_quotas={"evaluate": 1},
        family_recipes={"evaluate": {"person": "roster-cam", "tier": "single"}},
    )
    assert result.rejected == [], [(r.reason,) for r in result.rejected]
    (task,) = result.accepted
    # cam owns the identity: persona and allergies come from her roster
    # entry (the legacy realize path re-derives meal windows from the gold
    # table, so those stay put).
    baseline = _run(
        tmp_path,
        [_EVALUATE_FIT],
        judge=_ok_judge,
        catalog=_knife_catalog(),
        family_quotas={"evaluate": 1},
        output_path=tmp_path / "plain.json",
    )
    (baseline_task,) = baseline.accepted

    assert task.persona == "cut"
    assert task.s0.profile.allergies == ("egg",)
    assert baseline_task.s0.profile.allergies == ("peanut",)
    assert baseline_task.persona == "everyday"
    assert validate_draft(task) == []


_COMPOSITE = {
    "items": [{"food": "milk_whole", "expression": "a cup"}],
    "query": (
        "Please log a cup of milk for lunch, then recommend a dinner "
        "that fits what's left."
    ),
    "steps": ["log", "recommend"],
}


def test_composite_person_recipe_feeds_recommend_coverage(tmp_path: Path) -> None:
    from nutrienv.bench.pipeline.freezer import freeze_tasks
    from nutrienv.bench.quality_gates import recommend_coverage
    from nutrienv.bench.split import load_split

    result = _run(
        tmp_path,
        [_COMPOSITE],
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"composite": 1},
        family_recipes={"composite": {"person": "roster-cam"}},
    )
    assert len(result.accepted) == 1, [
        (r.reason, r.family) for r in result.rejected
    ]
    (task,) = result.accepted
    child_profile = task.oracle.sub_oracles[1].profile
    assert child_profile.allergies == ("egg",)
    report = recommend_coverage([task], personas=("cut",))
    assert report.missing_personas == ()
    assert "egg" not in report.missing_allergens
    _, target = freeze_tasks(
        [task], catalog=task.s0.catalog, output_path=tmp_path / "comp.json"
    )
    (loaded,) = load_split(target, catalog=task.s0.catalog)
    assert validate_draft(loaded) == []
    assert loaded.oracle.sub_oracles[1].profile.allergies == ("egg",)


def test_person_allergen_clash_is_rejected_visibly(tmp_path: Path) -> None:
    """N-1/N-2: a chosen person never gets a plate carrying their allergen --
    the candidate is rejected, not accepted with the allergy stripped."""
    milk_plate = {
        "items": [{"food": "milk_whole", "expression": "a cup"}],
        "query": "Evaluate this as my plan: a cup of milk.",
    }
    for family, payload in (
        ("composite", {**_COMPOSITE}),
        ("evaluate", milk_plate),
    ):
        result = _run(
            tmp_path,
            [payload],
            judge=_ok_judge,
            catalog=_nutrient_catalog(),
            family_quotas={family: 1},
            family_recipes={family: {"person": "roster-fay"}},
            output_path=tmp_path / f"{family}-clash.json",
        )
        assert result.accepted == [], (family, result.accepted)
        assert [(r.reason, r.family) for r in result.rejected] == [
            ("allergen_clash", family)
        ]


def test_sample_pools_with_allergen_targets_carrier_pools() -> None:
    from nutrienv.bench.pipeline.sampler import sample_pools
    from nutrienv.world.catalog_store import load_catalog

    catalog = load_catalog("data/fdc/catalog-v2.sqlite")
    pools = sample_pools(
        catalog,
        seed=20260822,
        family="evaluate",
        n_pools=4,
        with_allergen="egg",
    )
    assert len(pools) == 4
    for pool in pools:
        assert any(
            "egg" in pool_food.allergen_tags for pool_food in pool.foods
        ), [food.food_id for food in pool.foods]

    with pytest.raises(ValueError, match="allergen tag"):
        sample_pools(
            catalog,
            seed=1,
            family="evaluate",
            n_pools=1,
            with_allergen="nonexistent_tag",
        )


def test_pool_allergen_recipe_reaches_the_sampler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recipe wiring is real: sample_pools receives with_allergen for the
    recipe's family (deleting the _build_jobs wiring fails this test). The
    honest run residual is documented in reports/impl-pool-allergen.md."""
    import sys

    run_batch_module = sys.modules["nutrienv.bench.pipeline.run_batch"]

    seen: dict[str, str | None] = {}
    real = run_batch_module.sample_pools

    def spy(catalog, *, seed, family, n_pools, **kwargs):
        seen[family] = kwargs.get("with_allergen")
        return real(catalog, seed=seed, family=family, n_pools=n_pools, **kwargs)

    monkeypatch.setattr(run_batch_module, "sample_pools", spy)

    result = _run(
        tmp_path,
        None,
        expander=synthetic_expander,
        judge=_ok_judge,
        catalog=_nutrient_catalog(),
        family_quotas={"evaluate": 2},
        family_recipes={
            "evaluate": {
                "knife": "allergy",
                "person": "roster-cam",
                "pool_allergen": "egg",
                "items": "1",
                "tier": "single",
            },
        },
    )
    assert seen == {"evaluate": "egg"}
    # Sampler-level guarantee holds on the drawn pools too: every acceptance
    # (if any) is an allergy reject over the person's profile; rejections are
    # the documented residual (allergen_clash / fit-gate unresolvable).
    assert result.accepted == [] or all(
        task.oracle.last_verdict == "reject"
        and "allergy" in task.oracle.last_reasons
        and task.s0.profile.allergies == ("egg",)
        for task in result.accepted
    )
    assert {r.reason for r in result.rejected} <= {"unresolvable", "allergen_clash"}


def test_pool_allergen_input_is_normalized() -> None:
    from nutrienv.bench.pipeline.sampler import sample_pools
    from nutrienv.world.catalog_store import load_catalog

    catalog = load_catalog("data/fdc/catalog-v2.sqlite")
    pools = sample_pools(
        catalog,
        seed=1,
        family="evaluate",
        n_pools=1,
        with_allergen="Egg",
    )
    (pool,) = pools
    assert any("egg" in food.allergen_tags for food in pool.foods)
