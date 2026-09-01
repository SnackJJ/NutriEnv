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

## Re-review (claude opus)

**Verdict: ACC.** All six findings resolved, each verified by probe rather than
by diff reading. The two blockers are properly closed: the R-1 revert is undone
*and* pinned by a named regression test, and the expander hints now raise
instead of vanishing — on both the serial and threaded paths. I also re-swept
every previously-closed recipe-channel finding; none regressed.

### Finding status

| # | Finding | Status | Evidence |
|---|---|---|---|
| F-1 | High — silent revert of the accepted R-1 fix | **Resolved** | `run_batch.py:418` back to `frozenset({"occasion"})` with the 333ab82 comment restored. Probe: `_RECIPE_KEYS["recommend"] == {"occasion"}`; `recommend:tier=pair` → `recipe key 'tier' is not supported for 'recommend' (allowed: ['occasion'])`; `recommend:occasion=dinner` still accepted. Now pinned by `test_recommend_tier_recipe_stays_refused` (`:795`) — the guard that was missing when this regressed. |
| F-2 | High — hints silently discarded on non-synthetic expanders | **Resolved** | `run_batch.py:630-637` raises instead of blanking. Probed at **workers=1 and workers=4**: both raise `recipe items/amount_path require the synthetic expander (--synthetic); the LLM expander cannot honour them yet` — `future.result()` re-raises, so the threaded path fails closed too. No collateral: `knife`+`tier` recipes still work on a non-synthetic expander (accepted, `tier='single'`). Synthetic path intact: `items=3 + tier=triple` → 3-food plate, `validate_draft == []`, freeze→load preserves 3 foods and the tier. Pinned by `test_items_and_amount_path_hints_require_the_synthetic_expander` (`:812`). |
| F-3 | Medium — two accepted `amount_path` no-ops | **Resolved** | `run_batch.py:426` is now `frozenset({"explicit_grams"})`, and the comment says so ("there are no accepted no-op values"). Probes: `named_measure`, `unspecified`, `bogus` all → `amount_path must be one of ['explicit_grams']`; `explicit_grams` still produces `"Evaluate this as my plan: 50 g of eggs, and 13.5 g of olive oil."` |
| F-4 | Low — `explicit_grams` fell back to the table phrase | **Resolved** | `expander.py:179` → `return None if one is None else f"{one:g} g"`, commented as fail-closed "like items". Because the branch is unreachable on the real catalog, I exercised it directly: took a real pool food, stripped its `quantity == 1.0` alternatives (leaving qty 0.5/1.5/2.0, still speakable — `_preferred_phrase` returns "half a cup"), and ran both paths. Default → `half a cup of Milk`; `explicit_grams` → `{"items": [], "query": ""}`. Fail-closed confirmed, default path untouched. |
| F-5 | Low — parameter shadowing | **Resolved** | Payload list renamed `payload_items` (`expander.py:215`) with a comment naming the reason; all five return sites updated (`:225`, `:232`, `:240`, `:270`). No `items = [` rebinding remains. Behaviour unchanged — probe outputs byte-identical to the pre-fix run. |
| F-6 | Low — bare `pytest.raises(ValueError)` | **Resolved** | `tests/test_run_batch.py:770-790` now drives a `(recipe, message)` table with `match=`, and grew two cases (`named_measure`, `unspecified`) that double as F-3's regression guard. |

### Regression sweep

F-1 was a silent revert, so I re-verified every recipe-channel finding closed in
earlier rounds rather than assuming they held:

```
evaluate:tier=bogus (NEW-1)       rejected: tier must be one of [...]
log:tier=single     (NEW-1b)      rejected: not supported for 'log' (allowed: [])
update:tier=single  (NEW-1b)      rejected: not supported for 'update' (allowed: [])
evaluate:occasion   (NEW-2)       rejected: not supported for 'evaluate'
evaluate:knife=swap (finding 6)   rejected: unsupported evaluate knife 'swap'
recommend:shell     (finding 5)   rejected: not supported for 'recommend'
recommend:scene     (finding 5)   rejected: not supported for 'recommend'
unrequested family                rejected: not among the requested family_quotas
evaluate:tier=None                rejected: must be a non-empty string
knife allergy                     reasons=('allergy','kcal_hi') gram_exact=True tier='single'
empty recipe == no recipe         True
```

