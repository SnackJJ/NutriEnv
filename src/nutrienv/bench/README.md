# Bench public API

`nutrienv.bench` exports `Generator`, `Task`, `Oracle`, and `Scorer`.

```python
from nutrienv.bench import Generator, Scorer
from nutrienv.env import NutriEnv

task = Generator().sample(7, family="log")
env = NutriEnv()
env.reset(task.s0)
# issue actions with env.step(...)
result = Scorer().score(env.state(), task.oracle)
```

Generation is deterministic for a seed and uses an isolated RNG. The six task
families are `lookup`, `log`, `recommend`, `evaluate`, `update`, and
`constrain`. Pass `persona=` to flavor S0 (`everyday` default). `leftover` is
recommend-only: daily windows on the Profile plus `Oracle.plan_windows`
remainder. Other gold personas are not implemented in the factory yet. Every task
receives the complete catalog and Env always exposes the full action set.
`n_constraints`, `ledger_gaps`, and `name_ambiguity` alter the query and S0
rather than tool availability. Draft oracles follow the gold contract: log pins
`profile` to S0 and `ledger` to S0+tail; update / recommend / evaluate pin
`ledger` to S0; household grams come from `resolve_portion`.

Oracle fields are query-scoped. `None` means that portion of state is not
judged. A ledger oracle contains only rows appended after S0. For plans,
`last_plan=[]` requests any non-empty allergen-safe plan satisfying every
profile window; a non-empty oracle list requests those exact evaluation items.
Catalog nutrients are summed as `amount_per_100g * grams / 100`.

Scoring returns exactly `{"passed": bool, "tag": str}`. The tags are `pass`,
`allergy`, `window`, `log_miss`, `update_miss`, and `wrong_goal`.

## Situations

Pass `situation="..."` to `Generator.sample` or `generate_split` to request a
specific query/S0 flavor. Situations use the local USDA FDC catalog (`data/fdc/catalog.sqlite`, built by
`scripts/download_fdc.py` and `scripts/build_fdc_catalog.py`). The published exam is a frozen split (ADR 0006, ADR 0009). `data/splits/v0-gold.json` is the 40-item calibration set; `v0.1-gold.json` is 64 and `v0.2-gold.json` is 100, each copying its parent's items unchanged and appending a reviewed slice. Increments are materialized by `scripts/materialize_v02.py`, which drives the same `Generator._*_from_row` helpers the factory uses, so a frozen file cannot drift from the table that produced it. The destination ruler is 240 sliced items; increments are new files, never an overwrite of v0-gold. Everyday is the majority persona; cut / gym / leftover / flex are reasons people ask; hypertension is one thin item. Lookup is not in the headline split. Leftover recommend tasks show daily windows on the Profile and score the meal against `Oracle.plan_windows` (the remainder; ADR 0007). `scripts/run_react.py` reads v0-gold by default; `--seed/--n` is draft-factory only.

Diversity comes from `realizations.py` tables. Changing the factory seed picks another table row. Every family the exam scores is now table-backed: `FUZZY_ROWS` (24), `LEFTOVER_ROWS` (27), `UPDATE_ROWS` (22), `CONSTRAIN_ROWS` (22, split into `kind="condition"` and `kind="conflict"`), `EVALUATE_ROWS` (11). Gold-shaped rows come first in each table so the factory still covers the calibration shapes.

Rows never store a number the catalog can compute. Grams come from `resolve_portion`, leftover remainder windows from `ledger_totals`, and an evaluate row's nutrient windows from its own plan total plus a margin the row declares. A row that stored those numbers could drift out of agreement with the catalog and turn a frozen item unpassable without any test noticing.

Query text is hand-written, not templated: spoken diversity is the point, and ADR 0006 already says paraphrases are not new rows. Validity comes from cross-checking instead — `validate_draft` verifies that the sentence and the oracle describe the same change. An update whose oracle moves a window by an amount the sentence does not name, or moves it in the direction the sentence denies, or adds an allergen no word in the sentence evidences, or silently skips a change the sentence asks for, is rejected. Evaluate items must resolve every gram through the query's own phrasing and must land inside their own windows.

Constrain carries two different oracle contracts and every gate is scoped per kind: `condition` must submit a safe plan (`last_plan=[]`, `allow_empty_plan=False`), while `conflict` may submit nothing (`last_plan=None`, `allow_empty_plan=True`). "Constrain means the agent chooses" is true only of the first.

| Situation | Fixture-backed realization |
|---|---|
| `fuzzy_portion` | A table row’s spoken phrase resolves through `resolve_portion` (e.g. half a cup of milk → 122 g). |
| `multi_item_log` | One query requires three distinct new breakfast ledger rows. |
| `condition_suitability` | A profile allergic to the named food asks whether it is suitable, or what to eat instead; silence does not pass. |
| `unit_convert` | Two ounces of oats converts through `resolve_portion` (28.35 g/oz) to 56.7 g. |
| `near_synonym` | A log of “prawns” must resolve to the fixture's `shrimp` entry. |
| `conflict_windows` | S0 contains mutually infeasible kcal/protein windows and expects no violating plan. |
| `ledger_gap` | Breakfast and dinner exist in S0; the query supplies only the missing lunch row. |

`Task.situations` is a tuple of string tags and is empty for ordinary
family-only generation. Supplying an unknown situation, or pairing one with an
incompatible explicit family, raises `ValueError`.
