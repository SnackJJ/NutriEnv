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

## Honest probe (real catalog-v2, 15 seeds × items∈{1,2,3})

| person (exclude) | items | unfit | allergen_clash | fit-gate/shortfall |
|---|---|---|---|---|
| roster-cam (egg) | 1 | 0 | 0 | 15 |
| roster-cam (egg) | 2 | 0 | 0 | 15 |
| roster-cam (egg) | 3 | **1** | 0 | 14 |
| roster-kim (soy) | 3 | **1** | 0 | 14 |

The mechanism claim holds end to end on the real catalog (unfit items ARE
produced), but the fit-window residual dominates: random plates rarely land
inside a specific person's meal-slot kcal window (acceptance ~1/15 per draw at
items=3). Zero allergen_clash at items≥2 (the exclusion keeps the carrier out
of the plate; only single-food draws that ARE the carrier can clash, and
pool_allergen's swap-in makes that likely at items=1). Bulk production needs
issue-15 plate/window tuning (e.g. occasion or explicit-gram sizing) — this
commit delivers the transport plus a real, reproducible unfit.

## Verification

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1337 passed in 63.13s        # 0 failed (was 1335; +2 tests)
```
