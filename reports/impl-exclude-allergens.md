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

## Honest probe (real catalog-v2)

**Methodology:** seeds 0..29 (`sample_pools(seed=seed)`, one pool per seed),
persons roster-cam (exclude egg) and roster-kim (exclude soy), items ∈ {1..4},
resolve via `resolve_candidate` with `knife=allergy, person=…, tier=single`.
Measured in this checkout:

| person (exclude) | items=1 | items=2 | items=3 | items=4 |
|---|---|---|---|---|
| roster-cam (egg), unfit / 30 | 0 | 0 | 0 | 0 |
| roster-kim (soy), unfit / 30 | 0 | 0 | 0 | 0 |

Every non-shortfall draw was rejected by the fit gate (`unresolvable`): the
pre-knife plate must land inside the chosen person's meal-slot windows (e.g.
cam dinner kcal [390.24, 520.32]), and random 1–4 unit plates almost never do
(0/30 per config here). A 100-seed cam/items=2 run also gave 0/100. The
earlier "≈1 unfit per 15 draws" figure did not reproduce and is withdrawn;
an external review reported 4/15 at items=2 for seeds 0..14 — not reproduced
under the methodology above (likely a different resolve configuration).

Where the mechanism IS proven end to end: the deterministic fixture test
(`test_exclude_allergens_recipe_produces_the_knife_unfit`) produces a genuine
ADR 0017 unfit — reject, empty last_plan, exactly one knife-added carrier,
reasons == bind, `validate_draft == []`. Operator guidance: random-pool bulk
production is gated by the fit window, not by the carrier condition; yielding
reliably requires issue-15 plate/window design (occasion, explicit-gram sizing,
or person selection matched to drawn plates). Zero allergen_clash at items≥2
(exclusion keeps carriers out of the plate); items=1 can draft the swapped-in
carrier → visible `allergen_clash`.

## Verification

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1337 passed in 63.13s        # 0 failed (was 1335; +2 tests)
```
