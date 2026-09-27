"""Gram anchor arrives in generate_one binding: propose, whitelist-veto, fail-closed."""

from __future__ import annotations

from nutrienv.bench.pipeline.generate_one import generate_one
from nutrienv.bench.pipeline.roster import ROSTER


def _food(name, portions, aliases=(), allergen_tags=()):
    return {
        "name": name,
        "portions": portions,
        "aliases": list(aliases),
        "allergen_tags": list(allergen_tags),
    }


def _catalog():
    # two scoops of whey: "scoop" is a named measure that resolve_portion
    # refuses because the food only has qns. The anchor may propose 2×30.
    return {
        "whey": _food(
            "Whey protein, powder",
            {"qns": 30.0},
            ("whey", "protein powder"),
            ("milk",),
        ),
    }


def _expander(pool, *, persona, family, amount_path=None):
    return {
        "query": "Please log two scoops of protein powder for lunch.",
        "foods": ["whey"],
    }


def test_anchor_accepts_whitelisted_proposal_and_binds_grams() -> None:
    def anchor(food_id, expression, query):
        assert food_id == "whey"
        return 60.0  # 2 × qns 30, on the table whitelist

    result = generate_one(
        catalog=_catalog(),
        family="log",
        seed=0,
        person=ROSTER[0],
        amount_path="named_measure",
        expander=_expander,
        gram_anchor=anchor,
    )
    assert result.rejected is None, result.rejected
    assert result.accepted is not None
    assert [row.grams for row in result.accepted.oracle.ledger_tail] == [60.0]


def test_anchor_rejects_off_table_grams_and_fails_closed() -> None:
    def anchor(food_id, expression, query):
        return 99.0

    result = generate_one(
        catalog=_catalog(),
        family="log",
        seed=0,
        person=ROSTER[0],
        amount_path="named_measure",
        expander=_expander,
        gram_anchor=anchor,
    )
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "unresolvable"


def test_anchor_exception_fails_closed_and_keeps_natural_query() -> None:
    def anchor(food_id, expression, query):
        raise RuntimeError("anchor down")

    result = generate_one(
        catalog=_catalog(),
        family="log",
        seed=0,
        person=ROSTER[0],
        amount_path="named_measure",
        expander=_expander,
        gram_anchor=anchor,
    )
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.query == "Please log two scoops of protein powder for lunch."
