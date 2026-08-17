# Pilot 20 report (v1.0-gold)

Pipeline version: `v1.0-gold`. Catalog: `data/fdc/catalog-v1.sqlite` sha256=`f49e4f904905abbb8b4ebb02c908935f01776280a2c00b3de1a3e890cad5ae91`. Seed: `20260817`.

## Pool plan

Deterministic 20-slot table in `scripts/run_pilot_20.py:build_pool_plan`. Single-food log slots are size-1 pools (素材固定 → 择优). Meal slots pad anchors to 8 speakable foods. Same seed always yields this plan; live LLM text is not byte-stable.

| slot | family | kind | persona | foods | target key | evaluate row |
|---|---|---|---|---|---|---|
| log-s-thick | log | single | everyday | 2705832 | thick | — |
| log-s-thin | log | single | everyday | 2705828 | thin | — |
| log-s-floz | log | single | everyday | milk_whole | fl_oz | — |
| log-s-cup | log | single | everyday | soy_milk | cup | — |
| log-s-slice | log | single | everyday | whole_wheat_bread | slice | — |
| log-s-qns | log | single | everyday | oats | qns | — |
| log-s-egg | log | single | gym | egg | piece | — |
| log-s-chk | log | single | gym | chicken_breast | cup | — |
| log-m-01 | log | meal | everyday | apple, cheddar, peanut_butter | — | — |
| log-m-02 | log | meal | everyday | banana, orange, avocado | — | — |
| log-m-03 | log | meal | everyday | tuna, potato, olive_oil | — | — |
| log-m-04 | log | meal | everyday | pasta, spinach, broccoli | — | — |
| log-m-05 | log | meal | gym | pasta, cheddar, orange | — | — |
| log-m-06 | log | meal | gym | chicken_breast, white_rice, broccoli | — | — |
| eval-01 | evaluate | meal | everyday | tuna, white_rice, broccoli | — | ev-tuna-rice |
| eval-02 | evaluate | meal | everyday | tofu, white_rice, spinach | — | ev-tofu-rice |
| eval-03 | evaluate | meal | everyday | egg, oats | — | ev-egg-oats |
| eval-04 | evaluate | meal | gym | banana, greek_yogurt | — | ev-gold-snack |
| eval-05 | evaluate | meal | everyday | avocado, egg, spinach | — | ev-tri-avocado-eggs-spin |
| eval-06 | evaluate | meal | gym | milk_whole, oats | — | ev-pair-milk-oats-oz |

## Throughput

- pools: 20
- expander candidates produced: 21
- accepted: 20
- family counts: {'evaluate': 6, 'log': 14}
- persona counts: {'everyday': 14, 'gym': 6}

### Rejection reasons

| reason | count |
|---|---|
| implausible | 3 |
| unresolvable | 3 |
| validate_draft | 2 |
| coverage_miss | 1 |
| duplicate | 1 |
| schema | 1 |

### Per-model quality

| model | produced | accepted |
|---|---|---|
| deepseek-v4-flash-0731 | 4 | 2 |
| deepseek-v4-pro-0813 | 3 | 2 |
| evaluate-row | 0 | 6 |
| fallback-table | 0 | 4 |
| glm-5.2 | 3 | 2 |
| kimi-k2.7-code | 4 | 1 |
| qwen3.8-2.4t-a95b | 4 | 2 |
| qwen3.8-max | 3 | 1 |

## Review-harness anomalies (人审 input)

The first freeze keeps every gate-passed item. Drop after review with `scripts/run_pilot_20.py --drop <id,...>`.

| id | reasons | query |
|---|---|---|
| v10-log-0001 | unparseable, low_consistency, low_entailment | Please log a thick serving of beef. |
|  | scores c=1.0 n=5.0 e=1.0 disagree=0.0 | |
| v10-log-0006 | unparseable | I had a serving of oatmeal this morning, please log it. |
|  | scores c=5.0 n=5.0 e=5.0 disagree=0.0 | |
| v10-log-0018 | unparseable | I had two cups of spaghetti with a cup of grilled chicken and a cup of broccoli for dinner. |
|  | scores c=5.0 n=5.0 e=5.0 disagree=0.0 | |

## Human review (issue 10 人审)

