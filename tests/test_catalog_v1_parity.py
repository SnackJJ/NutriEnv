"""S3 seam: independent full-FNDDS verifier vs builder on a synthetic fixture.

The verifier is written from the dry-run POLICY (sort, first-wins, compound
piece/slice, QNS, oz-not-package). It does not import builder internals.
A deliberately last-wins verifier must disagree, so a broken first-wins
order cannot silently pass the parity test.
"""

from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_fdc_catalog as builder  # noqa: E402

# Mini food_portion.csv covering every POLICY branch the seam must lock.
# File order is *not* seq_num order: food 100 lists medium (seq 2) before
# small (seq 1) so zip-order first-wins would pick piece=200, not 165.
_FIXTURE_CSV = """\
fdc_id,id,seq_num,portion_description,modifier,gram_weight
100,20,2,1 medium,,200
100,10,1,1 small,,165
200,30,1,"1 piece/slice, any size",,30
300,40,1,Quantity not specified,90000,50
400,50,1,1 oz,,28.35
500,60,1,1 cup,,0
500,61,2,1 tablespoon,,15
600,70,2,"1 cup, diced",,132
600,71,1,"1 cup, shredded",,113
700,80,1,1 5.3 oz container,,150
"""

_QNS_MODIFIER = "90000"
_HOUSEHOLD = (
    (re.compile(r"\bcups?\b"), "cup"),
    (re.compile(r"\btablespoons?\b|\btbsp\b"), "tbsp"),
    (re.compile(r"\bteaspoons?\b|\btsp\b"), "tsp"),
    (re.compile(r"\bslices?\b"), "slice"),
    (re.compile(r"\bpieces?\b|\beach\b"), "piece"),
    (re.compile(r"\bcans?\b"), "can"),
)
_SIZE_WORDS = re.compile(r"\bbanana\b|\begg\b|\bmedium\b|\blarge\b|\bsmall\b")
_PIECE = re.compile(r"\bpieces?\b")
_SLICE = re.compile(r"\bslices?\b")


def _fixture_rows() -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(_FIXTURE_CSV)))


def _policy_keys(description: str, modifier: str) -> list[str]:
    """Map one row to catalog keys from the published dry-run POLICY."""
    desc = (description or "").strip()
    desc_l = desc.lower()
    joined = f"{desc} {modifier or ''}".strip().lower()
    if modifier == _QNS_MODIFIER or desc_l.startswith("quantity not"):
        return ["qns"]
    if not joined or "guideline" in joined:
        return []
    if "mashed" in joined:
        return []
    if "sliced" in joined and "cup" in joined:
        return []

    out: list[str] = []
    if _PIECE.search(joined) and _SLICE.search(joined):
        out = ["piece", "slice"]
    else:
        for pattern, key in _HOUSEHOLD:
            if pattern.search(joined):
                out = [key]
                break
    if out:
        return out
    if _SIZE_WORDS.search(joined):
        return ["piece"]
    if re.search(r"\bthick\b", joined):
        return ["thick"]
    if re.search(r"\bthin\b", joined):
        return ["thin"]
    if re.search(r"\bregular\b", joined):
        return ["regular"]
    if re.search(r"\bcubic inch(?:es)?\b", joined):
        return ["cubic_inch"]
    if re.search(r"\bfl\.?\s*oz\b", joined):
        return ["fl_oz"]
    if re.search(r"\boz\b", joined) and not re.search(
        r"\boz\s+(?:container|bag|bottle|package|cup)\b", joined
    ):
        return ["oz"]
    if re.search(r"\b(?:single\s+)?servings?\b", joined):
        return ["serving"]
    return []


def _sort_tuple(row: dict[str, str]) -> tuple[str, int, int]:
    try:
        seq = int(row.get("seq_num") or 0)
    except ValueError:
        seq = 0
    try:
        pid = int(row.get("id") or 0)
    except ValueError:
        pid = 0
    return (row.get("fdc_id") or "", seq, pid)


def verify_full_fndds_policy(
    rows: Iterable[dict[str, str]], *, last_wins: bool = False
) -> dict[str, dict[str, float]]:
    """Independent POLICY scan. last_wins=True is the deliberate mismatch."""
    ordered = sorted(rows, key=_sort_tuple)
    portions: dict[str, dict[str, float]] = {}
    for row in ordered:
        try:
            grams = float(row.get("gram_weight") or "")
        except ValueError:
            continue
        if grams <= 0:
            continue
        keys = _policy_keys(
            row.get("portion_description") or "", row.get("modifier") or ""
        )
        if not keys:
            continue
        bucket = portions.setdefault(row.get("fdc_id") or "", {})
        for key in keys:
            if last_wins or key not in bucket:
                bucket[key] = round(grams, 2)
    return portions


def test_builder_full_scan_matches_independent_verifier() -> None:
    rows = _fixture_rows()
    built = builder.collect_portions_full(rows)
    verified = verify_full_fndds_policy(rows)
    assert built == verified
    assert built["100"] == {"piece": 165.0}
    assert built["200"] == {"piece": 30.0, "slice": 30.0}
    assert built["300"] == {"qns": 50.0}
    assert built["400"] == {"oz": 28.35}
    assert built["500"] == {"tbsp": 15.0}
    assert built["600"] == {"cup": 113.0}
    assert "700" not in built


def test_deliberately_wrong_first_wins_order_disagrees() -> None:
    rows = _fixture_rows()
    built = builder.collect_portions_full(rows)
    wrong = verify_full_fndds_policy(rows, last_wins=True)
    assert built != wrong
    assert wrong["100"]["piece"] == 200.0
    assert wrong["600"]["cup"] == 132.0
    # If the parity test used this verifier as the expected value, it would fail.
    assert built != verify_full_fndds_policy(rows, last_wins=True)
