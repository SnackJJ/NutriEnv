# Spec: evaluate tier authoring channel in generate_one

**Status:** decided by coordinator (issue 15 infrastructure, independent of the open design
questions — tier names/floors are fixed by migrated v0.3 floors, not by the pending rulings).

## Problem

`Task.tier` exists (realize.py:164, default "") and `evaluate_tier_coverage` groups evaluate items by
it, but **`generate_one` has no tier parameter** — every mill-produced evaluate item freezes with
`tier=""`, so the ADR 0016 evaluate slice (48 items) can never satisfy the migrated tier floors
(single 7 / pair 11 / triple 11 / long 5 / explicit_grams 4 / synonym 3; total 41). Verified:
archived v1.0-gold's 6 evaluate items are all tier "" and `evaluate_tier_coverage` reports all six
missing.

## Change (data channel only — content design belongs to issue 15)

1. `generate_one(..., tier: str = "")` — new keyword parameter.
2. Thread `tier` into every `Task(...)` construction in generate_one.py (7 sites: lines ~328, 372,
   420, 487, 604, 755, 969). Simplest honest approach: pass `tier=tier` in each constructor call,
   OR — if the code flow makes that invasive — build the accepted Task and then use the existing
   `_retag(task, situations, persona)`-style helper to set tier. Prefer the least invasive correct
   option; do not touch the rejected paths.
3. Type: accept only `""` or a value in `EVALUATE_TIERS` (import from quality_gates) for family
   "evaluate"; raise ValueError otherwise (authoring discipline: nobody invents a tier).
   For non-evaluate families, `tier` must be `""` (ignore or raise — decide: raise, so callers can't
   accidentally tier a log).
4. `run_batch` / `generate_batch`: add an optional `--tiers`-style mapping is OUT OF SCOPE for this
   spec (issue 15 decides who assigns tiers). This spec only opens the generate_one channel so an
   authoring driver CAN pass tier.

## Tests (tests/test_generate_one_evaluate.py)

- `test_generate_one_evaluate_accepts_declared_tier`: `generate_one(family='evaluate', tier='pair',
  ...)` (reuse `_run_eval` helper with an override) → accepted Task has `task.tier == 'pair'`,
  `validate_draft(task) == []`, and `evaluate_tier_coverage([task])` counts pair.
- `test_generate_one_evaluate_rejects_unknown_tier`: `tier='bogus'` raises ValueError.
- `test_generate_one_log_rejects_tier`: `generate_one(family='log', tier='single', ...)` raises
  ValueError.
- Freeze round-trip: the tier survives `freeze_tasks` → `load_split` (assert loaded `.tier ==
  'pair'`) — check how existing freeze/load tests do it (tests/test_band_freeze_replay.py) and
  mirror minimally.

## Definition of done

1. Tests above pass; full suite /home/jzq/Projects/nutri-env/.venv/bin/python -m pytest -q → 0
   failed (expect 1296+).
2. Commit to main with "pipeline: " prefix (e.g. "pipeline: add evaluate tier authoring channel to
   generate_one"). Do NOT push.
3. Append a short section to reports/impl-batch-families.md (or new reports/impl-tier-channel.md)
   with evidence.
4. Do NOT touch: docs/adr/*, data/splits/*, *.sqlite, scorer.py, validator.py, review_harness.py,
   quality_gates.py (tier VALUES and floors are policy — not this change).

Work autonomously. If blocked, stop and report what is done.