All hold. Nothing else in this commit changed behaviour.

### Notes (non-blocking)

- **N-1 — the guard fires per job, not at `run_batch` entry**
  (`run_batch.py:630`). Every job carrying the offending recipe hits the check
  *before* its own `expander(...)` call, so the single-family case wastes
  nothing. But with a mixed quota — say `{"evaluate": 1, "log": 5}` and a recipe
  only on `evaluate` — the recipe-free `log` jobs are already in flight and, on
  a real run, would spend LLM calls before the evaluate job's failure surfaces.
  `run_batch` has both the parsed spec and the expander in hand at `:116`; a
  check there would fail before pool sampling. Cheap improvement, not a defect.
- **N-2 — `scripts/generate_batch.py` still advertises `items`/`amount_path`
  in its flat `RECIPE_KEYS` with no `--synthetic` awareness.** Acceptable as
  is: the library fails closed and the message names `--synthetic`, which is
  the actionable instruction. Noting it only because a CLI-side pre-check would
  fail earlier and cheaper (this is the same fix as N-1).
- **N-3 — the rewritten `_RECIPE_KEYS` comment dropped the clause "whose value
  must be a declared EVALUATE_TIERS entry."** The check itself is intact and
  verified (`evaluate:tier=bogus` → rejected); only the comment is now less
  specific than the code it documents.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py tests/test_expander.py -q
75 passed in 0.70s

