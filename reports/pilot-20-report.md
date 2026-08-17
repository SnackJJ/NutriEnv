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
- expander candidates produced: 46
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
| deepseek-v4-flash-0731 | 9 | 4 |
| deepseek-v4-pro-0813 | 7 | 3 |
| evaluate-row | 0 | 1 |
| fallback-table | 0 | 1 |
| glm-5.2 | 6 | 3 |
| kimi-k2.7-code | 8 | 3 |
| qwen3.8-2.4t-a95b | 8 | 4 |
| qwen3.8-max | 8 | 1 |

Routed around mid-run: deepseek-v4-pro-0813.

### Notes / provenance

18/20 items are live LLM expansions; 1 still `evaluate-row`; 1 still `fallback-table`.

## Rerun fallbacks (issue 10c)

Live multi-model expander, no table-phrase / evaluate-row fallback. Bounded retries per slot: 5. KEEP (already-LLM) items were not re-expanded.

- replaced: 8
- still-fallback: 2
- still-fallback slots: eval-04, log-m-05
- routed around: deepseek-v4-pro-0813

| slot | id | previous | model | fallback | review | query |
|---|---|---|---|---|---|---|
| log-s-floz | v10-log-0003 | fallback-table | deepseek-v4-flash-0731 | False | clean | I drank 1 fl oz of whole milk. |
| eval-01 | v10-evaluate-0009 | evaluate-row | deepseek-v4-pro-0813 | False | clean | Please evaluate my planned meal of a can of tuna, one cup of rice, and one cup of broccoli florets. |
| eval-02 | v10-evaluate-0010 | evaluate-row | deepseek-v4-flash-0731 | False | clean | Please evaluate my meal of one cup of firm tofu, one cup of steamed rice, and one cup of broccoli florets. |
| eval-03 | v10-evaluate-0011 | evaluate-row | glm-5.2 | False | clean | I'm planning to have two eggs, a cup of oatmeal, and an apple for breakfast — can you evaluate if this is a good meal? |
| eval-04 | v10-evaluate-0012 | evaluate-row | evaluate-row | True | all_retries_failed | Check this snack for me: a banana and 150g of Greek yogurt. |
| eval-05 | v10-evaluate-0013 | evaluate-row | qwen3.8-2.4t-a95b | False | clean | Can you evaluate my plan to have 1 cup of chicken, 1 cup of broccoli, and 1 piece of apple? |
| eval-06 | v10-evaluate-0014 | evaluate-row | qwen3.8-2.4t-a95b | False | clean | Can you evaluate my light training meal of a cup of oatmeal, a cup of milk, and one banana? |
| log-m-03 | v10-log-0017 | fallback-table | kimi-k2.7-code | False | clean | Log a baked potato with two slices of cheddar cheese and a cup of broccoli florets. |
| log-m-05 | v10-log-0019 | fallback-table | fallback-table | True | all_retries_failed | Please log a cup of spaghetti, and a slice of cheddar cheese for lunch. |
| log-m-06 | v10-log-0020 | fallback-table | kimi-k2.7-code | False | clean | Log a cup of chicken, a cup of rice, and a cup of broccoli florets. |

Attempts for `log-s-floz`:

| attempt model | reason | query |
|---|---|---|
| qwen3.8-max | coverage_miss:fl_oz | Please log that I drank 4 fl oz of milk. |
| deepseek-v4-pro-0813 | coverage_miss:fl_oz | I drank 8 fl oz of whole milk. |
| deepseek-v4-flash-0731 | accepted | I drank 1 fl oz of whole milk. |

Attempts for `eval-01`:

| attempt model | reason | query |
|---|---|---|
| deepseek-v4-pro-0813 | accepted | Please evaluate my planned meal of a can of tuna, one cup of rice, and one cup of broccoli florets. |

Attempts for `eval-02`:

| attempt model | reason | query |
|---|---|---|
| deepseek-v4-flash-0731 | accepted | Please evaluate my meal of one cup of firm tofu, one cup of steamed rice, and one cup of broccoli florets. |

Attempts for `eval-03`:

