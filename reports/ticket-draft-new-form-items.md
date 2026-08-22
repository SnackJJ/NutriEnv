# Next ticket draft: v1.0 new-form item production (Phase 5/6 forward)

**Drafted by coordinator** (2026-08-22, after batch-families ACC). This is a design-input for the
next issue ticket — NOT an implementation order. Contents are the floor shapes the new exam must
cover, with the recipe clues verified from existing code/tests.

## Context (verified)

- Archived `v1.0-gold` (20-item pilot) covers log 14 + evaluate-fit 6 only; on ADR 0016 floors:
  leftover **0/24**, constrained **0/8**, evaluate-unfit **0/8**, evaluate tier **0 across all 6
  tiers**, no recommend/update/composite items.
- Batch orchestrator now supports all five families (0136ab4/343399a, codex ACC): `generate_batch
  --family recommend/update/composite` works (synthetic smoke 5/5 accepted, validate_draft []
  each).
- `generate_one` supports all five families and the recipe parameters below.

## Floor shapes to produce (ADR 0016/0017 targets)

| Shape | Target | Recipe clue (verified in tests) |
|---|---|---|
| Evaluate-unfit (reject + empty plan, closed reason set) | ≥8 | `generate_one(family='evaluate', knife='allergy', rewriter=make_unfit_rewriter(...))` → `last_verdict=='reject'`, empty `last_plan`, reasons == `bind_evaluate_reasons(...)`; see tests/test_generate_one_evaluate.py:170-192. |
| Constrained Recommend (unpassable windows / allergy trap / leftover) | ≥8 | Single-family recommend with unpassable pinned windows, or allergy-trap named dish; `constrained_recommends` asks from item (fitting_plan none / ledger remainder / named-dish trap). |
| Leftover Recommend geometry | ≥24 | Composite (log+recommend) carries parent ledger + child pinned remainder windows; also `scene`/`prior_logs` variants of single recommend. Fallback-rec leftovers if needed. |
| Evaluate tier coverage | all 6 tiers | single / pair / triple / long / explicit_grams / synonym — evaluate mill needs tier-driven shells (issue 05 furniture + `evaluate_tier_coverage` gates). |
| Composite | 36 of 240 | already constructible (10); needs counts/roster allocation per ADR 0016. |
| Recommend single-family | 72 | template shells (_RECOMMEND_SHELLS_BY_OCCASION); free-plan with meal-slot windows. |
| Update single-family | 36 | add-allergy / weight / phase / fatigue templates (08). |

## Open design questions (resolve in the ticket)

1. Does the new exam REPLACE v1.0-gold or extend it? (User: gold is archived; new forms are the
   subject — implies a NEW freeze file for the new-form set, possibly the 240.)
2. Recommend single-family leftover: which shell/scene combination produces the ledger-scene
   geometry (24 leftover)? Verified clue: `scene` + `prior_logs`/`prior_ledger` params on
   generate_one; composite log+recommend already does remainder-after-log.
3. Evaluate tier shells: issue 05 built evaluate knives; tier labels (single/pair/triple/long/
   explicit_grams/synonym) must map to generation recipes + realize rows — check
   `evaluate_tier_coverage` contract and `test_quality_gates` for the tier names.
4. Quota allocation within 240: log 60 / evaluate 48 / recommend 72 / update 36 / composite 36
   (ADR 0016 table) — plus floors inside evaluate/recommend. Confirm/override numbers.
5. Live (LLM-expander) batches: batch families doc notes LLM recommend/update prompt shells are
   NOT wired in build_system_prompt yet — the ticket must either wire them or ship synthetic-only
   first (explicit decision).

## Evidence to reuse

- reports/spec-batch-families.md, reports/impl-batch-families.md (5-family batch working).
- reports/issue-consistency-audit.md (gap table).
- tests/test_generate_one_evaluate.py (unfit recipe), tests/test_generate_one_composite.py
  (composite recipes), tests/test_band_freeze_replay.py (freeze→load gate).
- scripts/run_pilot_20.py build_pool_plan (pilot slot table as a starting shape).