$ .venv/bin/python -m pytest -q
1320 passed in 48.57s          # 0 failed
```

Commit scope: `29c9057` touches `reports/spec-recipe-items.md`,
`src/nutrienv/bench/pipeline/expander.py`,
`src/nutrienv/bench/pipeline/run_batch.py`, `tests/test_run_batch.py`. No ADR,
`data/splits/*`, `*.sqlite`, `scorer.py`, `validator.py`, `review_harness.py`,
or `quality_gates.py` change. `Pass ⇔ end state == Oracle` unaffected.

**RELEASE: recipe items/amount_path base transport is released.** N-1/N-2/N-3
are tracked improvements, not release gates.

## N-1/N-2 closed: expander-mismatch guard at run_batch entry + CLI

- **N-1**: `run_batch` raises the shared "recipe items/amount_path require
  the synthetic expander (--synthetic)…" ValueError right after `_parse_spec`
  (before `_build_jobs`/sampling) when any family recipe carries
  items/amount_path and the injected expander is not the synthetic one. The
  per-job guard stays as defence in depth.
  Regression: `test_expander_hint_mismatch_fails_at_entry_before_any_job` —
  mixed quota (evaluate:1 + log:5, recipe only on evaluate, items=3) with a
  counting fake LLM expander: raises with **zero** expander calls.
- **N-2**: `scripts/generate_batch.py` refuses `--recipe FAMILY:items/…`
  without `--synthetic` at CLI time ("--recipe evaluate:items requires
  --synthetic; …"); with `--synthetic` it runs through (verified:
  items=3 + tier=triple accepted, frozen item carries 3 plan foods).

## Review (claude opus) — N-1/N-2

**Verdict: ACC.** Both tracking items are closed, and the N-1 claim is stronger
than the test asserts: the entry guard fires before `_build_jobs` too, so a
mixed-quota real batch spends neither an LLM call nor a sampling pass. One Low
note about the guard message, which is duplicated rather than shared.

### Verification

**1 — `run_batch` entry, mixed quota → zero work done.** Guard at
`run_batch.py:122-132`, placed after `_parse_spec` (it needs the parsed
recipes) and before `build_food_index`/`_build_jobs` at `:140-141`. Probed with
a counting fake non-synthetic expander **and** an instrumented `_build_jobs`,
on the exact mixed shape N-1 named (`{"evaluate": 1, "log": 5}`, recipe only on
`evaluate`):

```
ValueError: recipe items/amount_path require the synthetic expander
            (--synthetic); the LLM expander cannot honour them yet
expander calls=[]   _build_jobs calls=0
```

So no pool is sampled and no recipe-free `log` job reaches the expander — which
was the whole cost N-1 was about. `test_expander_hint_mismatch_fails_at_entry_before_any_job`
(`tests/test_run_batch.py:832`) pins the zero-call half; the zero-sampling half
is a free consequence of the placement and is worth knowing.

**2 — CLI.** Guard at `scripts/generate_batch.py:226-230`, inside the
`--recipe` loop before the recipe is accumulated. Ran the real CLI:

```
--recipe evaluate:items=3                  -> --recipe evaluate:items requires --synthetic;
                                              the LLM expander cannot honour items/amount_path yet
--recipe evaluate:items=3 --synthetic      -> pools=1 candidates=1 accepted=1, wrote 1 item
                                              family=evaluate  n_plan=3  situations=[]
                                              "Evaluate this as my plan: a serving of Chinese pancake,
                                               and a can of Snack, and a tablespoon of Pickle relish."
--recipe evaluate:amount_path=explicit_grams  -> blocked, names --synthetic
--recipe evaluate:items=3 --recipe evaluate:amount_path=explicit_grams -> blocked
--recipe evaluate:tier=pair (no --synthetic)  -> NOT blocked, runs normally
```

Mixed flags behave: `tier`/`knife` are Candidate stamps, not expander hints, so
they are correctly left alone — the guard keys off `{"items","amount_path"}`
only. And the `--synthetic` path is proven end to end, not just at the API: the
frozen split really contains a 3-food evaluate item.

**3 — per-job guard still present.** `run_batch.py:643-649` is untouched. Since
the entry guard now shadows it on every normal path, I reached it directly by
building jobs and calling `_expand_one(job, fake_llm, persona)` — it raises the
same ValueError. Defence in depth is real, not vestigial. Synthetic path
unchanged: `items=3` still yields a 3-food plate with the same query as before
this commit.

**4 — the message is duplicated, not shared.** See N-4 below.

### Regression sweep

Given this channel's history of a silent revert (F-1), I re-ran the full guard
sweep rather than assuming:

```
evaluate:tier=bogus / log:tier / update:tier / evaluate:occasion / knife=swap
recommend:shell / recommend:scene / unrequested family / tier=None   -- all rejected
recommend:tier=pair (F-1)   -> rejected: not supported for 'recommend' (allowed: ['occasion'])
knife allergy               -> reasons=('allergy','kcal_hi') gram_exact=True tier='single'
empty recipe == no recipe   -> True
```

All hold. This commit is purely additive (`+54 lines, -0`).

### Finding

- **N-4 (Low) — the guard message is two identical literals, not one shared
  constant** (`src/nutrienv/bench/pipeline/run_batch.py:130-131` and
  `:647-648`). Verified byte-identical today, so a test matching either works
  and the commit comment ("same message as the per-job defence-in-depth guard")
  is factually true right now. But nothing keeps them in step: editing one —
  say to name a future non-synthetic capability — silently desynchronises the
  entry and per-job paths, and the per-job path is the one no normal run
  reaches, so the drift would go unnoticed.
  **Fix:** hoist to a module constant, e.g.
  `_HINTS_NEED_SYNTHETIC = "recipe items/amount_path require the synthetic expander (--synthetic); the LLM expander cannot honour them yet"`,
  and raise `ValueError(_HINTS_NEED_SYNTHETIC)` from both sites. The CLI
  message at `generate_batch.py:227` is deliberately different (it names the
  offending family and key) and should stay as it is.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
36 passed in 0.27s

$ .venv/bin/python -m pytest -q
1321 passed in 49.27s          # 0 failed
```

Commit scope: `e30b128` touches `reports/spec-recipe-items.md`,
`scripts/generate_batch.py`, `src/nutrienv/bench/pipeline/run_batch.py`,
`tests/test_run_batch.py`. No ADR, `data/splits/*`, `*.sqlite`, `scorer.py`,
`validator.py`, `review_harness.py`, or `quality_gates.py` change.
`Pass ⇔ end state == Oracle` unaffected.

**RELEASE: N-1/N-2 are closed — recipe/expander mismatch now fails at the
`run_batch` entry and at the CLI, before any sampling or LLM call.** N-4 is a
tracked cleanup, not a release gate.