| id | verdict | note |
|---|---|---|
| v10-log-0007 | DROP | Ungrammatical 'a piece of eggs' — the defect the review harness should catch. Not gold. |
| v10-log-0001 | KEEP | thick serving is handbook-correct; naturalness=5.0. Low c/e is models reading 'beef' as generic ground beef vs sirloin steak — acceptable ambiguity. |
| v10-log-0006 | KEEP | Single-model unparseable glitch; other model 5/5/5; natural query. |
| v10-log-0018 | KEEP | Single-model unparseable glitch; other model 5/5/5; natural multi-food query. |

4 flagged → 1 dropped (0007) → 1 regenerated (reuse v10-log-0007). Remaining flags: 0001 / 0006 / 0018 kept.

## Replacement

- slot `log-s-egg` → `v10-log-0007` (reused dropped id).
- query: Logged two eggs for my post-workout meal.
- foods: Egg, whole, raw [2707152] piece 100.0g
- expander model: `deepseek-v4-flash-0731`
- review: clean

| attempt model | reason | query |
|---|---|---|
| deepseek-v4-flash-0731 | accepted:clean | Logged two eggs for my post-workout meal. |

人审负担: **3** / 20 still flagged after drop/replace.

## Final items

Every oracle gram passed `validate_oracle_grams` (freezer gate): each amount is a catalog-v1 PortionFact multiple.

| id | family | persona | foods + keys + grams | expander model | query |
|---|---|---|---|---|---|
| v10-log-0001 | log | everyday | Beef, steak, sirloin, NS as to fat eaten [2705832] thick 240.0g | kimi-k2.7-code | Please log a thick serving of beef. |
| v10-log-0002 | log | everyday | Beef, steak, ribeye, NS as to fat eaten [2705828] thin 180.0g | qwen3.8-2.4t-a95b | Please log that I had a thin serving of beef. |
| v10-log-0003 | log | everyday | Milk, whole [2705385] fl_oz 30.5g | fallback-table | Please log 1 fl oz of milk for lunch. |
| v10-log-0004 | log | everyday | Soy milk, sweetened [2705404] cup 244.0g | deepseek-v4-pro-0813 | I had a cup of soy milk. |
| v10-log-0005 | log | everyday | Bread, whole wheat [2707709] slice 24.0g | deepseek-v4-flash-0731 | Log a slice of whole wheat bread. |
| v10-log-0006 | log | everyday | Oats, raw [2708489] qns 10.0g | glm-5.2 | I had a serving of oatmeal this morning, please log it. |
| v10-log-0007 | log | gym | Egg, whole, raw [2707152] piece 100.0g | deepseek-v4-flash-0731 | Logged two eggs for my post-workout meal. |
| v10-log-0008 | log | gym | Chicken, broilers or fryers, breast, meat only, cooked, roasted [171477] cup 140.0g | qwen3.8-2.4t-a95b | Log a cup of chicken for my training meal. |
| v10-evaluate-0009 | evaluate | everyday | Fish, tuna, light, canned in water, without salt, drained solids [171986] can 165.0g; Rice, white, cooked, no added fat [2708408] cup 158.0g; Broccoli, raw [2709643] cup 90.0g | evaluate-row | Evaluate this as my plan: a can of tuna, a cup of rice, and a cup of broccoli. |
| v10-evaluate-0010 | evaluate | everyday | Tofu, firm, prepared with calcium sulfate and magnesium chloride (nigari) [172448] cup 126.0g; Rice, white, cooked, no added fat [2708408] cup 158.0g; Spinach, raw [2709614] cup 25.0g | evaluate-row | Submit this as the plan: a cup of tofu, a cup of rice, and a cup of spinach. |
| v10-evaluate-0011 | evaluate | everyday | Egg, whole, raw [2707152] piece 100.0g; Oats, raw [2708489] cup 80.0g | evaluate-row | Evaluate this as my plan: two eggs and a cup of oats. |
| v10-evaluate-0012 | evaluate | gym | Banana, raw [2709224] piece 126.0g; Yogurt, Greek, nonfat milk, plain [2705424] qns 150.0g | evaluate-row | Check this snack for me: a banana and 150g of Greek yogurt. |
| v10-evaluate-0013 | evaluate | everyday | Avocado, raw [2709223] cup 150.0g; Egg, whole, raw [2707152] piece 100.0g; Spinach, raw [2709614] cup 25.0g | evaluate-row | Does this work as brunch: a cup of avocado, two eggs, and a cup of spinach? |
| v10-evaluate-0014 | evaluate | gym | Milk, whole [2705385] cup 244.0g; Oats, raw [2708489] oz 56.7g | evaluate-row | Evaluate this as breakfast: a cup of milk and about 2 ounces of oats. |
| v10-log-0015 | log | everyday | Apple, raw [2709215] piece 165.0g; Cheese, Cheddar [2705709] slice 9.0g; Peanut butter [2707537] tbsp 16.0g | qwen3.8-max | Please log that I ate one apple, one slice of cheddar cheese, and one tablespoon of peanut butter. |
| v10-log-0016 | log | everyday | Egg, whole, raw [2707152] piece 100.0g; Cheese, Cheddar [2705709] slice 9.0g; Banana, raw [2709224] piece 126.0g | deepseek-v4-pro-0813 | I ate 2 eggs, 1 slice of cheddar cheese, and a banana for breakfast. |
| v10-log-0017 | log | everyday | Fish, tuna, light, canned in water, without salt, drained solids [171986] can 165.0g; Potato, baked, NFS [2709383] piece 230.0g | fallback-table | Please log a can of canned tuna, and a piece of baked potato for lunch. |
| v10-log-0018 | log | everyday | Pasta, cooked [2708357] cup 280.0g; Chicken, broilers or fryers, breast, meat only, cooked, roasted [171477] cup 140.0g; Broccoli, raw [2709643] cup 90.0g | glm-5.2 | I had two cups of spaghetti with a cup of grilled chicken and a cup of broccoli for dinner. |
| v10-log-0019 | log | gym | Pasta, cooked [2708357] cup 140.0g; Cheese, Cheddar [2705709] slice 9.0g | fallback-table | Please log a cup of spaghetti, and a slice of cheddar cheese for lunch. |
| v10-log-0020 | log | gym | Chicken, broilers or fryers, breast, meat only, cooked, roasted [171477] cup 140.0g; Rice, white, cooked, no added fat [2708408] cup 158.0g | fallback-table | Please log a cup of chicken, and a cup of rice for lunch. |

