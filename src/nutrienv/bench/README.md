# Bench public API

`nutrienv.bench` exports `realize`, `Material`, `Task`, `Oracle`, and `Scorer`.

```python
from nutrienv.bench import realize, material_from_row, spoken_query, Scorer
from nutrienv.bench.realizations import FUZZY_ROWS
from nutrienv.env import NutriEnv

row = FUZZY_ROWS[0]
task = realize(material_from_row(row), spoken_query(row))
env = NutriEnv()
env.reset(task.s0)
# issue actions with env.step(...)
result = Scorer().score(env.state(), task.oracle)
```

`realize(material, query)` is the public, deterministic, catalog-injectable
constructor. Same material + same query produce field-equal Tasks; a different
query changes only `Task.query`. Grams come from the catalog via
`resolve_portion`. The six task families are `lookup`, `log`, `recommend`,
`evaluate`, `update`, and `constrain`. `leftover` is recommend-only: daily
windows on the Profile plus `Oracle.plan_windows` remainder. Every task
receives the complete catalog and Env always exposes the full action set.
Draft oracles follow the gold contract: log pins `profile` to S0 and `ledger`
to S0+tail; update / recommend / evaluate pin `ledger` to S0.

Oracle fields are query-scoped. `None` means that portion of state is not
judged. A ledger oracle contains only rows appended after S0. For plans,
`last_plan=[]` requests any non-empty allergen-safe plan satisfying every
profile window; a non-empty oracle list requests those exact evaluation items.
`last_verdict` is `None` (today's plan scoring, so old splits load), `"accept"`,
or `"reject"`. Accept requires the exact adopted plan, accept, and empty
reasons. Reject requires reject, an empty adopted plan, and the exact
reason-code set; a fitting substitute fails, and `allow_empty_plan` does not
bypass this. Reject oracles do not set plan-must-fit or allow-empty-plan.
`update_band` is omitted for exact Profile equality (every frozen update item).
`cut` / `fatigue` / `muscle` score the band-relevant window keys against the
ADR 0015 bands; allergies and non-band window keys stay exact, and `phase` is
free because the handbook offers both a phase patch and a direct window move.
Daily-window math is imported from
`nutrienv.world.derive_daily_windows`. A split oracle that names a new body
fact or phase refreshes `profile.windows` with that same derivation so a
fact-only Env patch can equal the Oracle. A band oracle is the exception: it
keeps S0's windows, which are the baseline `fatigue` must rise above.
Catalog nutrients are summed as `amount_per_100g * grams / 100`.

Scoring returns exactly `{"passed": bool, "tag": str}`. The tags are `pass`,
`allergy`, `window`, `log_miss`, `update_miss`, and `wrong_goal`.

## Situations

Situations use the local USDA FDC catalog (`data/fdc/catalog.sqlite`, built by
`scripts/download_fdc.py` and `scripts/build_fdc_catalog.py`). The published exam is a frozen split (ADR 0006, ADR 0009). `data/splits/v0-gold.json` is the 40-item calibration set; `v0.1-gold.json` is 64, `v0.2-gold.json` is 100 and `v0.3-gold.json` is 156, each copying its parent's items unchanged and appending a reviewed slice. Increments are materialized by `scripts/materialize_split.py <version>`, which drives the public `realize(material, query)` seam, so a frozen file cannot drift from the table that produced it. `evaluate` reached its full 48-item allocation in v0.3. The destination ruler is 240 sliced items; increments are new files, never an overwrite of v0-gold. Everyday is the majority persona; cut / gym / leftover / flex are reasons people ask; hypertension is one thin item. Lookup is not in the headline split. Leftover recommend tasks show daily windows on the Profile and score the meal against `Oracle.plan_windows` (the remainder; ADR 0007). `scripts/run_react.py` runs the published 240-item exam by default (fail-closed `load_exam`); pass `--split` to run a calibration/history file.

The published exam is `data/splits/v0.5-gold.json`, loaded through `load_exam()`, which binds it to the exact catalog file recorded in the manifest: it rejects a wrong version, a missing or non-`.sqlite` catalog, or a `catalog_sha256` mismatch. The manifest field therefore records the *currently verified* catalog for v0.5, while the parent v0.1–v0.4 splits keep the hash of the catalog frozen at their materialization time (`e1ffbb1a…`, pre-2026-08-16 rebuild). Any future catalog rebuild must update the `catalog_sha256` of every in-use split, or the exam will refuse to start.

Diversity comes from `realizations.py` tables. Every family the exam scores is table-backed: `FUZZY_ROWS` (24), `LEFTOVER_ROWS` (27), `UPDATE_ROWS` (22), `CONSTRAIN_ROWS` (22, split into `kind="condition"` and `kind="conflict"`), `EVALUATE_ROWS` (55). Gold-shaped rows come first in each table so the factory still covers the calibration shapes.

Evaluate rows carry a `tier` naming the axis they exercise: `single` / `pair` / `triple` / `long` vary how many items a spoken list holds, `explicit_grams` uses foods the catalog has no portion for so the query must state grams, and `synonym` names a food the slug does not. Be honest about what the first four measure: they are one axis — list-extraction load — not four capabilities, and `explicit_grams` is a control rather than a harder case. They earn their slots by spanning that axis deliberately instead of reshuffling foods, not by being four different skills.

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
family-only items. The retired `Generator.sample` factory is archived in
`generator.py`; do not use it to produce exam numbers.
