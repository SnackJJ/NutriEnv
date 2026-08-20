# Env public API (owned by env-kernel)

The interactive world only. No generator, no oracle, no scorer — `bench/` owns those.

```python
from nutrienv.env import NutriEnv
from nutrienv.world.types import Profile, LedgerRow, WorldState
from nutrienv.world.catalog_fixture import demo_state, demo_catalog, demo_profile
```

## Types — `nutrienv.world.types`

```python
Profile(user_id, allergies=(), medications=(), windows={}, plan_preset={}, version=1)  # frozen
LedgerRow(food_id, grams, eaten_at)                                                    # frozen
WorldState(profile, ledger=[], catalog={}, last_plan=[], last_verdict=None, last_reasons=())  # mutable
```

`last_verdict` is `None` (silence), `"accept"`, or `"reject"`. `last_reasons` is a sorted unique
tuple of closed reason codes (`allergy` and `{kcal,protein_g,carb_g,fat_g,fiber_g,sodium_mg}_hi/_lo`).

`catalog` maps `food_id -> {name, nutrients, allergen_tags, aliases, portions?}`. Nutrients are
**per 100 g** under the keys `kcal, protein_g, carb_g, fat_g, fiber_g, sodium_mg`.

## Env — `nutrienv.env.NutriEnv`

```python
NutriEnv(*, default_eaten_at: str = "now")
env.reset(s0: WorldState) -> dict   # opening observation; s0 is deep-copied, not adopted
env.step(action: dict) -> dict      # {ok, observation, error?, done}
env.state() -> WorldState           # the live end state, for the scorer
```

- `reset` returns `{op, profile, ledger, ledger_totals, last_plan, last_verdict, last_reasons, catalog_size}`.
  Find foods with `search_foods` (BM25 over the local USDA snapshot). The opening
  observation does not list every id.
- `step` on a legal action → `{"ok": True, "observation": {...}, "done": False}`.
- Illegal action → `{"ok": False, "observation": None, "error": {"code", "message"}, "done": False}`
  and the world is unchanged. Codes: `bad_schema`, `unknown_op`, `unknown_food`,
  `implausible_quantity`.
- `done` is always `False` in v1 — hand-in lives outside Env.
- `step`/`state` before `reset` raise `RuntimeError`. That is a harness bug, not an Illegal Action,
  so it is not graded as one.

## Actions — all available on every Task

| op | args | effect |
|---|---|---|
| `search_foods` | `q` | BM25 over name/aliases/food_id; top 25. `q="*"` is empty, not a dump |
| `get_food` | `food_id` | full catalog entry, including `portions` |
| `get_profile` | — | profile view plus `last_plan`, `last_verdict`, `last_reasons` |
| `get_ledger` | — | all rows, each with scaled `nutrients`, plus `totals` |
| `get_dri` | — | static FDA reference table + the profile's own windows |
| `log_meal` | `food_id`, `grams`, `eaten_at?` | appends a `LedgerRow` |
| `submit_plan` | `items: [{food_id, grams}]`, `verdict?`, `reasons?` | writes `last_plan`, `last_verdict`, `last_reasons` |
| `update_profile` | `patch` | patches `allergies, medications, windows, plan_preset, version` |
| `update_plan` | `patch` | shallow-merges into `profile.plan_preset` |

Schemas are strict: an unknown key anywhere in the envelope or in a plan item is `bad_schema`.
`grams` must be a finite number `> 0` and at most 2000. A submitted plan's
total may not exceed 4000 g. Either breach is `implausible_quantity`, not
`bad_schema`. An empty `items` list is legal. `submit_plan` is total on
`(last_verdict, last_plan, last_reasons)`: omitted verdict with non-empty items infers
accept; omitted verdict with empty items is silence (`None`, `[]`, `()`), not reject.
`verdict=accept` requires a non-empty plan and forbids the `reasons` key (including
`reasons=[]`). `verdict=reject` requires empty items; empty or omitted reasons are
legal physics. Reject plus a plan, accept plus `reasons`, reasons without a verdict,
or an unknown reason token is `bad_schema` and leaves the world unchanged.

