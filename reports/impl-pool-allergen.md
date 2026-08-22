# Impl report: sample_pools allergen targeting + recipe pool_allergen knob

Spec: `reports/spec-pool-allergen.md`. Commit on main, prefix "pipeline:".

## What changed

- `sampler.py` `sample_pools(..., with_allergen: str | None = None)`: when
  set, pools are guaranteed to contain at least one food carrying the catalog
  allergen tag. **Implementation note (deliberate deviation from the spec's
  re-draw sketch):** bounded re-draws cannot satisfy the condition on a real
  catalog — with ~5394 eligible foods and a dozen egg carriers, eight redraws
  of an 8-food pool hit a carrier with probability ~1%. So after a draw
  without a carrier, ONE slot is swapped for `rng.choice(sorted(carriers))`
  (deterministic per seed, always succeeds). A tag no food carries still
  raises `ValueError("catalog has no food with allergen tag …")` fail-closed.
- `run_batch`: `pool_allergen` accepted in every family's recipe set; parsed
  as a non-empty string (unknown TAGS fail closed in `sample_pools` when the
  family's pools are drawn); threaded into that family's `sample_pools` call
  via `_build_jobs`; excluded from the Candidate stamps and expander hints
  (it is consumed at sampler level).
- `scripts/generate_batch.py`: `--recipe evaluate:pool_allergen=egg` passes
  through the generic FAMILY:KEY=VALUE parsing.

## Honest probe (knife=allergy + person=roster-cam + pool_allergen=egg +
items=1 + tier=single, catalog-v2 fixture and CLI)

```
CLI: pools=1 candidates=1 accepted=0 ; rejections: allergen_clash=1
fixture run: accepted [] ; rejected ['allergen_clash', 'unresolvable']
```

The carrier condition is now satisfiable (every drawn pool carries the tag;
asserted per-pool in `test_sample_pools_with_allergen_targets_carrier_pools`).
The residual is real and documented, not hidden:

1. The synthetic expander composes the FIRST N speakable pool foods — with
   items=1 the plate IS the carrier the swap-in placed, so cam (egg-allergic)
   clashes with her own plate → visible `allergen_clash` rejection.
2. When the plate avoids the carrier, the fit gate still applies: cam's
   cut-phase dinner slot must contain the pre-knife plate.

Both remaining knobs ("compose N foods excluding the person's carriers while
the pool keeps one", occasion/plate tuning for the fit gate) are issue-15
recipe design, exactly as the spec anticipated. No pass was faked.

## Tests

- `test_sample_pools_with_allergen_targets_carrier_pools` — every pool has ≥1
  egg-tag food on catalog-v2; unknown tag raises.
- `test_pool_allergen_recipe_feeds_the_sampler` — recipe reaches the sampler;
  acceptances (if any) must be allergy rejects over cam's profile; rejections
  ⊆ {unresolvable, allergen_clash}.

## Verification

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1334 passed in 52.28s        # 0 failed (was 1332; +2 tests)
```