| attempt model | reason | query |
|---|---|---|
| glm-5.2 | accepted | I'm planning to have two eggs, a cup of oatmeal, and an apple for breakfast — can you evaluate if this is a good meal? |

Attempts for `eval-04`:

| attempt model | reason | query |
|---|---|---|
| kimi-k2.7-code | implausible | I'm planning to eat 150 g of chicken, a cup of broccoli florets, and one banana for my post-workout meal—can you evaluate it? |
| qwen3.8-2.4t-a95b | implausible | Can you evaluate my plan to eat 150 g of chicken with a cup of broccoli and a slice of cheddar? |
| qwen3.8-max | implausible | Can you evaluate my light training meal plan of 150 g of chicken, a cup of broccoli florets, and a piece of banana? |
| deepseek-v4-pro-0813 | unresolvable | Can you evaluate my meal of a cup of plain Greek yogurt, one banana, and two eggs? |
| deepseek-v4-flash-0731 | implausible | I'm planning to eat 150 g of grilled chicken with a cup of broccoli and 3 slices of avocado — can you evaluate this meal? |

Attempts for `eval-05`:

| attempt model | reason | query |
|---|---|---|
| qwen3.8-2.4t-a95b | accepted | Can you evaluate my plan to have 1 cup of chicken, 1 cup of broccoli, and 1 piece of apple? |

Attempts for `eval-06`:

| attempt model | reason | query |
|---|---|---|
| qwen3.8-max | implausible | Can you evaluate my training meal plan of 150 g of chicken, a cup of oatmeal, and a cup of broccoli? |
| deepseek-v4-pro-0813 | unresolvable | Can you evaluate my meal of a cup of oatmeal, a cup of whole milk, and one banana? |
| qwen3.8-2.4t-a95b | accepted | Can you evaluate my light training meal of a cup of oatmeal, a cup of milk, and one banana? |

Attempts for `log-m-03`:

| attempt model | reason | query |
|---|---|---|
| kimi-k2.7-code | accepted | Log a baked potato with two slices of cheddar cheese and a cup of broccoli florets. |

Attempts for `log-m-05`:

| attempt model | reason | query |
|---|---|---|
| qwen3.8-2.4t-a95b | duplicate | Log my meal: 150 g of chicken, a cup of spaghetti, and a cup of broccoli florets. |
| qwen3.8-max | duplicate | Please log that I already had 150 g of chicken, a cup of spaghetti, and a cup of broccoli. |
| deepseek-v4-flash-0731 | duplicate | Log a cup of spaghetti, a cup of chicken, and a cup of broccoli florets. |
| glm-5.2 | duplicate | I just ate 150 g of grilled chicken with a cup of pasta and a cup of broccoli for my post-workout meal, please log it. |
| kimi-k2.7-code | duplicate | Log my lunch: 150 grams of grilled chicken, a cup of spaghetti, and a cup of broccoli florets. |

Attempts for `log-m-06`:

| attempt model | reason | query |
|---|---|---|
| qwen3.8-max | implausible | Log my training meal of 150 g of chicken, a cup of rice, and a cup of broccoli florets. |
| deepseek-v4-flash-0731 | implausible | I had 150 g of grilled chicken with a cup of rice and a cup of broccoli, please log it. |
| glm-5.2 | implausible | I just had 150 g of grilled chicken with a cup of steamed rice and a cup of broccoli for my post-workout meal, log it. |
| kimi-k2.7-code | accepted | Log a cup of chicken, a cup of rice, and a cup of broccoli florets. |

### New-item review anomalies (人审 input)

Freeze first with flags. Main agent may `--drop` / `--replace-slot` afterwards.

