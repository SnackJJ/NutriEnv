# nutri-env v1 charter (locked)

Python package. Sibling of NutriBuddy. Frozen ruler: Env + Bench. No harness implementation. No training loop. No product UI.

## Locked rules

- Full Action catalog on every Task. Difficulty is in query + S0, not hidden tools.
- Illegal Action (bad schema, unminted food_id) → immediate error observation. Episode continues.
- Semantic quality (windows, extra/missing field writes) → score only at hand-in.
- Writes apply now. Pass ⇔ end state == Oracle.
- Oracle from Generator(S0, query). Unmentioned fields must stay S0.
- Headline metric: binary Pass / rate / pass^k. Diagnostic tags are not the headline.
- Confirm is not in the policy. Product human may later emit the same update Action. v1 has no user simulator.

## Task families (all in v1; one primary goal per Task)

查 lookup · 记 log · 答 recommend/evaluate · 改 update (plan and/or profile as Oracle says) · 约 constraint question

## State (structured, per episode)

Profile: allergies, medications, windows (kcal, protein_g, …), plan_preset, version  
Ledger: append-only eaten rows (food_id, grams, when)  
Catalog: local foods (id, nutrients, allergen tags, aliases). No live USDA.

## Actions (names may be bikesheded but must be typed)

- `search_foods` / `get_food` / `query_nutrients`
- `get_profile` / `get_ledger` / `get_dri`
- `log_meal` (descriptive; allergen eaten is valid)
- `submit_plan` (recommend or evaluate-by-plan)
- `update_profile` / `update_plan` (apply now; judge via Oracle)

## Package layout

```
src/nutrienv/
  env/       # reset(S0), step(action) -> obs, state
  world/     # profile, ledger, catalog
  actions/   # schemas + dispatch
  bench/     # generator, oracle, scorer, seed
tests/
```

## Situations (query/S0 flavors; not foreign items)

`fuzzy_portion` · `multi_item_log` · `condition_suitability` · `unit_convert` · `near_synonym` · `conflict_windows` · `ledger_gap`

## Runner

`scripts/run_split.py` (thin): load env tag + seed split, call `Harness.act(obs) -> action`, `env.step`, score end state. Subject = harness + model. Ship `ScriptHarness` first.

## Non-goals v1

LangChain, Postgres, product PWA, RL trainer, photo logging, free-text memory, rubric-as-headline.
