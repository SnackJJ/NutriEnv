# Spec: recipe person knob — resolver uses a chosen roster person, not fixed ROSTER[0]

**Status:** decided by coordinator (base for the 14-assertion persona×allergen coverage: the
synthetic preview showed everyday-only + 1 allergen because the resolve path hard-codes
`ROSTER[0]` = roster-ada (peanut) at four sites; generate_one already samples 20 roster people).

## Problem

`src/nutrienv/bench/pipeline/resolver.py` uses `profile_for(ROSTER[0])` at 4 sites
(`_composite_windows` :334, recommend :397, update :438, knife :508). ROSTER[0] is roster-ada
(persona everyday, allergy peanut). So every batch item — composite/recommend/update/knife — is
profiled as ada: windows derived from her body facts, allergies {peanut} only. The 14-assertion
`recommend_coverage` (persona × allergen tags) can never pass: cut/gym personas and the other 6
catalog allergens (egg/milk/shellfish/soy/tree_nut/…) are unreachable through the batch path.
`generate_one` instead does `sample_roster_person(seed)` (roster.py:198) so the mill covers the
diversity; only the batch path is pinned to one person.

## Change

1. `types.Candidate` gains `person: str | None = None` (a roster user_id or index, default None).
2. `run_batch._RECIPE_KEYS`: add `person` to every family set ({"knife","tier","items",
   "amount_path","person"} evaluate; {"occasion","person"} recommend; {"person"} update,
   composite). Parse: accept `person=roster-ada` or `person=1` (index) — validate it resolves to a
   RosterPerson (reuse roster lookup; fail-closed on bad id).
3. `resolver`: thread `candidate.person` (via a small `_person_profile(candidate)` helper that
   falls back to `ROSTER[0]` when person is None — defaults byte-identical) into
   `_composite_windows`, `_realize_recommend`, `_realize_update`, `_realize_evaluate_knife`
   (their `profile_for(ROSTER[0])` calls become `profile_for(chosen)`).
4. `generate_batch.py --recipe evaluate:person=roster-cam` passes through (generic parsing).
5. Tests: `evaluate:knife=allergy + person=roster-cam` → task profile is cam's (cut persona, egg
   allergy — verify profile.allergies contains egg and windows match cam's); recommend person →
   recommend coverage now shows cam's allergen; a batch with personas over multiple roster people
   covers cut + egg + milk etc. (the 14-assertion need); `person=bogus` rejected at parse.

## Definition of done

1. Tests pass; full suite 0 failed (expect 1321+).
2. Demo: a synthetic batch mixing `evaluate:person=roster-cam` (egg), `recommend:person=roster-fay`
   (milk) covers those allergens/personas in `recommend_coverage` — the persona×allergen channel
   works.
3. Commit "pipeline: " prefix. Append evidence to reports/spec-recipe-items.md (or a new
   reports/impl-recipe-person.md).