No anomalies flagged on the new items.

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
| v10-evaluate-0009 | evaluate | everyday | Fish, tuna, light, canned in water, without salt, drained solids [171986] can 165.0g; Rice, white, cooked, no added fat [2708408] cup 158.0g; Broccoli, raw [2709643] cup 90.0g | deepseek-v4-pro-0813 | Please evaluate my planned meal of a can of tuna, one cup of rice, and one cup of broccoli florets. |
| v10-evaluate-0010 | evaluate | everyday | Tofu, firm, prepared with calcium sulfate and magnesium chloride (nigari) [172448] cup 126.0g; Rice, white, cooked, no added fat [2708408] cup 158.0g; Broccoli, raw [2709643] cup 90.0g | deepseek-v4-flash-0731 | Please evaluate my meal of one cup of firm tofu, one cup of steamed rice, and one cup of broccoli florets. |
| v10-evaluate-0011 | evaluate | everyday | Egg, whole, raw [2707152] piece 100.0g; Oats, raw [2708489] cup 80.0g; Apple, raw [2709215] piece 165.0g | glm-5.2 | I'm planning to have two eggs, a cup of oatmeal, and an apple for breakfast — can you evaluate if this is a good meal? |
| v10-evaluate-0013 | evaluate | everyday | Chicken, broilers or fryers, breast, meat only, cooked, roasted [171477] cup 140.0g; Broccoli, raw [2709643] cup 90.0g; Apple, raw [2709215] piece 165.0g | qwen3.8-2.4t-a95b | Can you evaluate my plan to have 1 cup of chicken, 1 cup of broccoli, and 1 piece of apple? |
| v10-evaluate-0014 | evaluate | gym | Oats, raw [2708489] cup 80.0g; Milk, whole [2705385] cup 244.0g; Banana, raw [2709224] piece 126.0g | qwen3.8-2.4t-a95b | Can you evaluate my light training meal of a cup of oatmeal, a cup of milk, and one banana? |
| v10-log-0001 | log | everyday | Beef, steak, sirloin, NS as to fat eaten [2705832] thick 240.0g | kimi-k2.7-code | Please log a thick serving of beef. |
| v10-log-0002 | log | everyday | Beef, steak, ribeye, NS as to fat eaten [2705828] thin 180.0g | qwen3.8-2.4t-a95b | Please log that I had a thin serving of beef. |
| v10-log-0003 | log | everyday | Milk, whole [2705385] fl_oz 30.5g | deepseek-v4-flash-0731 | I drank 1 fl oz of whole milk. |
| v10-log-0004 | log | everyday | Soy milk, sweetened [2705404] cup 244.0g | deepseek-v4-pro-0813 | I had a cup of soy milk. |
| v10-log-0005 | log | everyday | Bread, whole wheat [2707709] slice 24.0g | deepseek-v4-flash-0731 | Log a slice of whole wheat bread. |
| v10-log-0006 | log | everyday | Oats, raw [2708489] qns 10.0g | glm-5.2 | I had a serving of oatmeal this morning, please log it. |
| v10-log-0007 | log | gym | Egg, whole, raw [2707152] piece 100.0g | deepseek-v4-flash-0731 | Logged two eggs for my post-workout meal. |
| v10-log-0008 | log | gym | Chicken, broilers or fryers, breast, meat only, cooked, roasted [171477] cup 140.0g | qwen3.8-2.4t-a95b | Log a cup of chicken for my training meal. |
| v10-evaluate-0012 | evaluate | gym | Banana, raw [2709224] piece 126.0g; Yogurt, Greek, nonfat milk, plain [2705424] qns 150.0g | evaluate-row | Check this snack for me: a banana and 150g of Greek yogurt. |
| v10-log-0015 | log | everyday | Apple, raw [2709215] piece 165.0g; Cheese, Cheddar [2705709] slice 9.0g; Peanut butter [2707537] tbsp 16.0g | qwen3.8-max | Please log that I ate one apple, one slice of cheddar cheese, and one tablespoon of peanut butter. |
| v10-log-0016 | log | everyday | Egg, whole, raw [2707152] piece 100.0g; Cheese, Cheddar [2705709] slice 9.0g; Banana, raw [2709224] piece 126.0g | deepseek-v4-pro-0813 | I ate 2 eggs, 1 slice of cheddar cheese, and a banana for breakfast. |
| v10-log-0017 | log | everyday | Potato, baked, NFS [2709383] piece 230.0g; Cheese, Cheddar [2705709] slice 18.0g; Broccoli, raw [2709643] cup 90.0g | kimi-k2.7-code | Log a baked potato with two slices of cheddar cheese and a cup of broccoli florets. |
| v10-log-0018 | log | everyday | Pasta, cooked [2708357] cup 280.0g; Chicken, broilers or fryers, breast, meat only, cooked, roasted [171477] cup 140.0g; Broccoli, raw [2709643] cup 90.0g | glm-5.2 | I had two cups of spaghetti with a cup of grilled chicken and a cup of broccoli for dinner. |
| v10-log-0019 | log | gym | Pasta, cooked [2708357] cup 140.0g; Cheese, Cheddar [2705709] slice 9.0g | fallback-table | Please log a cup of spaghetti, and a slice of cheddar cheese for lunch. |
| v10-log-0020 | log | gym | Chicken, broilers or fryers, breast, meat only, cooked, roasted [171477] cup 140.0g; Rice, white, cooked, no added fat [2708408] cup 158.0g; Broccoli, raw [2709643] cup 90.0g | kimi-k2.7-code | Log a cup of chicken, a cup of rice, and a cup of broccoli florets. |

