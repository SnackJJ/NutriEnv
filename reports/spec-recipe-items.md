# Spec: recipe channel — evaluate items count + amount path knobs (issue 15 基础通道)

**Status:** decided by coordinator (base transport for tier/unfit bulk production; independent of
the issue-15 design rulings — it merely lets a recipe say "this evaluate should be a 3-food plate"
and "speak grams explicitly", which the tier draft needs for triple/explicit_grams).

## Problem

Recipe channel today accepts `evaluate:knife` and `evaluate:tier` only. `tier=triple` cannot
produce a 3-food plate because `synthetic_expander` composes only 1–2 pool foods and the recipe is
stamped onto the Candidate AFTER the expander ran (run_batch._expand_one:606-613). `explicit_grams`
similarly has no way to request "speak the grams" from the expander. Tier content production is
blocked on these two knobs (tier-mapping-draft: single=1/pair=2/triple=3 foods;
explicit_grams=grams-speech).

## Change

1. `expander` protocol gains an optional recipe hint. Simplest: `synthetic_expander(pool, *,
   persona, family, items: int | None = None, amount_path: str | None = None)`; when `items` is
   set, compose exactly that many pool foods (fail-closed: fewer available → the empty payload
   path); when `amount_path == "explicit_grams"`, the phrase uses the food's grams ("150 g of X")
   instead of the table phrase. Default None → today's 1-2 food table-phrase behavior.
2. `run_batch._expand_one`: pass the family recipe's `items`/`amount_path` (validated strings
   converted to int) into the expander call alongside persona/family. The recipe still stamps
   remaining knobs onto the Candidate as today.
3. `_RECIPE_KEYS["evaluate"]` grows `{"knife", "tier", "items", "amount_path"}`; parsing validates
   `items` as a positive int string ("3" ok, "0"/"abc" rejected) and `amount_path` against a small
   allowed set (`{"explicit_grams", "named_measure", "table_phrase"}` or whatever AMOUNT_PATHS
   style the expander supports — choose the minimal coherent set and document).
4. `scripts/generate_batch.py` `--recipe evaluate:items=3` passes through unchanged (generic
   FAMILY:KEY=VALUE parsing already handles new keys; verify).
5. Tests: `evaluate:items=3` on a synthetic pool with ≥3 speakable foods → the resolved Task has
   3 foods in `evaluated_plan` and validate_draft == []; `evaluate:amount_path=explicit_grams` →
   the query speaks gram amounts ("… g of …"); a pool with <3 speakable foods → clean rejection
   (not a 2-food triple); `items=0`/`items=abc` rejected at parse. Keep existing tests green.

## Definition of done

1. Tests pass; full suite 0 failed (expect 1314+).
2. A recipe run shows tier=triple + items=3 producing a genuine 3-food evaluate item that
   round-trips freeze→load with tier preserved.
3. Commit "pipeline: " prefix. Append evidence to reports/tier-mapping-draft.md (the items channel
   now exists) and reports/impl-recipe-channel.md.
