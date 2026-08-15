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
`scripts/download_fdc.py` and `scripts/build_fdc_catalog.py`). The published exam is a frozen split (ADR 0006, ADR 0009). `data/splits/v0-gold.json` is the 40-item calibration set. The destination ruler is 240 sliced items; increments are new files, never an overwrite of v0-gold. Everyday is the majority persona; cut / gym / leftover / flex are reasons people ask; hypertension is one thin item. Lookup is not in the headline split. Leftover recommend tasks show daily windows on the Profile and score the meal against `Oracle.plan_windows` (the remainder; ADR 0007). `scripts/run_react.py` reads v0-gold by default; `--seed/--n` is draft-factory only.

Diversity comes from `realizations.py` tables (fuzzy portions, leftover ledgers). Changing the factory seed picks another table row. `validator.validate_draft` rejects leaks, unresolvable grams, and leftover windows that do not match the remainder.

| Situation | Fixture-backed realization |
|---|---|
| `fuzzy_portion` | A table row’s spoken phrase resolves through `resolve_portion` (e.g. half a cup of milk → 122 g). |
| `multi_item_log` | One query requires three distinct new breakfast ledger rows. |
| `condition_suitability` | A shellfish-allergic profile asks whether shrimp is suitable, or what to eat instead; silence does not pass. |
| `unit_convert` | Two ounces of oats converts through `resolve_portion` (28.35 g/oz) to 56.7 g. |
| `near_synonym` | A log of “prawns” must resolve to the fixture's `shrimp` entry. |
| `conflict_windows` | S0 contains mutually infeasible kcal/protein windows and expects no violating plan. |
| `ledger_gap` | Breakfast and dinner exist in S0; the query supplies only the missing lunch row. |

`Task.situations` is a tuple of string tags and is empty for ordinary
family-only generation. Supplying an unknown situation, or pairing one with an
incompatible explicit family, raises `ValueError`.
