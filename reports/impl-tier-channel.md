# Impl report: evaluate tier authoring channel in generate_one

Spec: `reports/spec-tier-channel.md`. Data channel only — tier CONTENT design
belongs to issue 15. Commit on main, prefix "pipeline:".

## What changed (`src/nutrienv/bench/pipeline/generate_one.py`)

- `generate_one(..., tier: str = "")` — new keyword parameter.
- Validation at entry: `tier` non-empty is accepted only when
  `family == "evaluate"` and `tier in EVALUATE_TIERS` (imported from
  `nutrienv.bench.quality_gates`); anything else raises `ValueError` — so a
  log/recommend/update/composite cannot be tiered and nobody can invent a
  tier name.
- Tier threaded into every accepted-Task construction:
  - evaluate path: `_evaluate_from_bound(tier=...)` → `_realize_eval(tier=...)`
    (both the fit draft and the knife-unfit rewrite) and both `_retag(...)`
    leftover branches; `_realize_eval` passes it to `realize_evaluate` and
    keeps it on the re-wrapped Task; `_retag` gained `tier=""` (keeps
    `task.tier` when empty, so existing callers are unaffected);
  - other families (always `""` by validation): direct `tier=tier` keyword on
    the log Task, `_log_then_recommend`, `_log_then_evaluate_fit`,
    `_update_then_recommend`, `_recommend_from_template`,
    `_update_from_template`.
- Rejected paths untouched. No changes to quality_gates.py, validator.py,
  scorer.py, review_harness.py, ADRs, or split data.

## Tests (`tests/test_generate_one_evaluate.py`, +4)

- `test_generate_one_evaluate_accepts_declared_tier` — `_run_eval(tier="pair")`
  → `task.tier == "pair"`, `validate_draft(task) == []`,
  `evaluate_tier_coverage([task]).counts["pair"] == 1`.
- `test_generate_one_evaluate_rejects_unknown_tier` — `tier="bogus"` raises.
- `test_generate_one_log_rejects_tier` — `family="log", tier="single"`
  raises.
- `test_evaluate_tier_survives_freeze_load_round_trip` — freezer payload
  carries `"tier": "pair"`; freeze→`load_split` reload keeps `.tier == "pair"`
  (mirrors test_band_freeze_replay minimally; note: the mill's authoring
  situation tag `"evaluate_fit"` is not split-reload vocabulary, so the
  round-trip strips situations — pre-existing, orthogonal to the tier
  channel).

## Verification

```
$ .venv/bin/python -m pytest tests/test_generate_one_evaluate.py -q
................                                                         [100%]
16 passed in 0.17s

$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1300 passed in 42.80s
```

(Previously 1296; +4 new tests, 0 failures.)