4. Do NOT touch: docs/adr/*, data/splits/*, *.sqlite, scorer.py, validator.py, review_harness.py,
   quality_gates.py.

Work autonomously. If the expander cleanup turns out wider than expected, scope the items/amount
transport to the synthetic expander only (LLM expander prompt shells are issue-15 design) and
document that boundary.
## Review (claude opus)

**Verdict: REV.** The knobs themselves work: `items=3` yields a genuine 3-food
plate that round-trips freeze→load with `tier=triple` preserved, and
`explicit_grams` speech is gram-exact against `evaluated_plan`. Two blockers,
though: this commit silently reverts an accepted fix from `333ab82`, and the
new knobs are silently discarded on the production expander — so
`--recipe evaluate:items=3` does nothing on a real (non-`--synthetic`) run
while the CLI advertises it.

### Axis results

| Axis | Result |
|---|---|
| 1 Correctness | `items=3` → 3-food `last_plan`, `validate_draft == []` ✓; `explicit_grams` query gram-exact vs plan ✓; `<N` speakable → clean `("schema","evaluate")` rejection, no mislabeled short plate ✓; `items=0/abc/-1` rejected at parse ✓. Two fail-open paths: F-2, F-4. |
| 2 Scope / defaults | Empty recipe byte-identical ✓; `recommend` rejects `items`/`amount_path` ✓; `LlmExpander.__call__` signature untouched ✓. **Scope creep: F-1**, an unrelated revert. |
| 3 Test quality | Assert real behavior — food count, gram speech, freeze→load — not plumbing ✓. F-6 nit; nothing covers F-2's silent-drop path. |
| 4 tier synergy | `tier=triple + items=3` → 3-food evaluate item, freeze→`load_split` with tier intact ✓. The tier-mapping draft's main ask is met. |

### Findings

- **F-1 (High) — this commit silently reverts the accepted R-1 fix**
  (`src/nutrienv/bench/pipeline/run_batch.py:419`). `333ab82` ("tier is
  evaluate-only in recipe keys (R-1)") changed `"recommend"` from
  `{"occasion","tier"}` to `{"occasion"}` and added the comment "tier is
  evaluate-only authoring data (mirrors generate_one's guard); recommend can
  only carry an occasion override." This commit restores `tier` to the
  recommend set **and deletes that comment**, with no mention in the commit
  message or the spec. Probe: `family_recipes={"recommend": {"tier": "pair"}}`
  → accepted, `family=recommend tier='pair'`, `validate_draft == []`. That is
  R-1 verbatim, and `generate_one.py:173` still refuses the same input, so mill
  and batch disagree again. The impact is the same as R-1 (inert authoring
  metadata; `evaluate_tier_coverage` filters on `family == "evaluate"`), but
  reverting reviewed-and-closed work without flagging it is the blocker, not
  the blast radius.
  **Fix:** restore `"recommend": frozenset({"occasion"})` and its comment.

- **F-2 (High) — `items`/`amount_path` are silently discarded on every
  non-synthetic expander, including the production one**
  (`src/nutrienv/bench/pipeline/run_batch.py:633-636`). The guard reads
  `if hints and expander is not synthetic_expander: hints = {}`. It exists for
  a good reason — `Expander.__call__` (`types.py:119`) and
  `LlmExpander.__call__` (`expander.py:582`) accept only
  `(pool, *, persona, family)`, so forwarding hints would `TypeError` — but
  discarding them is fail-open. `scripts/generate_batch.py:262` uses
  `make_llm_expander` unless `--synthetic` is passed, so on a real run
  `--recipe evaluate:items=3` is accepted by the parser, advertised by
  `RECIPE_KEYS`, and then does nothing. Probe with a non-synthetic expander:

  ```
  items=3 -> ACCEPTED but items IGNORED: n_foods=2 (requested 3)
  ```

  This is the silent-no-op class the project already ruled against: the
  `evaluate.occasion` knob (NEW-2) was **removed** rather than left inert, and
  `_RECIPE_KEYS`'s own docstring says "A key outside the family's set would be
  silently dropped or ignored by the realize branch, so the parser refuses it."
  It also defeats the commit's stated purpose — bulk tier production — on the
  only path that produces real batches. The spec's licence to "scope the
  transport to the synthetic expander only and document that boundary" is
  satisfied by refusing at the boundary, not by crossing it quietly.
  **Fix:** raise instead of blanking — `raise ValueError("recipe items/amount_path require the synthetic expander")` at `:633`.

- **F-3 (Medium) — two of the three accepted `amount_path` values are no-ops**
  (`src/nutrienv/bench/pipeline/run_batch.py:427`). `_RECIPE_AMOUNT_PATHS`
  admits `named_measure` and `unspecified`, and the comment directly above it
  concedes they change nothing ("Only `explicit_grams` changes synthetic
  speech"). Probe: both produce a task **equal** to the no-recipe run. Same
  fail-open class as F-2, and the spec asked for "the minimal coherent set" —
  which is one value.
  **Fix:** `_RECIPE_AMOUNT_PATHS = frozenset({"explicit_grams"})`.

- **F-4 (Low, latent) — `explicit_grams` falls back to the table phrase per
  food** (`src/nutrienv/bench/pipeline/expander.py:167-179`). `_phrase_for`
  returns `_preferred_phrase(food)` when a food has no `quantity == 1.0`
  alternative, so a plate could mix "50 g of eggs" with "a cup of rice" while
  the recipe asked for gram speech — and be frozen as a
  `tier=explicit_grams` item that only partly speaks grams. The docstring
  promises gram speech with no mention of a fallback, and it sits directly
  beside `items`, which is deliberately fail-closed. Currently unreachable:
  of 5394 speakable pool foods in the real catalog, **0** lack a unit portion,
  so the branch never fires today. Flagged because a fixture or catalog change
  would expose it silently.
  **Fix:** `return None` in `_phrase_for` when `explicit_grams` finds no unit
  portion, so the food is skipped and the plate fails closed like `items`.

- **F-5 (Low) — parameter shadowing in `synthetic_expander`**
  (`src/nutrienv/bench/pipeline/expander.py:152` vs `:212`). The `items: int |
  None` parameter is rebound to the payload list at `:212`. Correct as written
  — every read of the parameter (`limit = items if items else 2`, the shortfall
  check) precedes the rebind — but it is a trap for the next edit, in a
  function where the two meanings are one letter apart.
  **Fix:** rename the payload list to `payload_items`.

- **F-6 (Low) — bare `pytest.raises(ValueError)` in the validation test**
  (`tests/test_run_batch.py:770-786`). Every other validation test in this file
  pins the message with `match=`. Without it, `items="-1"` would still pass if
  it started raising for an unrelated reason.
  **Fix:** add `match=` per case.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py tests/test_expander.py -q
73 passed in 0.72s

$ .venv/bin/python -m pytest -q
1318 passed in 48.15s          # 0 failed
```

```
[items=3 + tier=triple]  n_foods=3  tier='triple'
   "Evaluate this as my plan: a piece of eggs, and a tablespoon of olive oil,
    and a piece of tofu."                       freeze->load: tier preserved, 3 foods
[amount_path=explicit_grams]
   "Evaluate this as my plan: 50 g of eggs, and 13.5 g of olive oil."
   plan=[('egg',50.0),('olive_oil',13.5)]  all_grams_spoken=True
[amount_path=named_measure]  accepted; identical_to_no_recipe=True      <- F-3
[amount_path=unspecified]    accepted; identical_to_no_recipe=True      <- F-3
[recommend:tier=pair]        ACCEPTED family=recommend tier='pair'      <- F-1
[items=3, non-synthetic]     ACCEPTED but items IGNORED: n_foods=2      <- F-2
[recommend:items / amount_path]  rejected: "not supported for 'recommend'"
```

Commit scope: `8760775` touches `reports/impl-recipe-channel.md`,
`reports/tier-mapping-draft.md`, `scripts/generate_batch.py`,
`src/nutrienv/bench/pipeline/expander.py`,
`src/nutrienv/bench/pipeline/run_batch.py`, `tests/test_run_batch.py`. No ADR,
`data/splits/*`, `*.sqlite`, `scorer.py`, `validator.py`, `review_harness.py`,
or `quality_gates.py` change — the spec's do-not-touch list is respected.
`Pass ⇔ end state == Oracle` unaffected.

**Blockers: F-1 and F-2.** F-3 should land with them (same one-line class).
F-4/F-5/F-6 are follow-ups. The transport itself is sound — with F-1 reverted
back and F-2 made fail-closed, this is releasable.

## Fix round (claude opus findings)

- **F-1 (High)** — restored `"recommend": frozenset({"occasion"})` and the
  "tier is evaluate-only" comment in `_RECIPE_KEYS` (R-1 revert undone).
  Regression: `test_recommend_tier_recipe_stays_refused`.
- **F-2 (High)** — `_expand_one` now RAISES
  ("recipe items/amount_path require the synthetic expander (--synthetic)…")
  when those hints reach a non-synthetic expander instead of blanking them;
  knife/tier recipes keep working everywhere.
  Regression: `test_items_and_amount_path_hints_require_the_synthetic_expander`.
  (Typo fixed in final text: "expander".)
- **F-3 (Medium)** — `_RECIPE_AMOUNT_PATHS = {"explicit_grams"}`; the no-op
  values are refused. Covered with `match=` cases named_measure/unspecified.
- **F-4 (Low)** — `_phrase_for` returns None under explicit_grams when a food
  has no one-portion table value, so it is skipped (fail-closed like items)
  rather than mixing table phrases into gram speech.
- **F-5 (Low)** — the payload list in `synthetic_expander` renamed to
  `payload_items`; the `items` recipe-hint parameter is no longer shadowed.
- **F-6 (Low)** — validation test pins per-case messages via `match=`
  (items: "must be a positive integer"; amount_path: "must be one of").

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1320 passed in 55.28s        # 0 failed (was 1318; +2 tests)
```
