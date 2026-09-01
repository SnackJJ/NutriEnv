# Spec: recipe exclude_allergens hint — fit→knife plate construction (unfit bulk base)

**Status:** decided by coordinator. Closes the documented unfit residual: with `pool_allergen`
guaranteeing the carrier is in the pool, the fit→knife construction (ADR 0017) fails because
`synthetic_expander` puts the carrier INTO the plate (first N speakable foods) → immediate
`allergen_clash` instead of fit→knife. An `exclude_allergens` hint lets the plate take ONLY
non-allergenic foods (bind-fit), after which `apply_knife._allergy` steals a pool carrier and the
envelope rejects. Neutral transport — no design rulings involved.

## Mechanism (verified in code)

- `pool_allergen` (5269dd0) guarantees the pool holds a carrier; the swap places it (now at a
  random slot, fdfd2dc).
- `_allergy` (knives.py:255-274) scans `pool.foods` for a carrier NOT in the plate and adds it —
  the plate must first bind-fit (no carrier) so the fit→knife precondition holds.
- Today `items=1` drafts the carrier itself → `allergen_clash` (plate already contains the
  allergen). With `exclude_allergens=<person's tags or a recipe value>`, the plate draws only
  non-carrier foods, fits, then the knife adds the carrier → proper unfit.

## Change

