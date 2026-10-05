"""Agent-authored interpretations are grounded, separately reviewed and never NLP-parsed."""

import copy
from pathlib import Path

import pytest

from nutrienv.bench.pipeline import generate_one
from nutrienv.bench.pipeline.generate_one import review_packet
from nutrienv.world.catalog_fixture import demo_catalog


@pytest.fixture
def draft():
    return {
        "author_id": "writer-agent",
        "item": {
            "id": "agent-log", "family": "log", "query": "Can you log a piece of banana for lunch?",
            "s0": {"plan_scope": "day", "ledger": [], "profile": {
                "user_id": "ada", "sex": "female", "age_y": 34, "height_cm": 165,
                "weight_kg": 62, "activity": "light", "phase": "maintain",
            }},
            "oracle": {"profile": "s0", "ledger": "s0_plus_tail", "ledger_tail": [
                {"food_id": "banana", "portion": {"key": "piece", "count": 1},
                 "eaten_at": "today-lunch"},
            ]},
        },
    }


def approval(request):
    return {"reviewer_id": "reviewer-agent", "draft_sha256": request["draft_sha256"],
            "verdict": "approve", "findings": []}


def test_writer_and_reviewer_control_semantics_without_parser(draft, monkeypatch):
    import importlib

    def forbidden(*args, **kwargs):
        raise AssertionError("NLP parser may not author or backresolve a task")

    for name in ("nutrienv.world.portions", "nutrienv.bench.realize",
                 "nutrienv.bench.pipeline.resolver", "nutrienv.bench.pipeline.legacy_generate_one"):
        monkeypatch.setattr(importlib.import_module(name), "resolve_portion", forbidden)
    seen = []

    def reviewer(request):
        seen.append(request)
        return approval(request)

    result = generate_one(catalog=demo_catalog(), author=lambda: draft, reviewer=reviewer)
    assert result.accepted is not None
    assert result.accepted.query == draft["item"]["query"]
    assert result.accepted.oracle.ledger is not None
    assert result.accepted.oracle.ledger[-1].grams == 118
    assert seen[0]["catalog_foods"]["banana"]["portions"]["piece"] == 118
    assert "food identity" in seen[0]["review_contract"]
    assert "grams" not in draft["item"]["oracle"]["ledger_tail"][0]


def test_semantic_mismatch_is_rejected_by_separate_reviewer(draft):
    draft["item"]["query"] = "I had a chicken breast for lunch."

    def reviewer(request):
        return {**approval(request), "verdict": "revise",
                "findings": ["The declared banana is not the chicken breast in the question."]}

    result = generate_one(catalog=demo_catalog(), author=lambda: draft, reviewer=reviewer)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "semantic_review"


@pytest.mark.parametrize("evidence", [
    {"key": "missing", "count": 1}, {"key": "piece", "count": True},
    {"key": "piece", "count": -1}, {"key": "piece", "count": float("nan")},
    {"grams": 0}, {"phrase": "a banana"},
])
def test_missing_or_invalid_evidence_never_falls_back(draft, evidence):
    draft["item"]["oracle"]["ledger_tail"][0]["portion"] = evidence
    with pytest.raises((ValueError, TypeError)):
        generate_one(catalog=demo_catalog(), author=lambda: draft, reviewer=approval)


def test_explicit_measured_grams_need_no_phrase_grammar(draft):
    draft["item"]["query"] = "I weighed out 99 grams of banana at lunch; please log it."
    draft["item"]["oracle"]["ledger_tail"][0]["portion"] = {"grams": 99}
    result = generate_one(catalog=demo_catalog(), author=lambda: draft, reviewer=approval)
    assert result.accepted is not None
    assert result.accepted.oracle.ledger is not None
    assert result.accepted.oracle.ledger[-1].grams == 99