## Coverage

| key | count |
|---|---|
| qns | 2 |
| thick | 1 |
| thin | 1 |
| fl_oz | 1 |
| cup | 17 |
| slice | 4 |

Coverage check: qns / thick / thin / fl_oz / cup / slice each ≥ 1.

## Gym grams

resolve_portion accepts '150 g' / '150 grams', but validate_oracle_grams requires a catalog-v1 PortionFact multiple (×0.5/1/1.5/2, plus 2 oz). Gym items therefore stay on PortionFact keys unless the gram amount is already a table value (e.g. greek yogurt 150 g = qns).

## Handbook

`HANDBOOK_VOCABULARY` is covered by `_SYSTEM_V1_TAIL`. Pilot expressions stay on cup / tbsp / tsp / slice / piece / can / fl_oz / serving / thick / thin / regular / grams / ounces.

## D4 / evaluate

`validate_draft` still requires evaluate queries to match an `EVALUATE_ROWS` row (D4). Live expander queries therefore fail that gate and the pilot accepts the planned realization-row fallback. Resolver / Judge / `validate_oracle_grams` / review still run on the accepted evaluate items.

## Re-freeze

```
.venv/bin/python scripts/run_pilot_20.py --drop <id,...>
```

Reads `reports/pilot-20-state.json`, drops those ids, rewrites `data/splits/v1.0-gold.json` and this report. No network.

## Landing / exam switch

- `EXAM_SPLIT_PATH` now points at `data/splits/v1.0-gold.json`.
- `scripts/landing_verify.py` keeps the v0.5 old-key / replay / validate_draft / oz checks, then `load_exam` + `validate_draft` the 20 v1.0 items.
- `_SYSTEM_V1_TAIL` was not changed: every spoken measure in the pilot is already in the v1 handbook.

## Verification (10b)

- Dropped `v10-log-0007` ("a piece of eggs"); regenerated the same id via live expander.
- Replacement: `v10-log-0007` gym / egg / piece / 100 g / `deepseek-v4-flash-0731` / "Logged two eggs for my post-workout meal." / review clean.
- `load_exam()` → 20 items (14 log / 6 evaluate).
- Coverage: qns 2, thick 1, thin 1, fl_oz 1, cup 17, slice 4.
- `.venv/bin/python -m pytest -q` → **921 passed**.
- `.venv/bin/python scripts/landing_verify.py` → **PASS**.
- `_SYSTEM_V1_TAIL` unchanged; `catalog.sqlite` and `v0.5-gold.json` untouched.

Freeze sha256 of `data/splits/v1.0-gold.json`: `0f463a4585a1630e0a5a44a5b5ff772830627b4a102613d917f07cb4cba558d2`.