## Coverage

| key | count |
|---|---|
| qns | 2 |
| thick | 1 |
| thin | 1 |
| fl_oz | 1 |
| cup | 20 |
| slice | 5 |

Coverage check: qns / thick / thin / fl_oz / cup / slice each ≥ 1.

## Gym grams

resolve_portion accepts '150 g' / '150 grams', but validate_oracle_grams requires a catalog-v1 PortionFact multiple (×0.5/1/1.5/2, plus 2 oz). Gym items therefore stay on PortionFact keys unless the gram amount is already a table value (e.g. greek yogurt 150 g = qns).

## Handbook

`HANDBOOK_VOCABULARY` is covered by `_SYSTEM_V1_TAIL`. Pilot expressions stay on cup / tbsp / tsp / slice / piece / can / fl_oz / serving / thick / thin / regular / grams / ounces.

## D4 / evaluate

R1 changed `_validate_evaluate` to semantic gram backresolve: each plan item's grams must match a catalog PortionFact multiple (or a spoken gram amount in the query), and each food must be named. Evaluate queries no longer need to verbatim-match `EVALUATE_ROWS`. `--rerun-fallbacks` re-expands former evaluate-row / fallback-table slots with the live expander under this gate.

## Re-freeze

```
.venv/bin/python scripts/run_pilot_20.py --rerun-fallbacks --force
.venv/bin/python scripts/run_pilot_20.py --drop <id,...>
.venv/bin/python scripts/run_pilot_20.py --replace-slot <slot> --replace-id <id>
```

`--rerun-fallbacks --force` rewrites the published exam (R2 overwrite guard passed explicitly). `--drop` / `--replace-slot` also rewrite with `overwrite=True`. Reads `reports/pilot-20-state.json`.

## Landing / exam switch

- `EXAM_SPLIT_PATH` now points at `data/splits/v1.0-gold.json`.
- `scripts/landing_verify.py` keeps the v0.5 old-key / replay / validate_draft / oz checks, then `load_exam` + `validate_draft` the 20 v1.0 items.
- `_SYSTEM_V1_TAIL` was not changed: every spoken measure in the pilot is already in the v1 handbook.


## Verification (10c)

- `--rerun-fallbacks --force` replaced 8/10 fallback slots with live expander output.
- still-fallback (honest disclosure): `eval-04` (implausible/unresolvable ×5) and `log-m-05` (duplicate ×5 vs already-used chicken+pasta+broccoli).
- KEEP 10 already-LLM items byte-identical vs the pre-rerun freeze.
- `load_exam()` → 20 items (14 log / 6 evaluate).
- Coverage: qns 2, thick 1, thin 1, fl_oz 1 (LLM, log-s-floz), cup 20, slice 5.
- New-item review-harness anomalies: none (all 8 accepted replacements review-clean).
- `.venv/bin/python -m pytest -q` → **949 passed**.
- `.venv/bin/python scripts/landing_verify.py` → **PASS** (v0.5 240 + v1.0 20).
- `_SYSTEM_V1_TAIL` unchanged; `catalog.sqlite` and `v0.5-gold.json` untouched.


Freeze sha256 of `data/splits/v1.0-gold.json`: `39dc756c7c8ab7986f02e324b7e9e8f7099fcc68aa5b3c07870bf374a8a2c6ac`.