@pytest.mark.parametrize("change", ["same_reviewer", "stale_hash", "approval_with_findings"])
def test_review_identity_and_exact_binding_are_required(draft, change):
    def reviewer(request):
        response = approval(request)
        if change == "same_reviewer":
            response["reviewer_id"] = draft["author_id"]
        elif change == "stale_hash":
            response["draft_sha256"] = "0" * 64
        else:
            response["findings"] = ["Unresolved portion ambiguity."]
        return response

    with pytest.raises(ValueError):
        generate_one(catalog=demo_catalog(), author=lambda: draft, reviewer=reviewer)


def test_review_hash_covers_nutrients_and_allergens(draft):
    catalog = demo_catalog()
    _, first = review_packet(draft, catalog)
    modified = copy.deepcopy(catalog)
    modified["banana"]["nutrients"]["protein_g"] += 1
    _, second = review_packet(draft, modified)
    assert first["draft_sha256"] != second["draft_sha256"]
    modified = copy.deepcopy(catalog)
    modified["banana"]["allergen_tags"] = ["soy"]
    _, third = review_packet(draft, modified)
    assert first["draft_sha256"] != third["draft_sha256"]


def test_agent_packet_cannot_supply_hidden_precomputed_windows(draft):
    draft["item"]["s0"]["profile"]["windows"] = {"kcal": [1, 10000]}
    with pytest.raises(ValueError, match="body facts"):
        review_packet(draft, demo_catalog())


def test_active_cli_requires_structured_draft_and_independent_review(draft, tmp_path):
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts/generate_one_cli.py"
    spec = importlib.util.spec_from_file_location("agent_author_cli", path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.__doc__ is not None and "--prepare-review" in cli.__doc__
    # Invalid agent JSON fails with its source path, not a generated fixture.
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(ValueError, match="bad.json"):
        cli.main(["--draft", str(bad), "--prepare-review"])
    with pytest.raises(SystemExit):
        cli.main(["--synthetic"])


def test_agent_provides_a_legal_meal_witness_not_a_code_generated_plate(draft):
    draft["item"]["family"] = "recommend"
    draft["item"]["query"] = "What high-protein snack should I eat?"
    draft["item"]["s0"]["plan_scope"] = "snack"
    draft["item"]["oracle"] = {
        "profile": "s0", "ledger": "s0", "last_plan": [],
        "plan_must_fit_windows": True, "plan_high_protein": True,
        "plan_occasion": "snack", "budget_basis": "ledger",
    }
    draft["witnesses"] = [{"actions": [{"op": "submit_plan", "items": [
        {"food_id": "chicken_breast", "portion": {"grams": 100}},
    ]}]}]
    result = generate_one(catalog=demo_catalog(), author=lambda: draft, reviewer=approval)
    assert result.accepted is not None
    assert result.accepted.oracle.last_plan == []
    draft["witnesses"][0]["actions"][0]["items"][0]["portion"] = {"grams": 600}
    with pytest.raises(ValueError, match="illegal witness action"):
        review_packet(draft, demo_catalog())


def test_cli_prepares_then_admits_only_the_exact_separate_review(draft, tmp_path):
    import importlib.util
    import json

    path = Path(__file__).resolve().parents[1] / "scripts/generate_one_cli.py"
    spec = importlib.util.spec_from_file_location("agent_author_cli_roundtrip", path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    source = tmp_path / "draft.json"
    request = tmp_path / "request.json"
    review = tmp_path / "review.json"
    output = tmp_path / "admitted.json"
    source.write_text(json.dumps(draft))
    assert cli.main(["--draft", str(source), "--prepare-review", "--output", str(request)]) == 0
    review.write_text(json.dumps(approval(json.loads(request.read_text()))))
    assert cli.main(["--draft", str(source), "--review", str(review), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "accepted"
    draft["item"]["query"] = "A different unreviewed question."
    source.write_text(json.dumps(draft))
    with pytest.raises(ValueError, match="exact draft"):
        cli.main(["--draft", str(source), "--review", str(review)])
