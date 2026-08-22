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