## Rules bench-gen must mirror when building an Oracle

1. **`eaten_at` has no clock.** A `log_meal` without `eaten_at` is stamped with
   `NutriEnv(default_eaten_at=...)`, default `"now"`. A wall-clock default would make the end
   state unpredictable and `end state == Oracle` unusable.
2. **`allergies` / `medications` are sets.** Writes are stripped, lowercased, de-duplicated and
   sorted. Build Oracle values with `nutrienv.world.normalize_tags(...)` so ordering and case
   can never cause a spurious fail. S0 values are *not* normalized — only writes are.
3. **`windows` and `plan_preset` merge key-wise.** Patching `{"windows": {"kcal": [2000, 2400]}}`
   leaves `protein_g` at its S0 value. Window values become `(lo, hi)` floats and require `lo <= hi`.
   `allergies` / `medications` replace wholesale — a patch is the new full list.
4. **`version` is never auto-bumped.** It changes only if the patch says so, so unmentioned fields
   stay at S0 (ADR 0004).
5. **`user_id` is not patchable** — it is identity, not a nutrition field. Patching it is `bad_schema`.
6. **Env never judges.** An allergen meal logs fine; an out-of-window plan submits fine. Semantic
   quality is scored at hand-in, not rejected as physics.

`update_plan {patch}` and `update_profile {patch: {plan_preset: ...}}` are two spellings of the
same merge; either reaches the same end state.

## Portions — `nutrienv.world.resolve_portion`

A catalog entry may carry `portions: {measure -> grams}`, the weight of one household measure
**of that food**: `milk_whole` has `cup: 244.0`, `whole_wheat_bread` has `slice: 32.0`,
`olive_oil` has `tbsp: 13.5`. A food only declares the measures that make sense for it. The
`get_food` observation always includes `portions`, empty for a food that declares none, so the
observation has one shape whatever catalog the Generator supplies.

```python
from nutrienv.world import resolve_portion
resolve_portion("milk_whole", "half a cup", catalog)   # -> 122.0
resolve_portion("milk_whole", "2 slices", catalog)     # -> None
```

**Env does not parse natural language, and no Action calls this.** Turning "half a cup" into a
number is the Generator's or the harness's job; `resolve_portion` is a shared table-lookup so
that everyone does it identically, and so a fuzzy-portion Task can be judged without asking a
model to do unit arithmetic. Keeping it out of the Action layer also keeps `log_meal` typed:
grams in, grams stored.

The grammar is small and total — it never raises, and `None` means *ask for grams*, never *zero*:

- Quantities: `2`, `1.5`, `1/2`, `1 1/2`, `½`, `one`…`twelve`, `half`, `quarter`, `third`.
  A fraction word multiplies a number in front of it (`three quarters` → 0.75) unless `and`
  separates them (`one and a half` → 1.5). No quantity at all reads as one — `a cup` and `cup`
  are both 1.
- Measures: `cup(s)`, `tbsp`/`tablespoon(s)`, `tsp`/`teaspoon(s)`, `piece(s)`/`each`/`unit(s)`,
  `slice(s)` — plus `g`/`gram(s)`, which need no table entry. Words after the measure are
  ignored, so `half a cup of milk` works.
- `None` for: an unknown `food_id`, a measure the food does not declare, an unparseable or
  non-positive quantity (`some milk`, `3-4 cups`, `0 cups`), or a bare number with no unit.

## Fixture

`nutrienv.world.catalog_fixture` ships 15 foods (peanut butter, shrimp, oats, egg, white rice,
whole milk, chicken breast, almond, salmon, tofu, whole wheat bread, banana, broccoli, greek
yogurt, olive oil) with `demo_catalog()`, `demo_profile()` and `demo_state()`, each carrying the
household measures that suit it. It exists so others can run Env before the Generator lands —
real Tasks get their S0 from `bench/` (ADR 0003).
