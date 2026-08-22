# Spec: make generate_one knife/leftover-unfit output reloadable (situations cleanup)

**Status:** decided by coordinator (closes claude opus final-review Low-4: "mill/batch situations
asymmetry"). Design authority: `split.py:153-155` rejects non-SITUATIONS situation values on
load; quality gates judge unfit/leftover from ORACLE GEOMETRY (evaluate_unfits reads
last_verdict/last_plan; leftover_recommends reads persona/ledger/child-tail) — no gate consumes
these situation tags.

## Problem

`generate_one` stamps three non-SITUATIONS situation tuples on knife/leftover-unfit evaluate
items (generate_one.py:901, :909, :956):

- `("evaluate_unfit", "leftover_under", "draft_only")`
- `("evaluate_unfit", "leftover_over")`
- `("evaluate_unfit", knife)`

None of `evaluate_unfit`/`leftover_under`/`draft_only`/`leftover_over` is in `SITUATIONS`
(`src/nutrienv/bench/situations.py`), so a knife/leftover-unfit item from the MILL cannot be
`load_split` reloaded — while the batch path (recipe channel) was already fixed to `situations=()`
in 188a2ee. The mill and batch producers disagree on the same contract. Verified: no gate or
freezer code reads these tags; only two tests assert their presence/absence
(test_generate_one_evaluate.py:377, :390).

## Change

1. generate_one.py: replace the three non-SITUATIONS situation tuples with `()` (unfit/leftover
   geometry lives in the oracle — `evaluated_plan`, `last_verdict=="reject"`, `last_plan==[]`,
   `last_reasons`, `bound_labels`; `leftover_over/under` remain visible via
   `oracle.bound_labels`, which tests already assert).
2. Update the two tests that asserted the tag presence/absence (lines ~377, ~390): assert the
   ORACLE geometry instead (e.g. `"leftover_under" not in oracle.bound_labels` for the
   `last_meal=False` draft case — already asserted at line 376; and for the `last_meal=True`
   case assert `"leftover_under" in oracle.bound_labels` instead of `"draft_only" in
   task.situations`).
3. Add a round-trip assertion: a knife-unfit and a leftover-unfit evaluate item from
   `generate_one` freeze→`load_split`→`validate_draft` cleanly (mirror the batch knife
   round-trip test in tests/test_run_batch.py). Use the existing evaluate test fixtures
   (tests/test_generate_one_evaluate.py helpers) and freezer pattern.
4. Confirm no other code path depends on the removed tags (grep-verified: none).

## Definition of done

1. Tests updated + new round-trip test pass; full suite 0 failed (expect 1312+).
2. Compare with batch: a generate_one knife item and a batch knife item both reload via
   `load_split` with `validate_draft == []` — producers now agree.
3. Commit "pipeline: " prefix (e.g. "pipeline: emit reload-valid situations on mill unfit items
   (align with batch recipe channel)"). Do NOT push.
4. Append a section to reports/impl-recipe-channel.md naming this as the Low-4 follow-up closed.
5. Do NOT touch: docs/adr/*, data/splits/*, *.sqlite, scorer.py, validator.py, review_harness.py,
   quality_gates.py (their unfit/leftover geometry reading is the REFERENCE, not a change).

Work autonomously. If a fixture can't round-trip (e.g. the mill knife item needs an allergy
catalog), document and use the closest real case.
**Status update:** implemented on main ("pipeline:" commit). The three
non-SITUATIONS tuples are now `()`, both tag tests assert oracle geometry,
and `test_mill_unfit_items_survive_freeze_load_round_trip`
(tests/test_generate_one_evaluate.py) covers freeze→load→validate_draft for a
knife-unfit and a leftover-unfit item. Full suite 1313 passed, 0 failed.

## Review (claude opus)

**Verdict: ACC.** The three enumerated tuples are `()`, all three sites emit
reload-valid items, the leftover semantics survive intact through freeze→load
via `oracle.bound_labels`, no consumer was missed, no test lost discriminating
power, and scope is clean. One adjacent defect found in the same function — the
mill's *fit* evaluate item still emits `("evaluate_fit",)` — is outside this
spec's scope and is raised below as an immediate follow-up, not a blocker.

### Axis 1 — correctness of replacing the tags with `()`

**No consumer missed.** Verified independently, not taken on trust:

- `draft_only` — zero code references anywhere in `src/`, `tests/`, `scripts/`.
  The only hits are prose in `reports/`. Dropping it loses nothing.
- `evaluate_unfit` — the only reader is `quality_gates._is_evaluate_unfit`
  (`quality_gates.py:237`), which reads the oracle (`last_verdict`,
  `last_plan`, `evaluated_plan`), never `task.situations`.
- `leftover_under` / `leftover_over` — these live in a **separate, frozen,
  validated vocabulary**: `Oracle.bound_labels` (`realize.py:146`, produced by
  `leftover_bound_labels` at `realize.py:394`), written by `freezer.py:222-223`
  and validated on load by `split.py:386` against exactly
  `{"leftover_over","leftover_under"}`. So the semantics do not merely
  "survive" — they round-trip through the frozen split. Probed:

  ```
  leftover-unfit item  bound_labels=('leftover_over','leftover_under')
                       freeze -> load -> bound_labels=('leftover_over','leftover_under')
  ```

**All three sites verified individually**, by instrumenting `_retag` to record
which branch fired:

```
site :900  leftover_under (was …,"leftover_under","draft_only")  situations=()  reload OK
site :912  leftover_over  (was "evaluate_unfit","leftover_over") situations=()  reload OK
site :957  knife          (was "evaluate_unfit", knife)          situations=()  reload OK
```

`validate_draft(loaded) == []` on all three.

**The round-trip test is genuine, not thinner than claimed** — but it is
narrower than the fix. `test_mill_unfit_items_survive_freeze_load_round_trip`
really does build two mill items, assert `last_verdict == "reject"` and
`situations == ()` on both, then `freeze_tasks` → `load_split` →
`validate_draft`. Its leftover item carries
`bound_labels=('leftover_over','leftover_under')`, and since `generate_one.py:894`
tests `leftover_under` first, it does exercise the former `draft_only` branch
(site :900) — the branch that mattered most. What it does not reach is the
`leftover_over`-only branch (site :912); that fixture (`white_rice` 965 g +
`knife="over_slot"`, the one `test_generate_one_evaluate_leftover_over_keeps_ordinary_plate`
uses) takes a different path. I probed that branch directly: `situations=()`,
`bound_labels=('leftover_over',)`, freeze→load OK, `validate_draft == []`. So
the site is correct — it is simply uncovered by the new test. Adding that third
fixture to the round-trip loop would close it.

### Axis 2 — do the producers agree?

For the shape the spec names, yes. A mill knife-unfit item and a batch recipe
knife-unfit item both freeze, `load_split`, and `validate_draft == []`.

They do **not** agree on the fit shape — see F-1.

### Axis 3 — test updates

Not weakened to tautologies, and no coverage lost.

- `:377` `assert "draft_only" not in earlier.accepted.situations` →
  `assert earlier.accepted.situations == ()` — strictly **stronger** (exact
  equality vs. absence of one member).
- `:390` `assert "draft_only" in task.situations` →
  `assert task.situations == ()`.

The second swap does remove a discriminating signal: both the `earlier` and
`last` cases now assert the identical `situations == ()`, so that pair of lines
no longer distinguishes them. The real behaviour under test —
*`leftover_under` fires only on the last meal* — is still fully covered, by the
pre-existing and unchanged pair `assert "leftover_under" not in
earlier.accepted.oracle.bound_labels` (`:376`) and `assert "leftover_under" in
task.oracle.bound_labels` (`:389`). That is the correct place for the signal
and it was already there, so the test name still matches what it proves. The
two `situations == ()` lines are now regression guards for the new invariant,
which is a fair role for them.

### Axis 4 — scope

`22f9231` touches four files: `reports/spec-unfit-situations.md`,
`reports/impl-recipe-channel.md`, `src/nutrienv/bench/pipeline/generate_one.py`,
`tests/test_generate_one_evaluate.py`. No ADR, `data/splits/*`, `*.sqlite`,
`scorer.py`, `validator.py`, `review_harness.py`, or `quality_gates.py` change —
their oracle-geometry reading stayed the reference, as the spec required.
`situations.py` and `split.py` are untouched, so the approved vocabulary was not
quietly widened. Judging (`Pass ⇔ end state == Oracle`) is unaffected.

### Finding

- **F-1 (Medium, out of this spec's scope) — the mill's *fit* evaluate item
  still emits a non-SITUATIONS tag** (`src/nutrienv/bench/pipeline/generate_one.py:886`).
  The sweep covered the three unfit tuples the spec enumerated; the draft built
  at `:880-889` carries `("evaluate_fit",)`, which is also not in `SITUATIONS`,
  and it is returned unretagged by the `if knife is None` path at `:919`. That
  is the mill's ordinary accepted evaluate item. Probed:

  ```
  evaluate fit (knife=None)  situations=('evaluate_fit',)
                             freeze -> load FAILS: unknown situations: ['evaluate_fit']
  evaluate knife-unfit       situations=()   reload OK
  evaluate leftover-unfit    situations=()   reload OK
  ```

  The batch channel's fit evaluate uses `situations=()` (`resolver.py:468`) and
  reloads. So the mill/batch asymmetry Low-4 named is narrowed, not eliminated:
  it now lives on the fit path instead of the unfit path.

  **Why this is not a blocker for this commit:** the spec scoped itself to
  knife/leftover-unfit output and the report's claim is correspondingly
  qualified ("a mill knife item and a batch knife item both reload cleanly") —
  nothing false is asserted. The defect is pre-existing and currently latent:
  `generate_one` is imported only by tests and `__init__`; neither
  `scripts/phase6_generate.py` nor `scripts/run_pilot_20.py` calls it, and no
  committed split under `data/` contains `evaluate_fit` (situation counts
  across all frozen splits: `fuzzy_portion` 116, `condition_suitability` 58,
  `conflict_windows` 47, `multi_item_log` 34, `unit_convert` 11,
  `near_synonym` 11, `ledger_gap` 9 — all valid). No shipped artifact is
  broken.

  **Why it should be closed next:** it is one line in the function just swept,
  fourteen lines above one of the fixes, and the new round-trip test is the
  natural place to catch it — but that test only builds unfit items, so it
  cannot. The moment anyone wires the mill to `freeze_tasks`, the most common
  evaluate shape fails to load. **Fix:** `()` at `:886` (the fit shape lives in
  `last_verdict == "accept"` + `evaluated_plan`, exactly as
  `_log_then_evaluate_fit` already reasons at `:450-452` when it deliberately
  emits the valid `("multi_item_log",)` instead), plus a fit item in the
  round-trip test's loop.

  Audited every remaining task-construction site in `generate_one.py` so this is
  the complete list: `:345`, `:391`, `:442` emit `("multi_item_log",)` (valid);
  `:511`, `:630`, `:783` emit `()`; `:417`'s `("evaluate_fit",)` is an internal
  draft whose oracle alone is reused — the Task it returns at `:442` is tagged
  `("multi_item_log",)`, so it never escapes. `:886` is the only leak.

### Note (non-blocking)

- The round-trip test does not cover the `leftover_over`-only branch (`:912`).
  Verified correct by probe; adding the existing `white_rice` 965 g +
  `over_slot` fixture to the loop would make all three fixed sites test-pinned
  rather than two.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_generate_one_evaluate.py -q
18 passed in 0.12s

$ .venv/bin/python -m pytest -q
1313 passed in 41.96s          # 0 failed
```

**RELEASE: the Low-4 follow-up (mill knife/leftover-unfit situations) is closed
and accepted.** F-1 (`evaluate_fit` on the mill's fit path) is a separate,
latent defect of the same class — recommended as the next commit, and required
before `generate_one` output is ever fed to `freeze_tasks`.

**F-1 follow-up (closed):** the mill's FIT evaluate items no longer stamp
`("evaluate_fit",)` either — both `_realize_eval` call sites (single-family
fit and the composite log+evaluate child draft) now emit `()`, so fit geometry
lives solely in the oracle (accept + exact evaluated meal). The tier
round-trip test's `replace(task, situations=())` workaround is gone, and a new
`test_generate_one_fit_items_survive_freeze_load_round_trip` freezes → loads a
tiered fit item cleanly. generate_one now emits only reload-valid situations
on every evaluate path. Full suite 1314 passed, 0 failed.