## Not yet decided

- Batch size / seed / model routing for the production run (uses real expander+judge+review,
  quota-heavy). Pilot used live multi-model expander; the new-form run likely does too.
- Whether the new-form set freezes as one 240 (incl. composite 36) or as staged files.
## Constructibility matrix probe (2026-08-22, synthetic batch path)

`generate_batch --synthetic --family {log,evaluate,recommend,update,composite} --count 2
--seed 20260822` → pools=10 candidates=10 accepted=9 (1 code_gate honest rejection).
Output analyzed with modern quality gates:

| shape | produced via batch | validate | notes |
|---|---|---|---|
| log | 2/2 | 0 issues | ledger True |
| evaluate-fit | 2/2 | 0 issues | unfit NOT produced by default synthetic path |
| recommend | 2/2 | 0 issues | plan_windows pinned |
| update | 2/2 | 0 issues | |
| composite log+recommend | 1/1 | 0 issues | **hits leftover AND constrained** (ledger True, sub 2, pinned child) |

- leftover/constrained floor geometry IS producible (composite log+recommend).
- evaluate-unfit needs the knife=allergy + allergy catalog + rewriter recipe
  (tests/test_generate_one_evaluate.py:170-192) — not produced by default synthetic.
- Evaluate tier labels (6) need tier-driven shells — none yet.

## Matrix completion (2026-08-22, issue 15 #1 DONE)

evaluate-unfit recipe verified precisely (knife="allergy" + allergy catalog +
_rewrite_named; tests/test_generate_one_evaluate.py:170-192 pattern):
4/4 seeds → last_verdict="reject", last_plan=[], reasons={allergy,
protein_g_hi}, validate_draft==[], `evaluate_unfits` counts, tier
carried. Evaluate tier channel verified for all six EVALUATE_TIERS
(single/pair/triple/long/explicit_grams/synonym): each producible with
task.tier carried + validate clean (needs generate_one tier= from 9643b4f).

**Full constructibility matrix — all shapes producible:**

| shape | recipe | status |
|---|---|---|
| log | generate_batch --synthetic family=log | ✓ |
| evaluate-fit | family=evaluate | ✓ |
| evaluate-unfit | knife=allergy + allergy catalog + rewriter | ✓ (4/4) |
| evaluate tier ×6 | tier= param (9643b4f) | ✓ all six |
| recommend | shell=rec-* occasion | ✓ pinned windows |
| update | family=update (add-allergy evidence) | ✓ |
| composite log+recommend | steps=(log,recommend) | ✓ leftover+constrained |

Issue 15 checkbox #1 (constructibility matrix) is satisfied by probe evidence;
the production run needs the main-agent rulings on the 5 open questions.

## Leftover single-family Recommend recipe verified (issue 15 #4 probe)

`scene="leftover" + prior_logs=[same-roster-person prior log]` on
generate_one family=recommend → s0.ledger non-empty (copied provenanced Log
tails, ADR 0017 no-shadow-meals), plan_windows pinned, `leftover_recommends`
counts the id, validate_draft == []. Dropped cleanly with
reason="no_ledger" when no parent log exists (foreign_log for another
person's tail). So the 24-leftover floor has BOTH carriers:
composite log+recommend (10) and single-family scene=leftover recomends.

## ADR 0016 quota table verified against quota_ledger (issue 15 #2 code side)

log 48 / evaluate 48 / recommend 72 / update 36 / composite 36 = 240 exactly.
`quota_ledger` accepts the full 240 (single-family classified per family,
composite counted to exactly 36, ≤36 and ≤240 ceilings enforced). No code
gap for the ADR 0016 allocation — only the main-agent confirmation of the
numbers remains (ADR 0016 shows recommend 72, evaluate 48, update 36,
composite 36; log = the remaining 48).

Note: the ticket says "log 60" earlier — ADR 0016's own table sums to
recommend 72 + evaluate 48 + update 36 + composite 36 = 192, so log is 48
(not 60) for a 240 exam. Flag for the main-agent ruling: log 60 would
exceed 240; correct number is 48.
