# Spec: sample_pools allergen targeting + recipe pool_allergen knob (unfit base)

**Status:** decided by coordinator (base transport for the unfit bulk-production path A; the
choice of path A/B/C stays an issue-15 ruling, but this knob is useful under any variant — it
makes "the pool contains the allergen carrier" a satisfiable condition instead of random).

## Problem

`evaluate:knife=allergy+person=roster-cam` (egg) unresolvable on real catalog-v2 random pools:
the synthetic plate takes the first 1-2 pool foods, which usually contain no egg carrier, and even
when it does the plate must bind-fit the person's six-key meal windows. `sample_pools` has no way
to steer which foods a pool contains. A `pool_allergen` knob lets an authoring driver ask "pools
whose top foods can carry allergen X", turning the carrier condition from 1-in-… to satisfiable
(the fit-window condition still needs occasion/person tuning — that stays issue-15 recipe design).

## Change

1. `sample_pools(..., with_allergen: str | None = None)`: when set, pools are drawn such that at
   least ONE enabled alternative food in the pool carries the allergen tag. Implementation:
   eligible keeps all speakable foods; after sampling each pool, if no picked food carries the
   tag, re-draw that pool (rng continues — deterministic per seed) up to a bounded retry count
   (e.g. 8); if still none (catalog lacks the tag entirely), raise ValueError("catalog has no
   food with allergen tag X") — fail-closed, never a silent allergen-less pool.
2. `run_batch._parse_spec`/`_build_jobs`: optional `"pool_allergen"` in family recipes (apply to
   any family — harmless filter; validate the value is a non-empty string, fail-closed on
   unknown tag AFTER sample_pools raises). Thread into the `sample_pools` call for that family.
3. `_RECIPE_KEYS`: add "pool_allergen" to all family sets (it is a sampler-level knob, orthogonal
   to realize semantics).
4. `generate_batch.py --recipe evaluate:pool_allergen=egg` passes through (generic parsing).
5. Tests: `sample_pools(with_allergen='egg')` on catalog-v2 → every pool has ≥1 egg-tag food;
   `with_allergen='nonexistent_tag'` raises; a synthetic batch with
   `evaluate:knife=allergy+person=roster-cam+pool_allergen=egg+tier=single+items=1` — either
   produces an unfit item (fit-window permitting) or, if the fit precondition still rejects every
   pool, document the residual honestly (the carrier condition is now satisfied; the fit gate is
   the remaining knobs). Do NOT fake a pass; report what the real run yields.

## Definition of done

1. Tests pass; full suite 0 failed (expect 1332+).
2. Honest probe: knife+person+pool_allergen+fit-tuned occasion/items → report unfit count (may be
   >0 or still 0; the sample_pools knob's own test (every pool carries the tag) is the hard
   assertion).
3. Commit "pipeline: " prefix. Append evidence to reports/issue15-runbook.md (path A base) and a
   new reports/impl-pool-allergen.md.
4. Do NOT touch: docs/adr/*, data/splits/*, *.sqlite, scorer.py, validator.py, review_harness.py,
   quality_gates.py, generate_one.py.

Work autonomously. If blocked, stop and report.
## Review (claude opus)

**Verdict: ACC.** The knob works on every axis I could probe: the carrier
guarantee holds across 6 tags × 4 seeds × 4 families, pools stay size 8 with no
duplicate foods, the same seed gives the same pools, an unknown tag raises, and
the default path is byte-identical to the pre-commit sampler across 40 configs.
The recipe reaches `sample_pools` for all four advertised families — no silent
no-op. The documented residual is real, not a papered-over failure. Two Medium
findings, neither a behaviour defect: the sampler's docstring describes a
mechanism the code does not use, and the run_batch-level test has no power over
the feature it names.

### Axis results

| Axis | Result |
|---|---|
| 1 Correctness | Carrier per pool: **true** for egg/milk/soy/tree_nut/shellfish/peanut × seeds {1, 7, 20260822, 99999} × families {evaluate, recommend, composite, update} — 480 pools, zero misses, pool size always 8, zero duplicate-food pools. Deterministic per seed ✓. Unknown tag → `catalog has no food with allergen tag 'nonexistent_tag'` ✓. Default `None` identical to `6a5c7be` across 40 (seed × family × spoken_only) configs ✓. `rng` stays a local `random.Random(seed)`, so thread-safety is unchanged ✓. No infinite loop is possible — there is no loop (see F-1). |
| 2 Honesty | The residual is real. Reproduced `knife=allergy + person=roster-cam + pool_allergen=egg + items=1` → `{allergen_clash, unresolvable}`, nothing accepted. I also confirmed the *mechanism* behind it, which the impl note describes correctly: the swap lands the carrier at `pool.foods[0]` and `synthetic_expander` takes the first N speakable foods, so a swapped pool nearly always drafts the carrier into the plate — where the person's own allergy then rejects it. No faked pass, and the boundary is stated rather than hidden. |
| 3 Fail-closed / no-op families | Instrumented `sample_pools` and ran each family through `run_batch`: `evaluate → ('evaluate','egg')`, `recommend → ('recommend','egg')`, `update → ('update','egg')`, `composite → ('composite','egg')`. Every advertised family threads it; `log` is not advertised. `pool_allergen` is also correctly excluded from the Candidate `stamps` (`run_batch.py:670-675`) — `Candidate` has no such field, so stamping would have raised. |
| 4 Scope | `reports/` ×2, `scripts/generate_batch.py`, `run_batch.py`, `sampler.py`, `tests/test_run_batch.py`. No ADR, `data/splits/*`, `*.sqlite`, `scorer.py`, `validator.py`, `review_harness.py`, `quality_gates.py`, or `generate_one.py` change ✓. |

### Findings

- **F-1 (Medium) — the docstring describes bounded retries; the code does a
  single slot-0 swap** (`src/nutrienv/bench/pipeline/sampler.py:54-56` vs
  `:86-88`). The docstring says "draws without one are retried (same rng,
  bounded)". There is no retry and no loop: a deficient draw has `picked[0]`
  replaced by `rng.choice(sorted(carriers))`. The inline comment at `:85-87`
  states the truth and gives a good reason (on a 5000-food catalog a pure
  re-draw essentially never hits), so the implementation choice is right — but
  the public contract is not what the code does. This is not cosmetic: a reader
  taking the docstring at face value would expect a uniform draw *conditioned*
  on containing a carrier, whereas the real distribution has slot 0 forcibly
  replaced. That difference is exactly what produces the documented residual,
  so hiding it in the docstring hides the mechanism.
  **Fix:** replace the retry sentence with the swap and its positional bias —
  "a draw without one has one slot replaced by a deterministically chosen
  carrier, so the carrier lands at index 0."

- **F-2 (Medium) — `test_pool_allergen_recipe_feeds_the_sampler` has no power
  over the feature it names** (`tests/test_run_batch.py:1133-1165`). It never
  inspects a pool, and both its assertions
  (`accepted == [] or all(...)`, `{reasons} <= {"unresolvable","allergen_clash"}`)
  are satisfied whether or not the knob is present. Ran the identical config
  with and without `pool_allergen`:

  ```
  with    pool_allergen: accepted=0 reasons=['allergen_clash','unresolvable'] assert1=True assert2=True
  WITHOUT pool_allergen: accepted=0 reasons=['allergen_clash','unresolvable'] assert1=True assert2=True
  ```

  Deleting the `with_allergen=` line from `_build_jobs` would not fail this
  test. The wiring is in fact correct — I proved it by instrumenting
  `sample_pools` — but the commit ships no regression guard for it, and the
  test's docstring asserts a claim ("the recipe reaches the sampler") that the
  body does not check. `test_sample_pools_with_allergen_targets_carrier_pools`
  (`:1105`) is genuinely strong and does cover the sampler-level guarantee, so
  the feature is not untested — only the run_batch wiring is.
  **Fix:** assert the jobs' pools carry the tag, or spy on `sample_pools` and
  assert it received `with_allergen="egg"`.

- **F-3 (Low) — the swap always targets slot 0, biasing carrier position**
  (`sampler.py:88`). Measured on seed 20260822: swapped pools put the carrier
  at index 0 every time (pools 0, 2, 3, 4), while naturally-drawn carriers sit
  anywhere (indices 1/4 and 4). Because `synthetic_expander` selects the first
  N speakable foods, this makes "carrier ends up in the plate" the norm for
  swapped pools rather than an occasional event — it systematises the residual.
  It also means slot 0's originally drawn food is always the one discarded.
  **Fix:** `picked[rng.randrange(len(picked))] = rng.choice(sorted(carriers))`.

- **F-4 (Low) — `with_allergen` is not normalized while catalog tags are**
  (`sampler.py:66-78`). Catalog tags go through `normalize_tags` (which
  lowercases), the input does not, so `pool_allergen=Egg` raises
  `catalog has no food with allergen tag 'Egg'` — blaming the catalog for what
  is an input-casing issue. Fail-closed, so nothing unsafe; just a misleading
  message for a plausible typo.
  **Fix:** normalize the input the same way before building `carriers`.

### Notes

- `data/fdc/catalog-v2.sqlite` is tracked in git, so the new sampler test's
  real-catalog dependency is safe (no worktree/missing-data hazard).
- `pool_allergen` guarantees a carrier is *in the pool*, not that the draft
  *names* it. That is inherent to the knob and correctly scoped as issue-15
  recipe design in the impl notes — worth keeping that sentence wherever the
  knob gets documented for operators, since "pool_allergen=egg" reads like a
  promise about the item.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
47 passed in 0.72s          # the new tests live here; there is no tests/test_sampler.py

$ .venv/bin/python -m pytest -q
1334 passed in 63.34s       # 0 failed
```

```
carrier guarantee   egg/milk/soy/tree_nut/shellfish/peanut: all pools carry it (480 pools)
                    pool sizes=[8]  duplicate-food pools=0  same seed -> same pools: True
default None        identical to 6a5c7be across 40 configs: True
unknown tag         ValueError: catalog has no food with allergen tag 'nonexistent_tag'
family threading    evaluate/recommend/update/composite -> sample_pools got with_allergen='egg'
residual            knife+person=cam+pool_allergen=egg+items=1 -> {allergen_clash, unresolvable}
```

**RELEASE: the pool-allergen base is accepted.** F-1 and F-2 should land
together in a short follow-up — the docstring must describe the swap, and the
wiring needs a test with actual power — but neither blocks use of the knob.

## Fix round (claude opus findings)

- **F-1 (Medium)** — docstring now states the real mechanism: "a draw without
  one has one slot replaced by a deterministically chosen carrier (so the
  carrier lands at a random index)"; the retry sentence is gone.
- **F-2 (Medium)** — `test_pool_allergen_recipe_reaches_the_sampler` (renamed)
  spies on `run_batch.sample_pools` via monkeypatch and asserts it received
  `with_allergen="egg"` for the evaluate family — deleting the `_build_jobs`
  wiring now fails the test. The run-residual assertions stay as secondary.
- **F-3 (Low)** — the swap targets `picked[rng.randrange(len(picked))]`
  instead of always slot 0, removing the positional bias that systematised
  the allergen_clash residual; sampler carrier test re-run green.
- **F-4 (Low)** — `with_allergen` is normalized through the same
  `normalize_tags` as catalog tags before building the carrier set; casing
  pinned by `test_pool_allergen_input_is_normalized` (`"Egg"` finds egg).

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1335 passed in 57.70s        # 0 failed (was 1334; +1 net test)
```

## Re-review (claude opus)

**Verdict: ACC.** All four follow-ups are closed, and two of them I could
verify beyond reading the diff: the wiring test now genuinely dies when the
wiring is removed (mutation-checked), and the swap-bias fix measurably changed
the downstream behaviour it was distorting. No new findings.

### Finding status

| # | Finding | Status | Evidence |
|---|---|---|---|
| F-1 | Medium — docstring described bounded retries | **Resolved** | `sampler.py:54-57` now reads "a draw without one has one slot replaced by a deterministically chosen carrier (so the carrier lands at a random index)". No "retry" wording, and the "random index" clause is borne out by the histogram under F-3. The inline comment at `:87-89` matches. |
| F-2 | Medium — the wiring test had no power | **Resolved, mutation-checked** | The test is renamed `test_pool_allergen_recipe_reaches_the_sampler` and spies on `run_batch.sample_pools`, asserting `seen == {"evaluate": "egg"}`. I did not take that on faith: I rebuilt `_build_jobs` in memory with the `with_allergen=` kwarg stripped and re-ran the test against both versions. Real wiring → **PASSED**; wiring deleted → **AssertionError on `assert seen == {"evaluate": "egg"}`**. The guard is real. |
| F-3 | Low — swap always hit slot 0 | **Resolved** | `sampler.py:90` uses `picked[rng.randrange(len(picked))]`. Measured over 200 carrier pools (40 seeds × 5): carrier index histogram `{0:29, 1:26, 2:25, 3:25, 4:30, 5:22, 6:32, 7:16}` — spread across all eight slots instead of pinned at 0. The knock-on the finding was really about is gone too: `items=1` drafts containing the carrier fell to **29/200 (14.5%)**, about the natural 1-in-8 rate, where swapped pools previously drafted it almost every time. The residual is no longer systematised. Guarantee intact: 200/200 pools carry the tag, size 8, zero duplicate-food pools. |
| F-4 | Low — input tag not normalized | **Resolved** | `sampler.py:69-70` normalizes the input the same way catalog tags are. Probe: `'egg'`, `'Egg'`, `'EGG'`, `'  egg'` all accepted and land on real egg carriers; `'nonexistent_tag'` still raises `catalog has no food with allergen tag 'nonexistent_tag'`. `'shrimp'` still raises — correct, since `normalize_tags` does not alias it to `shellfish` anywhere in the codebase, so this stays consistent and fail-closed. Pinned by the new `test_pool_allergen_input_is_normalized`. |

### Regression checks

- Carrier guarantee re-swept after the swap change: egg/milk/soy/tree_nut/
  shellfish/peanut × seeds {1, 7, 20260822, 99999} × families {evaluate,
  recommend, composite, update} — **every pool carries the requested tag**.
- Determinism: same seed → same pools ✓.
- Default path (`with_allergen=None`) still **identical to the pre-feature
  sampler at `6a5c7be`** across 15 seed × family configs — the two extra rng
  calls are inside the carrier branch and cannot touch ordinary draws.
- Recipe-channel guard sweep (all prior rounds) re-run: `evaluate:tier=bogus`,
  `log:tier`, `update:tier`, `evaluate:occasion`, `knife=swap`,
  `recommend:shell/scene`, unrequested family, `tier=None` — all still refused;
  `knife allergy` still gram-exact at `tier='single'`; `empty recipe == no
  recipe` True.

### Note (informational, not a finding)

`with_allergen` pool draws are not reproducible between `5269dd0` and
`fdfd2dc`: the F-3 fix adds an `rng.randrange` call before `rng.choice`, so the
same seed now yields different carrier pools. That is the intended consequence
of removing the bias and it affects only `with_allergen` runs — ordinary draws
are unchanged, and nothing frozen depends on the old stream. Worth knowing if
any `pool_allergen` probe output recorded before this commit is ever compared
byte-for-byte.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
48 passed in 0.75s          # the pool_allergen tests live here; there is no tests/test_sampler.py

$ .venv/bin/python -m pytest -q
1335 passed in 48.02s       # 0 failed
```

Commit scope: `fdfd2dc` touches `reports/spec-pool-allergen.md`,
`src/nutrienv/bench/pipeline/sampler.py`, `tests/test_run_batch.py`. No ADR,
`data/splits/*`, `*.sqlite`, `scorer.py`, `validator.py`, `review_harness.py`,
`quality_gates.py`, or `generate_one.py` change. `run_batch.py` and
`generate_batch.py` are correctly untouched — nothing there needed changing.

**pool_allergen base fully closed.**
