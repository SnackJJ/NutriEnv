# Spec: recipe guard at run_batch entry + CLI --synthetic awareness (N-1/N-2)

**Status:** decided by coordinator (closes claude-opus re-review tracking items N-1/N-2 from
reports/spec-recipe-items.md). Cheap fail-early improvement, not a defect fix: the per-job guard
(F-2 fix, run_batch.py:630) already fails closed, but with a mixed quota the recipe-free jobs are
in flight before the failure surfaces. Moving the check earlier prevents wasted LLM calls on real
batches.

## Change

1. `run_batch` entry (right after `_parse_spec`, before `_build_jobs`): if the parsed spec's
   `family_recipes` contains `items` or `amount_path` for any family AND `expander is not
   `synthetic_expander`, raise ValueError("recipe items/amount_path require the synthetic
   expander (--synthetic); the LLM expander cannot honour them yet") — same message as the per-job
   guard, so tests can share the string. The per-job guard stays as defence in depth.
2. `scripts/generate_batch.py`: with `--recipe FAMILY:key=value`, if any key is `items` or
   `amount_path` AND `--synthetic` was not passed, fail at CLI parse time (argparse error or a
   clear ValueError before any LLM call). The flat RECIPE_KEYS there can then keep advertising the
   keys (the actionable `--synthetic` hint is in the message).
3. Tests: a mixed-quota spec (evaluate:1 + log:5, recipe only on evaluate with items=3) with a
   fake non-synthetic expander → run_batch raises at entry (before sampling — assert no expander
   call happened, e.g. a counting fake); CLI `--recipe evaluate:items=3` without `--synthetic`
   → errors; with `--synthetic` → accepted.
4. Existing tests keep passing (the per-job guard tests stay; entry check is additive).

## Definition of done

1. Tests pass; full suite 0 failed (expect 1320+).
2. Commit "pipeline: " prefix (e.g. "pipeline: fail recipe expander mismatch at run_batch entry and CLI (N-1/N-2)"). Do NOT push.
3. Append a short section to reports/spec-recipe-items.md closing N-1/N-2 with evidence.
4. Do NOT touch: docs/adr/*, data/splits/*, *.sqlite, scorer.py, validator.py, review_harness.py,
   quality_gates.py.

Work autonomously. If the entry check location is awkward (expander is a parameter — easiest), keep
it after the validator parameter checks. If blocked, stop and report.