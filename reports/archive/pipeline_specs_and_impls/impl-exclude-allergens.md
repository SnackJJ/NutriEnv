# Impl report: exclude_allergens recipe hint (fit→knife plate construction)

Spec: `reports/spec-exclude-allergens.md`. Commit on main, prefix "pipeline:".

## What changed

- `expander.py` `synthetic_expander(..., exclude_allergens: tuple[str,...] | None)`:
  the non-composite plate loop skips pool foods whose catalog allergen tags
  intersect the excluded set; shortfall below `items` → fail-closed empty
  payload. Defaults None → today's behavior. Composite path unchanged (owns
  its plate); the update family's carrier pick is deliberately independent
  (its semantics REQUIRE the allergen food in the oracle).
- `run_batch`: `exclude_allergens` added to evaluate/recommend/update recipe
  keys (log/composite don't take a plate hint — absent from the key set per
  the fail-closed habit). Values are comma/space-separated tags normalized via
  `normalize_tags`; unparseable/empty refused at parse. It is an expander hint
  (`_EXPANDER_HINTS`), converted to a tag tuple in `_expand_one`; the existing
  non-synthetic-expander guard covers it automatically.
- `scripts/generate_batch.py`: passes through generically.

## Tests

- Unit: mixed pool + `exclude_allergens=("egg",)`, items=2 with only one
  non-egg speakable food → empty payload; items=1 → plate = the non-egg food.
- End-to-end (deterministic fixture, cam's cut-dinner slot [390.2, 520.3]):
  knife=allergy + person=roster-cam + pool_allergen=egg + exclude_allergens=egg
  + items=2 + tier=single → accepted unfit: reject verdict, empty last_plan,
  evaluated_plan = non-egg plate + exactly ONE egg carrier added by the knife,
  reasons == bind ('allergy', 'kcal_hi'), `validate_draft == []`,
  `evaluate_unfits` counts it; freeze→load clean.

## Honest probe (real catalog-v2, PRODUCTION path — occasion supplied)

**Methodology (corrected):** the harness mirrors `_expand_one`: knife recipes
supply `occasion="dinner"` to `synthetic_expander` (the spoken "for <meal>"
clause feeds `occasion_from_query`). An earlier table ran resolve-only without
an occasion, so every draw failed at "recommend/knife query names no meal
occasion" — that table measured a broken harness, not the pipeline. Seeds
0..29, one pool per seed (`sample_pools(seed=seed)`), persons roster-cam
(exclude egg) / roster-kim (exclude soy), resolve via `resolve_candidate` with
`knife=allergy, person=…, tier=single`.

**Matrix** (cam/egg, items=2, seeds 0..29):

| config | unfit / 30 | reasons |
|---|---|---|
| no pool_allergen, no occasion | 0 | unresolvable ×30 |
| pool_allergen, no occasion | 0 | unresolvable ×30 |
| no pool_allergen, occasion | 0 | unresolvable ×30 |
| **pool_allergen + occasion** | **2** | unresolvable ×28 |

**Sweeps on the production path** (pool_allergen + occasion unless noted):

| sweep | unfit / 30 each |
|---|---|
| cam/egg items=2 by occasion | breakfast 6 · lunch 2 · dinner 2 |
| cam/egg dinner by items | items=1 → 1 · items=2 → 2 · items=3 → 3 |
| kim/soy dinner items=2 | 4 |
| cam/egg dinner items=2, seeds 30..59 | 4 |

**Current guidance:** `items=2 + occasion=dinner` yields ≈2/30 per seed range
(never 0 across ranges tried); occasion choice moves the number materially
(breakfast 6/30 for cam); yield grows with items over this sample. The
mechanism is proven end to end both here and in the deterministic fixture test
(`test_exclude_allergens_recipe_produces_the_knife_unfit`): reject envelope,
empty last_plan, one knife-added carrier, reasons == bind. Fit-window sizing
(plate energy vs person/slot) remains the dominant residual — issue-15 design.

## Verification

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1337 passed in 63.13s        # 0 failed (was 1335; +2 tests)
```
