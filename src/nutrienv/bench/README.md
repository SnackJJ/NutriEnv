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
`constrain`. Every task receives the complete catalog and Env always exposes
the full action set. `n_constraints`, `ledger_gaps`, and `name_ambiguity` alter
the query and S0 rather than tool availability.

Oracle fields are query-scoped. `None` means that portion of state is not
judged. A ledger oracle contains only rows appended after S0. For plans,
`last_plan=[]` requests any non-empty allergen-safe plan satisfying every
profile window; a non-empty oracle list requests those exact evaluation items.
Catalog nutrients are summed as `amount_per_100g * grams / 100`.

Scoring returns exactly `{"passed": bool, "tag": str}`. The tags are `pass`,
`allergy`, `window`, `log_miss`, `update_miss`, and `wrong_goal`.

## Situations

Pass `situation="..."` to `Generator.sample` or `generate_split` to request a
specific query/S0 flavor. Situations use only the bundled 15-food catalog.

| Situation | Fixture-backed realization |
|---|---|
| `fuzzy_portion` | “Half a cup of milk” resolves through Bench's portion map to 122 g. |
| `multi_item_log` | One query requires three distinct new breakfast ledger rows. |
| `condition_suitability` | A shellfish-allergic profile asks whether shrimp is suitable; an empty or allergen-safe plan is valid. |
| `unit_convert` | Two ounces of oats converts through Bench's unit map to 56.7 g. |
| `near_synonym` | “Prawns” must resolve to the fixture's `shrimp` entry. |
| `conflict_windows` | S0 contains mutually infeasible kcal/protein windows and expects no violating plan. |
| `ledger_gap` | Breakfast and dinner exist in S0; the query supplies only the missing lunch row. |

`Task.situations` is a tuple of string tags and is empty for ordinary
family-only generation. Supplying an unknown situation, or pairing one with an
incompatible explicit family, raises `ValueError`.
