# Spec: per-family recipe channel for batch item production (issue 15)

**Status:** decided by coordinator (issue 15 基建 #2, code side). Neutral transport — the specific
recipe VALUES (which family gets which knife/occasion/shell/tier) are issue-15 design, but the
ability to PASS a recipe through the batch path is required regardless.

## Problem

Verified (issue 15 probes): evaluate-unfit needs `knife="allergy"` + allergy catalog + rewriter;
leftover recommend needs `scene="leftover"` + `prior_logs`; tier needs `tier=` per item. `generate_one`
supports all of these per-item, and the constructibility matrix proved each shape is producible. But
the BATCH path (`run_batch` → `resolve_candidate`) has **no recipe channel**: `Candidate` carries only
`(items, query, family, persona, pool_id, steps)` and `_build_jobs` draws only `(family, pool)` from
`family_quotas`. So nobody can bulk-produce the floor shapes — the batch can only make "family-
default" items (log, evaluate-fit, template recommend/update, composite).

## Change (transport only; default behavior unchanged)

1. `types.Candidate` gains optional recipe fields (defaults keep every existing caller intact):
   `knife: str | None = None`, `occasion: str | None = None`, `shell: str | None = None`,
   `scene: str = "empty"`, `tier: str = ""`.
2. `resolver` dispatch: `_realize_evaluate` honours `candidate.knife` (knife constraint plumbing —
   it may already accept knives via the single-item path; check how evaluate knives are expressed
   today and wire candidate.knife to the same branch, defaulting to no knife for old callers);
   `_realize_recommend` honours `candidate.occasion` (default from query) and `candidate.shell`;
   `_realize_update` honours `candidate.scene`/`candidate.occasion` if it has scene semantics;
   every realize path forwards `candidate.tier` into the Task (tier channel from 9643b4f).
   IMPORTANT: `scene="leftover"` for recommend needs `prior_logs` — the resolver today resolves a
   single candidate; plumb a resolver-side source of prior logs (the batch's already-accepted log
   tasks for the same roster person) OR document that leftover via batch needs
   composite log+recommend (which already carries the ledger geometrically). Decide the minimal
   correct option; document which leftover carrier the batch supports first.
3. `run_batch._build_jobs`: accept an optional per-family recipe mapping in batch_spec, e.g.
   `"family_recipes": {"evaluate": {"knife": "allergy", ...}, "recommend": {"scene": "leftover"}}`,
   and store it on `_PoolJob` so `_run_jobs` can stamp it onto each Candidate before
   `resolve_candidate`. Default empty → behavior identical to today.
4. `scripts/generate_batch.py`: optional `--recipe family:key=value` (repeatable) parsed into the
   same mapping; `--synthetic` runs pass it through.
5. Tests: a small synthetic batch with `family_recipes={"evaluate": {}, "recommend": {}}` (empty
   recipes → same as today); one recipe that sets `tier` for evaluate and verifies the frozen
   output carries it; one evaluate recipe with a knife that produces an unfit (reuse the verified
   allergy-knife fixture if the synthetic catalog can supply it — if the batch synthetic catalog
   lacks an allergen food, the knife rejects cleanly and that is documented, not a failure).

## Definition of done

1. New tests pass; full suite 0 failed (expect 1301+).
2. A synthetic batch with per-family recipes (tier/knife/occasion) runs end to end; output tasks
   carry the recipe's effects (tier set; knife-driven unfit or clean rejection documented).
3. Commit "pipeline: " prefix. Do NOT push.
4. Append a section to reports/spec-batch-families.md or a new reports/impl-recipe-channel.md.
5. Do NOT touch docs/adr, data/splits (except own draft output), *.sqlite, scorer.py,
   validator.py, review_harness.py, quality_gates.py.

Work autonomously. If a piece is genuinely blocked by missing data (e.g. no allergen food in the
batch synthetic catalog), implement the transport, document the fixture limit, and stop with an
exact report.