4. Do NOT touch: docs/adr/*, data/splits/*, *.sqlite, scorer.py, validator.py, review_harness.py,
   quality_gates.py, generate_one.py.

Work autonomously. If blocked, stop and report.
## Implementation notes & demo

- `Candidate.person` (roster user_id or index); `_RECIPE_KEYS` carries
  `person` on every family; parse resolves it via
  `resolver._resolve_roster_person` (fail-closed on unknown id / bad index).
  Resolver sites now derive profiles via `_person_profile(candidate)`
  (`_realize_recommend` / `_realize_update` / `_realize_evaluate_knife` /
  composite windows), falling back to ROSTER[0] when unset (defaults
  byte-identical). When a person IS chosen, the Task persona becomes that
  roster person's persona (so `recommend_coverage` sees cut/gym personas).
- Tests: knife+person=roster-cam (cut profile, egg allergy, allergy reason,
  draft clean); recommend+roster-fay covers milk; mixed cam/fay covers
  cut/everyday + egg/milk in `recommend_coverage`; person=bogus/999 refused
  at parse; person=2 (index) resolves to roster-cam.
- Demo (catalog-v2, synthetic): `recommend:person=roster-fay` items reload
  with allergies ('milk',) and close the milk allergen + everyday persona in
  `recommend_coverage`. The `evaluate:knife=allergy + person=roster-cam`
  accept path is pinned by the deterministic fixture test
  (`test_person_recipe_uses_the_chosen_roster_profile`); on random catalog-v1
  pools it rejects cleanly (`unresolvable`) because a random plate rarely
  fits cam's tighter cut-phase dinner slot AND the pool lacks an egg carrier
  — fail-closed, documented.
```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1326 passed in 50.35s        # 0 failed (was 1321; +5 tests)
```

## Review (claude opus)

**Verdict: REV.** Where the knob is implemented it works cleanly — `recommend`
with `person=roster-cam/fay/ben` really swaps persona, allergies, phase and
windows, and a mixed batch closes cut/gym personas plus egg/milk in the real
`recommend_coverage` gate. Parse is fail-closed on every malformed form I
tried, and defaults are byte-identical. But `person` is advertised on five
families and genuinely implemented on three: it is a **complete no-op on `log`
and on the evaluate FIT path**, and only **half applied on `composite`** — the
half that the persona×allergen purpose actually needs is the missing half.

### Axis results

| Axis | Result |
|---|---|
| 1 Correctness | recommend / update / evaluate-knife: fully applied ✓. **log, evaluate-fit: silently ignored (F-1). composite: windows only (F-2).** |
| 2 Fail-closed | `roster-bogus` / `999` / `-1` / `""` / `2.0` / `roster-ADA` all refused at parse ✓; CLI refuses too (F-4 is only about how). Defaults byte-identical: no-recipe == empty recipe == `person=roster-ada` ✓. |
| 3 14-assertion effect | Works for the `recommend` family: a cam+fay+ben batch gives `missing_personas=()` over `("everyday","cut","gym")` and `missing_allergens=('peanut','soy')` — egg and milk closed ✓. Does **not** work through composite recommend children (F-2), and evaluate items cannot feed this gate at all (see the note on the spec's DoD #2). |
| 4 Scope | `reports/`, `generate_batch.py`, `resolver.py`, `run_batch.py`, `types.py`, `tests/test_run_batch.py` only. `generate_one.py`, ADRs, splits, sqlite, scorer, validator, review_harness, quality_gates untouched ✓. Prior guards re-swept, none regressed (incl. `recommend:tier` still refused). |

### Findings

- **F-1 (High) — `person` is an accepted no-op on `log` and on the evaluate FIT
  path** (`src/nutrienv/bench/pipeline/run_batch.py:437,440`). `_RECIPE_KEYS`
  advertises `person` for `log` and for all of `evaluate`, but `_realize`'s log
  branch never reads `candidate.person`, and `_realize_evaluate`
  (`resolver.py:501`) does not either — only `_realize_evaluate_knife` does.
  Probed both, comparing against the same run with no recipe:

  ```
  log person=roster-cam        persona='everyday' allergies=('peanut',) phase='maintain'
     log task identical to no-person: True
  evaluate-fit person=roster-cam persona='everyday' allergies=('peanut',) phase='maintain'
     evaluate-fit identical to no-person: True
  ```

  A user writing `--recipe evaluate:person=roster-cam` (no knife) or
  `--recipe log:person=roster-cam` gets ada items while believing the batch is
  diverse — which is exactly the failure the 14-assertion work is trying to
  fix, now hidden behind an accepted knob. This is the silent-no-op class this
  channel has already ruled on twice: `evaluate.occasion` was **removed** for
  it (NEW-2) and `items`/`amount_path` were made **fail-closed** for it (F-2 of
  the items round). `_RECIPE_KEYS`'s own docstring still reads "A key outside
  the family's set would be silently dropped or ignored by the realize branch,
  so the parser refuses it."
  **Fix:** drop `"log"` from `_RECIPE_KEYS` and require `knife` alongside
  `person` for evaluate (or thread `_person_profile` into `_realize_evaluate`).

- **F-2 (Medium) — `composite:person` applies the windows but not the
  allergies, phase, or persona** (`resolver.py:323-327`). `candidate.person` is
  threaded into `_composite_windows` only; the Material's `allergies` still
  come from `_log_allergies` (the food-vs-peanut rule) and the Task persona
  stays `candidate.persona`. Probe with `composite:person=roster-cam`:

  ```
  s0.profile: phase='maintain'  allergies=('peanut',)  daily kcal=(1300.8, 1300.8)
  persona='everyday'
  cam: persona='cut' allergies=('egg',) phase='cut' daily kcal=(1300.8, 1300.8)
  ada: daily kcal=(1815.34, 1815.34)
  ```

  So the numbers are cam's while the identity is ada's. The task stays passable
  — the profile's own windows and the oracle agree, `validate_draft == []`, so
  this is not a broken item — but `phase='maintain'` now contradicts a cut-derived
  energy band (ADR 0015 ties those), and more to the point the composite
  recommend child contributes **ada's** allergen and the **batch** persona to
  `recommend_coverage`, which counts composite children explicitly (ADR 0016,
  `quality_gates.py:126-127`). For the one gate this spec exists to satisfy,
  the composite half of the knob does nothing.
  **Fix:** derive the composite Material's `allergies`/persona from
  `_person_profile(candidate)` too, or drop `"composite"` from `_RECIPE_KEYS`
  until it does.

- **F-3 (Low) — the mixed-person coverage test asserts against a hand-rolled
  proxy instead of the gate** (`tests/test_run_batch.py:949-957`).
  `test_mixed_person_recipes_cover_cut_and_both_allergens` computes coverage
  with a local `_recommend_lens_allergies(task)` that just returns
  `[task.s0.profile.allergies]`, then asserts `{"egg","milk"} <= covered`. It
  never checks `report.missing_allergens`, so it would keep passing if
  `_recommend_lenses` stopped seeing these tasks — precisely the regression the
  14-assertion cares about. (I ran the real gate: it does pass today,
  `missing_allergens == ('peanut','soy')`, so this is a test change only.)
  **Fix:** assert `"egg" not in report.missing_allergens and "milk" not in report.missing_allergens`.

- **F-4 (Low) — cross-module private import, and a raw traceback at the CLI**
  (`run_batch.py:22`, `scripts/generate_batch.py`). `run_batch` imports
  `_resolve_roster_person` from `.resolver` — a leading-underscore name reached
  across modules. It also means a bad `--recipe recommend:person=roster-bogus`
  surfaces as an unhandled `ValueError` traceback, where the sibling CLI guards
  (`--recipe … requires --synthetic`, `--recipe family … is not among …`) exit
  with a clean message. Fail-closed either way, just inconsistent.
  **Fix:** make it public (`resolve_roster_person`), ideally on `roster.py`
  beside `ROSTER`, and catch it in `generate_batch.main` as `SystemExit`.

### Not defects (checked)

- `update:person=roster-cam` rejecting as `unresolvable` is **correct**: the
  `_UPDATE` fixture names egg and cam already carries egg, so
  `_realize_update` raises "update names no food carrying a new allergen tag".
  Verified `roster-fay` → `oracle.allergies=('egg','milk')` and `roster-ben` →
  `('egg',)` both succeed. Fail-closed working as designed.
- The spec's DoD #2 ("a batch mixing `evaluate:person=roster-cam` (egg) and
  `recommend:person=roster-fay` (milk) covers those allergens in
  `recommend_coverage`") cannot be met by its evaluate half regardless of
  F-1: `recommend_coverage` only walks recommend lenses
  (`quality_gates.py:132`), so an evaluate item contributes nothing to it by
  construction. Probed: an evaluate task yields
  `missing_personas=('cut',) missing_allergens=('egg',)`. The impl notes are
  correctly narrower than the DoD here — worth correcting the DoD wording so
  nobody reads it as a coverage claim.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
41 passed in 0.31s

$ .venv/bin/python -m pytest -q
1326 passed in 50.02s          # 0 failed
```

```
recommend person=None        persona='everyday' allergies=('peanut',) kcal_win=(544.6, 726.14)
recommend person=roster-cam  persona='cut'      allergies=('egg',)    kcal_win=(390.24, 520.32)
recommend person=roster-fay  persona='everyday' allergies=('milk',)   kcal_win=(474.99, 633.33)
mixed cam+fay+ben -> missing_personas=()  missing_allergens=('peanut','soy')
CLI --recipe recommend:person=roster-fay --synthetic -> wrote 1 item, allergies=['milk']
parse: roster-bogus / 999 / -1 / "" / 2.0 / roster-ADA  -- all refused
defaults: no recipe == empty recipe == person=roster-ada  -- True
```

**Blockers: F-1.** F-2 should land with it (same decision — implement or stop
advertising). F-3/F-4 are follow-ups. The recommend/update/knife transport
itself is sound and is what the persona×allergen coverage needs; once the
advertised surface matches the implemented surface, this is releasable.

## Fix round (claude opus findings)

- **F-1 (High) — no more person no-ops.** `log` removed from `_RECIPE_KEYS`
  (its realize branch has no person semantics; refused at parse). For
  evaluate, the stronger option was taken: `_realize_evaluate` now honours
  `candidate.person` — allergies and persona come from the chosen roster
  person (windows stay on the legacy gold-table derivation, which
  `_realize_evaluate`'s realize path owns). Defaults (person unset) are
  byte-identical: `_log_allergies` semantics preserved for the no-person run.
  Tests: `test_log_person_recipe_is_refused`,
  `test_evaluate_fit_person_honours_the_roster_profile` (egg + cut persona vs
  peanut + everyday baseline).
- **F-2 (Medium) — composite person owns identity.** The composite Material's
  allergies AND persona now derive from the chosen roster person (same source
  as its windows), so a composite recommend child contributes that person's
  allergen/persona to `recommend_coverage`. Test:
  `test_composite_person_recipe_feeds_recommend_coverage` — real-gate
  assertions plus freeze→load with `validate_draft == []` and the child
  profile's egg allergy intact.
- **F-3 (Low)** — mixed-person test now asserts the real gate:
  `recommend_coverage(...)` with `missing_personas == ()` and egg/milk absent
  from `missing_allergens`; the local proxy helper is deleted.
- **F-4 (Low)** — `_resolve_roster_person` renamed public
  (`resolve_roster_person`); run_batch imports it openly. CLI: `main` wraps
  `run_batch` and converts spec-validation ValueErrors into clean
  `SystemExit("batch spec rejected: …")` messages instead of tracebacks.
- Demo (catalog-v2, synthetic): composite:person=roster-cam +
  recommend:person=roster-fay → tasks carry persona cut / allergies ('egg',)
  and ('milk',); `recommend_coverage(personas=("cut","everyday"))` reports
  `missing_personas == ()` and egg/milk both covered (real gate).
```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1329 passed in 52.08s        # 0 failed (was 1326; net +3 tests)
```

## Re-review (claude opus)

**Verdict: REV.** All four findings are genuinely resolved — verified by probe,
including the composite child reaching the *real* `recommend_coverage` gate and
the CLI now exiting cleanly. But the fix that closed F-2 silently removed a
deliberate guard: `allergies = chosen.allergies` replaces `_log_allergies`
unconditionally, so a chosen person's allergen and the drafted foods are now
picked independently with no collision check. That produces a composite that
logs a food the profile is allergic to, and — on the evaluate path — silently
drops the allergen so the item contributes nothing to coverage.

### Finding status

| # | Finding | Status | Evidence |
|---|---|---|---|
| F-1 | High — `person` no-op on `log` and evaluate-fit | **Resolved** | `log` removed from `_RECIPE_KEYS` (`run_batch.py:436-441`, with a comment saying why); probe: `log:person=roster-cam` → `recipe key 'person' is not supported for 'log' (allowed: [])`. Evaluate-fit took the thread-it-through route (`resolver.py:299-302`, `:510-528`): probe `evaluate:person=roster-cam` → `persona='cut'`, `allergies=('egg',)` vs baseline `'everyday'`/`('peanut',)`, task **not** identical to the no-person run. The rule is consistent — no accepted `person` value is now inert. |
| F-2 | Medium — `composite:person` windows-only | **Resolved** | `_realize`(`resolver.py:299-302`) now takes allergies **and** persona from the chosen roster person and feeds both into the composite Material. Probe against the **real** gate: `composite:person=roster-cam` → `persona='cut'`, `s0.allergies=('egg',)`, `child.allergies=('egg',)`, `recommend_coverage([task], personas=("cut",), allergen_tags=("egg",))` → `missing_personas=() missing_allergens=()`. Freeze→load keeps the child allergies (pinned by the new test). |
| F-3 | Low — proxy assertion | **Resolved** | `_recommend_lens_allergies` helper deleted; `test_mixed_person_recipes_cover_cut_and_both_allergens` now asserts `"egg" not in report.missing_allergens` and `"milk" not in report.missing_allergens` off the real `recommend_coverage` report. |
| F-4 | Low — private import + CLI traceback | **Resolved** | `resolve_roster_person` is public (`resolver.py:344`), imported normally by `run_batch.py:22`. CLI probes: `--recipe log:person=roster-cam` → `batch spec rejected: recipe key 'person' is not supported for 'log'`; `--recipe recommend:person=roster-bogus` → `batch spec rejected: unknown roster person 'roster-bogus'`. No traceback, matching the sibling guards. Happy path end to end: `--recipe composite:person=roster-cam --synthetic` wrote an item with `persona=cut allergies=['egg']`. |

### New findings

- **N-1 (Medium) — the `_log_allergies` collision guard is bypassed on the
  person path, so a composite can log a food its own profile is allergic to**
  (`src/nutrienv/bench/pipeline/resolver.py:301`). `_log_allergies`
  (`resolver.py:415-419`) exists to prevent exactly this: it adds `peanut`
  **only if** none of the bound foods carries peanut. The person branch
  discards it — `allergies = chosen.allergies`, unconditionally. Probe with the
  commit's own `_COMPOSITE` fixture (which logs a cup of milk) and a
  milk-allergic person:

  ```
  composite:person=roster-fay -> ACCEPTED
     s0.allergies=('milk',)  ledger_tail=[('milk_whole', 244.0)]
     food tags=['milk']  CLASH=['milk']  validate_draft=[]
  composite:person=roster-cam -> s0.allergies=('egg',) logged=milk_whole  CLASH=-   (fine)
  no person                   -> s0.allergies=('peanut',) logged=milk_whole (guard held)
  ```

  The commit's test picks `roster-cam` (egg) against a milk plate, so the
  collision case is never exercised. Nothing catches it: `validate_draft`
  returns `[]`, and the validator has no ledger-vs-profile allergen rule (its
  allergen checks cover update evidence, the condition family, and
  `fitting_plan` unpassability — none of them this). The item stays *passable*,
  so this is a plausibility/coherence regression rather than a scoring bug —
  but it is a deliberate guard removed as a side effect, and it is not rare:
  measured against the real catalog's 5394 eligible pool foods, a milk-allergic
  person (fay, quin) collides with **11.3%** of them, egg 2.4%, shellfish/peanut
  ~2.5%. A 1–2 food draft with fay clashes roughly one time in five.
  **Fix:** keep the guard's shape — `allergies = tuple(t for t in chosen.allergies if t not in carried)` where `carried` is the bound foods' tags — or reject the candidate on collision, which is more in keeping with this channel's fail-closed habit.

- **N-2 (Medium) — on the evaluate path the colliding allergen is silently
  dropped, so the person contributes nothing** (same root cause,
  `resolver.py:301` feeding `_realize_evaluate`). The evaluate realize path
  filters the allergy against the plate to keep the fit oracle fit, so:

  ```
  evaluate:person=roster-fay, plate = a cup of milk
     -> ACCEPTED  s0.allergies=()   persona='everyday'
  ```

  The operator asked for fay and got a profile with **no allergies at all**.
  Coverage silently fails to improve, which is precisely the outcome this spec
  exists to prevent, and there is no signal that it happened. This channel has
  twice ruled that an accepted knob must not silently under-deliver
  (`evaluate.occasion` removed as NEW-2; `items`/`amount_path` made fail-closed
  as F-2 of the items round).
  **Fix:** the same collision check as N-1 — reject the candidate so the
  shortfall is visible instead of silent.

- **N-3 (Low) — `_realize_evaluate`'s `windows=` argument is dead for the
  evaluate family** (`resolver.py:526-527`). The comment says "A chosen roster
  person also owns the evaluated plate's windows", but the evaluate realize
  path derives its own two-key plate windows and never uses `Material.windows`.
  Probed: with `person=roster-cam`, `s0.profile.windows["kcal"] == (490.0,
  800.0)` — neither `GOLD_WINDOWS` (1800–2200) nor cam's (1300.8, 1300.8), for
  both the person and no-person runs. The commit's own test comment concedes
  the windows "stay put", so the intent is understood — but the code and its
  comment claim an effect they do not have.
  **Fix:** drop the argument and the comment, or say in one line why evaluate
  windows are plate-derived.

- **N-4 (Low) — the CLI's `except ValueError` wraps the whole `run_batch`
  call** (`scripts/generate_batch.py:287-290`). Any `ValueError` raised
  mid-run, long after spec parsing, is reported as `batch spec rejected: …`,
  which would mislead. **Fix:** wrap only the spec-validating portion, or
  re-word to `batch failed: …`.

### Regression sweep

Re-ran every guard closed in earlier rounds (this commit touched `_RECIPE_KEYS`
again): `evaluate:tier=bogus`, `log:tier`, `update:tier`, `evaluate:occasion`,
`knife=swap`, `recommend:shell/scene`, unrequested family, `tier=None` — all
still refused; `knife allergy` still gram-exact; `empty recipe == no recipe`
True. Nothing regressed.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
44 passed in 0.25s

$ .venv/bin/python -m pytest -q
1329 passed in 48.33s          # 0 failed
```

Commit scope: `49b9193` touches `reports/spec-recipe-person.md`,
`scripts/generate_batch.py`, `src/nutrienv/bench/pipeline/resolver.py`,
`src/nutrienv/bench/pipeline/run_batch.py`, `tests/test_run_batch.py`. No ADR,
`data/splits/*`, `*.sqlite`, `scorer.py`, `validator.py`, `review_harness.py`,
`quality_gates.py`, or `generate_one.py` change.

**Blockers: N-1 and N-2** — one root cause, one fix. F-1..F-4 are closed and
the persona×allergen transport works; once a person's allergens and the drafted
foods are reconciled instead of silently colliding, this is releasable.

## Fix round 2 (claude opus findings)

- **N-1/N-2 (Medium) — allergen collision is now a visible rejection.**
  `resolve_candidate` checks the chosen person's allergen tags against the
  bound plate's catalog tags BEFORE realization: a clash returns
  `Rejected(reason="allergen_clash")` instead of either logging an allergic
  food (composite) or silently stripping the allergy to keep the item
  (evaluate). `_realize` applies the chosen person's allergies/persona only
  after that check. Tests:
  `test_person_allergen_clash_is_rejected_visibly` — composite:fay+milk and
  evaluate:fay+milk both reject with `("allergen_clash", family)` and zero
  acceptances; non-colliding drafts still work (cam knife test, fay/mixed
  tests use an egg/milk-free pool catalog).
- **N-3 (Low)** — the dead `windows=...` Material argument and its misleading
  comment are dropped from `_realize_evaluate` (evaluate plate windows are
  plate-derived downstream).
- **N-4 (Low)** — CLI labeling narrowed: the script now runs `_parse_spec`
  first and labels only parse-phase failures "batch spec rejected: …";
  mid-run `run_batch` failures keep their own reporting.
  Tests: `test_bad_recipe_person_exits_cleanly`,
  `test_items_recipe_without_synthetic_exits_cleanly`.
- **Demo re-probe** (catalog-v2, synthetic, composite:roster-cam +
  recommend:roster-fay): composite accepted with persona cut / allergies
  ('egg',); fay recommends accepted with ('milk',); any clashing candidate
  would surface as `allergen_clash`. `recommend_coverage(personas=("cut",
  "everyday"))` → missing_personas == (), egg/milk both covered.
```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1332 passed in 51.74s        # 0 failed (was 1329; net +3 tests)
```