1. `synthetic_expander(pool, *, persona, family, items=None, amount_path=None,
   exclude_allergens: tuple[str, ...] | None = None)`: when composing the plate (evaluate/
   recommend/update non-composite path), skip foods whose catalog allergen_tags intersect the
   excluded set; if that leaves fewer than `items` foods, fail-closed empty payload (same as
   today's shortfall). Default None → today's behavior. Composite path unchanged (owns its plate).
2. `run_batch._RECIPE_KEYS`: add `exclude_allergens` to evaluate/recommend/update (families whose
   plate can be a knife/fit target; `log`/`composite` don't take a plate hint — leave them out or
   accept with a loud no-op guard per the channel's fail-closed habit: prefer loud rejection when
   a family can't honour it). Values: comma/space-separated tag string (normalize via
   normalize_tags, lowercase); parse fail-closed on empty/unknown shape.
3. `generate_batch.py --recipe evaluate:exclude_allergens=egg` passes through (generic).
4. Tests: synthetic batch `evaluate:knife=allergy+person=roster-cam+pool_allergen=egg
   +exclude_allergens=egg+items=1+tier=single` — the plate takes a non-egg food (fit), knife
   steals the egg carrier → an **unfit** item is produced (last_verdict=reject, empty last_plan,
   reasons incl. allergy, validate_draft==[], evaluate_unfits counts). If the fit window still
   rejects some pools (person's cut-dinner window), report the honest acceptance rate; the
   mechanism claim (exclude → non-carrier plate → knife steals carrier) is the hard assertion.
5. Unit: `synthetic_expander(exclude_allergens=('egg',))` on a mixed pool → every drafted food
   lacks egg; shortfall → empty payload.

## Definition of done

1. Tests pass (unfit item produced from the real catalog recipe; sampler-level exclude
   assertions); full suite 0 failed (expect 1335+).
2. Honest probe report: run the unfit recipe over several seeds/persons; report how many pools
   yield unfit (may be <100% due to fit windows — document).
3. Commit "pipeline: " prefix. Append evidence to reports/impl-pool-allergen.md (or a new
   reports/impl-exclude-allergens.md) and issue15-runbook.md (path A now reachable).
4. Do NOT touch: docs/adr/*, data/splits/*, *.sqlite, scorer.py, validator.py, review_harness.py,
   quality_gates.py, generate_one.py.

Work autonomously. If the mechanism still can't produce an unfit on the real catalog (e.g. the
fit-window dependency binds tighter than expected), implement the transport, document the exact
residual with evidence, and stop with a precise report — do not fake a pass.
## Review (claude opus)

**Verdict: REV.** The mechanism is real and I verified it end to end — the
fixture unfit is genuine on every property, and the real-catalog claim holds.
But `exclude_allergens` is advertised on `update`, where the impl report itself
says the family cannot honour it, and it provably does nothing there. Two
further findings: the honest-probe table does not reproduce (and is wrong in a
way that misdirects bulk production), and the commit unconditionally changes
every synthetic evaluate query without saying so.

### Axis results

| Axis | Result |
|---|---|
| 1 Mechanism | **Verified genuine.** The fixture recipe yields: `verdict='reject'`, `last_plan=[]`, `evaluated_plan=[rice 158 g, avocado 150 g, egg 50 g]` with **exactly one** egg carrier added to an otherwise allergen-free plate, `reasons=('allergy','kcal_hi')` **equal to the rebind** of `evaluated_plan` against the oracle's own windows/allergies, `profile.allergies=('egg',)`, `persona='cut'`, `validate_draft == []`, `evaluate_unfits` counts it, and freeze→`load_split` round-trips with `verdict='reject'`, `tier='single'`, `validate_draft == []`. Speech is gram-exact. This is ADR 0017's fit→knife, done properly. |
| 2 Honesty | Direction reproduces, **numbers do not** — see F-2. Confirmed: the mechanism works on catalog-v2 for both cam/egg and kim/soy; the fit-window residual dominates; `allergen_clash == 0` at items ≥ 2 across every sweep I ran. Nothing is overclaimed — the table *under*states the yield — but it is not reproducible as written. |
| 3 Fail-closed | Good, one gap. `''` → "must be a non-empty string"; `'  '` and `','` → "must name at least one allergen tag"; `'EGG, Milk'` accepted (normalization works); `log` and `composite` **loudly rejected** ("not supported for …"). Shortfall below `items` → empty payload, not a partial plate (unit test + verified). The gap is F-4 (`bogus_tag` accepted silently) and the bigger one is F-1 (`update` accepted but inert). |
| 4 Scope | `reports/` ×2, `scripts/generate_batch.py`, `expander.py`, `run_batch.py`, `tests/test_run_batch.py`. No ADR, `data/splits/*`, `*.sqlite`, `scorer.py`, `validator.py`, `review_harness.py`, `quality_gates.py`, or `generate_one.py` ✓. But see F-3: an unrelated behaviour change rides along inside `expander.py`. |

### Findings

- **F-1 (High) — `exclude_allergens` is an accepted no-op on `update`**
  (`src/nutrienv/bench/pipeline/run_batch.py:452`). The update branch of
  `synthetic_expander` (`expander.py:253-268`) re-picks its own carrier
  straight from `pool.foods` (`if food.allergen_tags and _preferred_phrase(...)`)
  and never consults `chosen`, so the exclusion cannot reach it. Measured over
  60 milk-carrier pools, excluding **all six** catalog allergens:

  ```
  evaluate   pools=60  unchanged=37  changed=23     <- exclusion works
  recommend  pools=60  unchanged=37  changed=23     <- exclusion works
  update     pools=60  unchanged=60  changed=0      <- exclusion inert
  update drafts that STILL name an excluded-allergen food: 41
  ```

  `reports/impl-exclude-allergens.md` states the cause plainly ("the update
  family's carrier pick is deliberately independent (its semantics REQUIRE the
  allergen food)"), so the inertness is known — yet the key is still
  advertised for that family. The same commit correctly *withholds* it from
  `composite` "per the fail-closed habit" (`run_batch.py:453`), which makes the
  two decisions inconsistent with each other. This channel has removed or
  hard-failed an inert knob four times now (`evaluate.occasion`,
  `items`/`amount_path` on non-synthetic expanders, `log:person`,
  `log:tier`); update should follow the same rule.
  **Fix:** `"update": frozenset({"person", "pool_allergen"})`.

- **F-2 (Medium) — the honest-probe table does not reproduce, and two rows are
  wrong in the direction that misdirects operators**
  (`reports/impl-exclude-allergens.md`, "Honest probe" table). It names no
  seeds, so it cannot be re-run as written. Using `seed = 0..14`:

  | config | report | measured |
  |---|---|---|
  | cam (egg) items=1 | 0 unfit | **1** unfit |
  | cam (egg) items=2 | 0 unfit | **4** unfit |
  | cam (egg) items=3 | 1 unfit | 1 unfit ✓ |
  | kim (soy) items=3 | 1 unfit | **2** unfit |

  `items=2` is not barren — it is the **best** configuration, and robustly so
  across four independent seed ranges (4, 2, 3, 1 unfit per 15; never 0), and
  4/30 vs 2/30 for items=1 and items=3 head-to-head. The report's own
  end-to-end test uses `items=2`, which sits oddly beside a table saying
  items=2 never produces an unfit on the real catalog. The runbook then carries
  "acceptance ~1/15" into operator guidance (`reports/issue15-runbook.md`),
  pointing bulk production at the weaker setting.
  **Fix:** name the seeds and re-measure; state items=2 as the current best
  yield.

- **F-3 (Medium) — every synthetic evaluate query changed, unconditionally and
  unmentioned** (`src/nutrienv/bench/pipeline/expander.py:236`).
  `"Evaluate this as my plan: {meal}."` became
  `"Evaluate this as my plan for dinner: {meal}."` for **all** evaluate drafts,
  recipe or not. Verified against `fdfd2dc`: evaluate is the only family whose
  default output differs. The change is *necessary* — the knife branch derives
  its windows via `occasion_from_query`, which matches only a literal
  `for <meal>` — but it is a change to produced exam text that no axis of this
  spec covers, the impl report does not mention it, and it breaks the
  "defaults byte-identical" property every prior round of this channel has
  checked (the report even asserts "Defaults None → today's behavior"). Minor
  semantic side effect: the fit evaluate oracle pins plate-derived two-key
  windows, not dinner windows, so the query now names an occasion the fit
  oracle does not enforce.
  **Fix:** state it in the impl report and commit scope; or gate the occasion
  clause on a knife/occasion recipe so untouched batches stay byte-identical.

- **F-4 (Low) — an unknown tag is silently accepted, unlike its sibling knob**
  (`src/nutrienv/bench/pipeline/run_batch.py:503-512`).
  `normalize_tags(["bogus_tag"])` returns `('bogus_tag',)`, so
  `exclude_allergens=bogus_tag` parses, excludes nothing, and produces a normal
  plate. The neighbouring `pool_allergen=bogus_tag` raises `catalog has no food
  with allergen tag 'bogus_tag'`. Same commit family, opposite posture.
  **Fix:** validate the tags against the catalog's tag set, as `pool_allergen`
  already does.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_expander.py tests/test_run_batch.py -q
90 passed in 1.24s

$ .venv/bin/python -m pytest -q
1337 passed in 48.77s          # 0 failed
```

```
fixture unfit  query "Evaluate this as dinner: 158 g of rice, 150 g of avocado, 50 g of eggs."
               verdict=reject last_plan=[] reasons=('allergy','kcal_hi') == rebind ✓
               egg carriers added by the knife = 1   validate=[]  evaluate_unfits ✓
               freeze->load: validate=[] verdict=reject tier='single'
real catalog   cam(egg)  items=1/2/3 -> 1 / 4 / 1 unfit per 15 seeds, 0 allergen_clash
               kim(soy)  items=1/2/3 -> 0 / 4 / 2 unfit per 15 seeds, 0 allergen_clash
               items=2 across seed bases 0/100/1000/20260817 -> 4 / 2 / 3 / 1 (never 0)
exclusion      evaluate & recommend honour it (23/60 pools changed); update inert (0/60)
parse          '' / '  ' / ',' refused;  'EGG, Milk' normalized;  log & composite refused
               'bogus_tag' accepted silently                                      <- F-4
```

**Blocker: F-1.** F-2 and F-3 are documentation-and-scope corrections that
should land with it; F-4 is a follow-up. The transport and the fit→knife
mechanism are sound — the unfit really is producible on the real catalog — so
once `update` stops advertising a knob it cannot honour, this is releasable.

## Fix round (claude opus findings)

- **F-1 (High)** — `exclude_allergens` removed from update's recipe keys
  (`"update": {"person", "pool_allergen"}`); the family's carrier pick cannot
  honour it. Regression: `test_update_exclude_allergens_recipe_is_refused`.
- **F-2 (Medium)** — probe re-measured with NAMED seeds (0..29, one pool per
  seed) and a wider items sweep; the corrected table in
  `impl-exclude-allergens.md` reports 0 unfit per config on random pools —
  the earlier "≈1/15" figure is withdrawn, and the reviewer's 4/15 at
  items=2 did not reproduce under this methodology (documented, not argued).
  Runbook operator guidance rewritten: the fit-window gate dominates; no seed
  sweeping for yield.
- **F-3 (Medium)** — the "for dinner" clause is now GATED: synthetic_expander
  takes `occasion: str | None = None` and only adds the clause when set;
  `_expand_one` passes `occasion="dinner"` only for knife recipes on the
  synthetic expander. Recipe-free evaluate drafts are byte-identical again
  ("Evaluate this as my plan: …"), pinned by
  `test_synthetic_evaluate_query_is_byte_identical_without_a_knife`; the
  end-to-end knife test still passes with the gated clause. The change is
  also explicitly recorded here as commit scope.
- **F-4 (Low)** — excluded tags are validated against the catalog's allergen
  vocabulary at run_batch entry ("recipe evaluate.exclude_allergens names
  unknown allergen tag(s) …"), matching pool_allergen's posture.
  Regression: `test_exclude_allergens_unknown_tag_is_refused`.

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1337 passed        # 0 failed (net +3 tests vs 1334 baseline of this spec)
```

## Re-review (claude opus)

**Verdict: REV — narrowly, on F-2 only.** The code is right: F-1, F-3 and F-4
are resolved and I verified each, the mechanism still produces a genuine ADR
0017 unfit, and the whole suite is green. But the replacement probe table is
measured by a harness that never reaches the gate it blames, so the corrected
numbers are wrong in the opposite direction — and the runbook now tells
operators that bulk unfit production is blocked when, through the production
path, it already works.

### Finding status

| # | Finding | Status | Evidence |
|---|---|---|---|
| F-1 | High — `exclude_allergens` inert on `update` | **Resolved** | `run_batch.py:473` is back to `frozenset({"person", "pool_allergen"})`. Probe: `update:exclude_allergens=milk` → `recipe key 'exclude_allergens' is not supported for 'update' (allowed: ['person', 'pool_allergen'])`. Pinned by `test_update_exclude_allergens_recipe_is_refused`. |
| F-2 | Medium — probe table unreproducible / items=2 wrong | **NOT resolved** — see below | |
| F-3 | Medium — unconditional evaluate occasion clause | **Resolved** | `expander.py:239-241` gates the clause on an explicit `occasion=` argument, supplied by `_expand_one` only when a `knife` recipe is present (`run_batch.py:716-720`). Verified against `fdfd2dc` (the commit before the hint landed): **defaults byte-identical across all five families**. Recipe-free → `"Evaluate this as my plan: …"`; `occasion="dinner"` → `"…my plan for dinner: …"`. Pinned by `test_synthetic_evaluate_query_is_byte_identical_without_a_knife`. |
| F-4 | Low — unknown tag silently accepted | **Resolved** | New catalog-tag check at `run_batch.py:131-148`, before any job runs, mirroring `pool_allergen`. Probe: `exclude_allergens=bogus_tag` → `names unknown allergen tag(s) ['bogus_tag']`; `exclude_allergens=egg` still accepted. |
| — | Mechanism | **Still holds** | Deterministic fixture: `"Evaluate this as dinner: 158 g of rice, 150 g of avocado, 50 g of eggs."`, `verdict='reject'`, `last_plan=[]`, `reasons=('allergy','kcal_hi')` equal to the rebind, `validate_draft == []`, `evaluate_unfits` ✓, freeze→load clean. |

### F-2: the corrected table measures a broken harness

The table's methodology is `sample_pools(seed=seed)` + `resolve_candidate` with
`knife=allergy, person=…, tier=single`. It names neither `pool_allergen` nor an
`occasion` hint — and after this very commit, the `for <meal>` clause is no
longer produced by `synthetic_expander` on its own; `_expand_one` adds it. So
the harness feeds the resolver a query with no spoken occasion. I rebuilt that
harness and ran all four variants, cam/egg, items=2, seeds 0..29:

```
[no pool_allergen, no occasion]  unfit=0/30   reasons={'unresolvable': 30}
[pool_allergen,    no occasion]  unfit=0/30   reasons={'unresolvable': 30}
[no pool_allergen, occasion   ]  unfit=0/30   reasons={'unresolvable': 30}
[pool_allergen  +  occasion   ]  unfit=2/30   reasons={'unresolvable': 28}
```

The cause of the 30/30 is not the fit window:

```
query without occasion: "Evaluate this as my plan: a piece of Burrito, and a cup of Pasta with sauce."
occasion_from_query -> None
_realize raises -> ValueError: evaluate knife recipe names no meal occasion
```

Every draw dies at the **occasion gate** (or, without `pool_allergen`, at the
no-carrier gate). Both surface under the same `unresolvable` label, which is
how they were read as fit-window rejections. The fit gate never ran.

**The production path — what `generate_batch.py` actually executes — yields.**
Full `run_batch` with the documented recipe, this checkout, 30 seeds per cell:

| person (exclude) | items=1 | items=2 | items=3 | items=4 |
|---|---|---|---|---|
| roster-cam (egg), unfit / 30 | 2 | **4** | 2 | 0 |
| roster-kim (soy), unfit / 30 | 0 | **6** | 5 | 1 |

`allergen_clash = 0` in every cell. So my earlier 4/15 was not a different
configuration in any exotic sense — it was the *supported* one, and it
reproduces here at 4/30 and 6/30.

**Where the report is right:** the fit window really is the binding constraint.
I instrumented `_realize` on the production path and every single rejection is
the fit gate, exactly as claimed:

```
cam(egg) items=2: unfit=4/30  rejections={'unresolvable': 25, 'code_gate': 1}
     15x  knife input plate does not fit dinner windows: ['kcal_lo']
      6x  knife input plate does not fit dinner windows: ['kcal_hi']
      3x  knife input plate does not fit dinner windows: ['fat_g_hi'…]
kim(soy) items=2: unfit=6/30  rejections={'unresolvable': 24}   (same shape)
```

**Where it is wrong, and why it matters:** "0 unfit / 30 draws per config" and
"reliable bulk yield needs issue-15 plate/window design … not seed sweeps"
(`reports/issue15-runbook.md`) are both refuted by the table above. At items=2
the transport yields **13–20% per pool**, so ADR 0016's floor of 8
Evaluate-unfit is roughly 40–60 pools — a seed sweep, available today. The
guidance as written would park a working capability behind unfinished design
work. Withdrawing a roughly-correct number in favour of a harness artifact is
the failure this project's "LLM produces candidates, not facts" discipline
exists to catch; it errs conservatively, but it is still an unverified number
driving an operator decision.

**Fix (one line of methodology):** measure through `run_batch` — the entry
point operators use — or add `with_allergen=tag` and `occasion="dinner"` to the
standalone harness, then restate: fit window is the binding gate (confirmed),
yield at items=2 is ~4–6 per 30 pools, items=4 is near-zero.

### Answer to the release question

**The transport is safe to release; the 0/30 methodology is not safe to publish
as operator guidance.** Nothing in the code changed my view — F-1/F-3/F-4 are
properly closed and the mechanism is proven both on the fixture and on 10
independent real-catalog draws. What must not ship is the table and the runbook
paragraph derived from it, because they understate a working capability and
misattribute the cause. Correct the two documents and this releases as-is; no
code change is required.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
53 passed in 0.65s

$ .venv/bin/python -m pytest -q
1340 passed in 41.49s          # 0 failed
```

Commit scope: `reports/` ×3, `expander.py`, `run_batch.py`,
`tests/test_run_batch.py`. No ADR, `data/splits/*`, `*.sqlite`, `scorer.py`,
`validator.py`, `review_harness.py`, `quality_gates.py`, or `generate_one.py`
change ✓.

**Blocker: F-2 (documentation only).** Once the probe table and the runbook
paragraph carry production-path numbers, the release line stands:
*exclude_allergens released — unfit is producible on the real catalog
(~4–6 per 30 pools at items=2; fit-window sizing remains issue-15 design).*

## Fix round 2 (claude opus findings)

**F-2 root cause confirmed:** the probe harness fed `resolve_candidate`
queries with no spoken meal; after ff322b5 the "for dinner" clause is gated on
`_expand_one`, so all 30 draws died at "names no meal occasion" — the table
measured a broken harness. Code unchanged (no bug); measurement fixed to the
production path (occasion supplied, exactly as `_expand_one` does).

Corrected matrix (cam/egg, items=2, seeds 0..29):

| config | unfit / 30 | reasons |
|---|---|---|
| no pool_allergen, no occasion | 0 | unresolvable ×30 |
| pool_allergen, no occasion | 0 | unresolvable ×30 |
| no pool_allergen, occasion | 0 | unresolvable ×30 |
| **pool_allergen + occasion** | **2** | unresolvable ×28 |

Production-path sweeps (seeds 0..29): cam/egg items=2 → breakfast 6/30,
lunch 2/30, dinner 2/30; cam/egg dinner items=1/2/3 → 1/2/3; kim/soy items=2
dinner → 4/30; cam dinner items=2 seeds 30..59 → 4/30. **Guidance: items=2 +
occasion=dinner ≈ 2/30 and never 0 across ranges tried; breakfast was best for
cam (6/30).** Fit-window sizing remains issue-15 design. The deterministic
fixture test stays as the mechanism proof. Full suite 1340 passed, 0 failed.

## Final review (claude opus)

**Verdict: ACC.** F-2 is closed properly. I re-ran every number the corrected
table publishes, using the methodology it states, and **all of them reproduce
exactly** — eight sweeps plus the four-row diagnostic matrix, no mismatches.
The cause of the withdrawn 0/30 is now named correctly, and the runbook prose
matches the table it cites. F-1, F-3 and F-4 remain resolved; the mechanism
fixture still holds; suite green; docs-only scope, which is right because the
finding was documentation-only.

### F-2 status: resolved, fully reproduced

Diagnostic matrix (cam/egg, items=2, seeds 0..29) — reproduced exactly:

```
no pool_allergen, no occasion    unfit=0/30  {'unresolvable': 30}
pool_allergen,    no occasion    unfit=0/30  {'unresolvable': 30}
no pool_allergen, occasion       unfit=0/30  {'unresolvable': 30}
pool_allergen  +  occasion       unfit=2/30  {'unresolvable': 28}
```

Published sweeps vs. my re-measurement:

| sweep | published | measured |
|---|---|---|
| cam/egg items=2, breakfast | 6/30 | **6/30** ✓ |
| cam/egg items=2, lunch | 2/30 | **2/30** ✓ |
| cam/egg items=2, dinner | 2/30 | **2/30** ✓ |
| cam/egg dinner, items=1 | 1/30 | **1/30** ✓ |
| cam/egg dinner, items=2 | 2/30 | **2/30** ✓ |
| cam/egg dinner, items=3 | 3/30 | **3/30** ✓ |
| kim/soy dinner, items=2 | 4/30 | **4/30** ✓ |
| cam/egg dinner, seeds 30..59 | 4/30 | **4/30** ✓ |

Mismatches: **none**. The table is now a reproducible artifact rather than a
claim — which is the property that was missing in both previous versions.

The prose is right too. The report states plainly that the earlier run "measured
a broken harness, not the pipeline", and names the mechanism ("every draw failed
at … names no meal occasion"), rather than leaving it as an unexplained
non-reproduction. `reports/issue15-runbook.md` was rewritten to match: the
"0 unfit / 30 draws per config … not seed sweeps" paragraph is gone, replaced
by the measured yields and the same fit-window caveat. Table and guidance no
longer disagree.

### The yield disagreement is settled

My earlier 4/15 and the report's 2/30 were never in conflict about the
pipeline — only about which seed→pool mapping was being sampled. Both hold on
this checkout:

```
report harness (seeds 0..29 -> sample_pools(seed=seed)):
    cam/egg items=2 dinner  2/30      kim/soy  4/30
full run_batch (seed -> _family_seed -> pools):
    cam/egg items=2 dinner  4/30      kim/soy  6/30
```

Same conclusion from both: the mechanism yields on random pools, never zero,
and the fit window is the binding gate. The report's figure is the more
conservative of the two, and it already shows the spread by reporting 4/30 on
seeds 30..59 — so nothing is being smoothed over.

### Other findings, re-verified

| # | Status | Evidence |
|---|---|---|
| F-1 | Resolved | `update:exclude_allergens=milk` → `recipe key 'exclude_allergens' is not supported for 'update'`. |
| F-3 | Resolved | Recipe-free evaluate query is `"Evaluate this as my plan: a regular serving of …"` — the historical phrasing, no occasion clause. |
| F-4 | Resolved | `exclude_allergens=bogus_tag` → `names unknown allergen tag(s) ['bogus_tag']`. |
| Mechanism | Holds | Fixture: `verdict='reject'`, `reasons=('allergy','kcal_hi')` equal to the rebind, `validate_draft == []`, `evaluate_unfits` ✓, freeze→load clean. |

### Note (not a finding)

For operator planning the `generate_batch.py` path is the one that matters, and
it runs ~4–6 unfit per 30 pools at `items=2 + dinner` rather than 2 — the
report's harness samples a different pool sequence. Since the published number
is the conservative one and the qualitative guidance is identical, nothing is
wrong; a single line in the runbook saying "measured through `run_batch`,
4–6/30" would make the planning arithmetic directly usable. Likewise
"yield grows with items over this sample" is correctly hedged — `items=4` falls
back toward zero on the `run_batch` path, so it should not be extrapolated.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
53 passed in 0.64s

$ .venv/bin/python -m pytest -q
1340 passed in 41.66s          # 0 failed
```

Commit scope: `1c0e29b` touches `reports/impl-exclude-allergens.md`,
`reports/issue15-runbook.md`, `reports/spec-exclude-allergens.md` only —
documentation, no code, which matches the finding it closes. No ADR,
`data/splits/*`, `*.sqlite`, `scorer.py`, `validator.py`, `review_harness.py`,
`quality_gates.py`, or `generate_one.py` change.

**RELEASE: exclude_allergens released — unfit producible on the production path
(~2/30 @ items=2+dinner by the report's harness, 4–6/30 through `run_batch`,
occasion-tunable to 6/30 at breakfast); fit-window sizing remains issue-15
design.**
