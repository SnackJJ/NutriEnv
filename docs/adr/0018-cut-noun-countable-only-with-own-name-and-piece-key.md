# 0018 — Cut noun is a countable only when the food's own name carries the cut and a piece row exists

**Status:** accepted

**Context.** Before catalog-v2, `resolve_portion` returned `None` for every bare
cut noun ("a chicken breast", "two drumsticks"). It could not distinguish a
cut the food *is* (chicken breast, piece = 105 g) from a cut the food merely
*pairs with* (a breast of a roast chicken has no portion key). Ticket 02 kept
the safer rule: every cut noun stays `None`.

**Decision.** Resolve a bare cut noun (breast / thigh / wing / drumstick /
chop / loin / rib / fillet / shank / brisket / cutlet) as `portions.piece`
units **only when both hold**:

1. the food's own name contains that cut noun, and
2. the food's portions table carries a `piece` row.

Otherwise it stays `None` (fail-closed; never cup/QNS).

**Evidence.** `a chicken breast` → 105 g and `two chicken breasts` → 210 g now
resolve because the pinned staple `2705956` "Chicken breast, baked, broiled,
or roasted, skin not eaten, from raw" has `piece = 105` from FNDDS row
`1 small breast`. `two chicken wings` → 70 g comes from the catalog-v2 `wing`
key, not this rule. A food whose name does not carry the cut still refuses.

**Authorisation trail.** catalog-v2 codex R2 flagged the earlier None→105 g
change as scope creep; the Opus adjudication (reports/catalog-v2-adjudication.md
§6.1) recorded it but did not approve it. That gap is closed here: the rule
plus the handbook symmetry line in react.py `_SYSTEM_V1_TAIL` are both already
landed and pinned by tests (test_cut_noun_reads_piece_when_food_name_matches,
test_bare_noun_handbook_covers_new_expressions). This ADR is the formal
authorisation that ticket 02 验收 3 ("a chicken breast stays None") was
deliberately superseded by the catalog-v2 staple re-pin.

**Consequences.** The judged ruler still derives grams from FNDDS PortionFact
(105 g) only. Frozen splits are untouched; catalog-v1 foods without `piece`
or without the cut in their name keep returning `None`.
