# Impl report: per-family recipe channel for batch item production

Spec: `reports/spec-recipe-channel.md` (issue 15 infrastructure #2). Transport
only — recipe VALUES are issue-15 design. Commit on main, prefix "pipeline:".

## What changed

- `pipeline/types.py` — `Candidate` gained `knife: str | None = None`,
  `occasion: str | None = None`, `shell: str | None = None`,
  `scene: str = "empty"`, `tier: str = ""`. Frozen-dataclass defaults keep
  every existing constructor byte-identical.
- `run_batch.py`
  - `_parse_spec`: new optional `batch_spec["family_recipes"]`
    (`{family: {key: value}}`). Fail-closed parsing: unknown families, unknown
    keys (must be knife/occasion/shell/scene/tier), and non-string values are
    refused (`_parse_family_recipes`) so a typo can never be silently dropped.
  - `_PoolJob` carries the family's recipe; `_build_jobs` stamps it;
    `_expand_one` merges it onto each Candidate via `dataclasses.replace`
    before `resolve_candidate`. Empty recipes → candidates byte-identical.
- `resolver.py`
  - `_realize_recommend`: honours `candidate.occasion` (override; falls back
    to the spoken "for <meal>" word; unresolved still fails loudly).
    `shell`/`scene` recipes raise — the resolver's free-plan recommend has no
    shell semantics, and `scene="leftover"` needs prior logs (see decision
    below); they fail loudly instead of being silently ignored. Tier is
    forwarded to the Task.
  - `_realize_update`: forwards tier; knife/shell/scene recipes raise (no
    update semantics resolver-side).
  - evaluate: fit realization extracted into `_realize_evaluate`; with a
    `knife` recipe, the new `_realize_evaluate_knife` mirrors the mill's
    fit→knife flow (`apply_knife` over the resolved plate against meal-slot
    windows from the roster profile) and builds the ADR 0017 unfit envelope:
    reject verdict, empty `last_plan`, `evaluated_plan` = knifed plate,
    `last_reasons` = bind of that plate, pinned `plan_windows`. The speech
    rewrite the mill delegates to its LLM rewriter is done deterministically:
    knifed-only foods are appended to the query ("… , plus peanut butter.")
    so every evaluated food stays named. `apply_knife` is imported lazily
    (`pipeline.knives → semantic_vote → resolver` would be circular at module
    load). No knife / no unfit plate / no occasion → clean documented
    rejection (`unresolvable`).
  - every realize path forwards `candidate.tier` (channel from 9643b4f);
    log/composite Tasks get it via `replace(task, tier=...)`.
- `scripts/generate_batch.py`: repeatable `--recipe FAMILY:KEY=VALUE`
  (keys knife/occasion/shell/scene/tier), parsed into `family_recipes`;
  families must match a requested `--family`; synthetic runs pass through.

## Leftover carrier decision (spec point 2/5)

Single-family `recommend` with `scene="leftover"` stays **generate_one-only**
for now: leftover geometry needs `prior_logs` for the same roster person, and
the batch resolves one candidate at a time with no accepted-task memory.
The batch's leftover carrier is **composite log+recommend**, which carries the
ledger geometrically end-to-end (verified in test_pipeline_composite and the
five-family smoke). The transport still accepts `scene` on recommend and the
resolver rejects it loudly (`unresolvable`), so an authoring driver cannot
silently produce a non-leftover item believing it is one.

## Tests (`tests/test_run_batch.py`, +5)

- `test_empty_family_recipes_behave_like_today` — `{"evaluate": {}}` behaves
  as today (accepted fit task, tier "").
- `test_tier_recipe_is_carried_into_the_frozen_output` — `{"tier": "pair"}`
  lands on `Task.tier` and in the frozen payload item.
- `test_knife_recipe_produces_an_evaluate_unfit` — allergy-knife fixture
  (compact catalog so every pool contains the peanut carrier): accept-count 1,
  reject verdict, empty last_plan, bound reasons, `validate_draft == []`.
- `test_unknown_recipe_key_is_refused` — parse-level ValueError.
- `test_leftover_scene_recipe_for_recommend_is_rejected_cleanly`.

## Smoke evidence

Fixture-level (deterministic):

```
knife recipe {"knife":"allergy","occasion":"dinner","tier":"single"}:
tier: 'single' | verdict: reject | reasons: ('allergy', 'kcal_lo')
evaluated: [milk_whole 244g, peanut_butter 16g]
query: "Evaluate this as my plan: a cup of milk, plus peanut butter."
validate_draft: OK   (reason set == bind of evaluated plan)
```

CLI (catalog-v1 archive, draft output only):

```
$ .venv/bin/python scripts/generate_batch.py --synthetic --model synthetic \
    --count 1 --family evaluate --family recommend --seed 20260822 ... \
    --recipe evaluate:tier=pair --recipe evaluate:knife=allergy \
    --recipe evaluate:occasion=dinner --recipe recommend:tier=long
pools=2 candidates=2 accepted=1 ; rejections: unresolvable=1
frozen: v10-recommend-0002 recommend tier='long' validate OK
```

The evaluate knife rejected cleanly on catalog-v1 for most seeds (random
8-food pools usually lack a peanut-tagged carrier — the documented clean path);
seeds 9/10 produced an accepted unfit whose frozen item carries
`tier='single'`. Reloading such an unfit via `load_split` currently fails on
the situation vocabulary (`evaluate_unfit`/`allergy` not in SITUATIONS) —
pre-existing for all mill unfit drafts, orthogonal to this channel; the frozen
payload itself is correct. Note also the transport is deliberately permissive
on tier VALUES outside generate_one (a recommend item with an evaluate-tier
string counts toward no floor); value policy belongs to issue 15.

## Verification

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1306 passed in 49.14s
```

(Previously 1301; +5 tests, 0 failures.)

## Review (codex)

**Verdict: REV.** The transport reaches the resolver and the allergy fixture
does produce an ADR-0017-shaped reject oracle, but the general knife path does
not preserve the spoken meal and its frozen output cannot be loaded. The
fail-closed contract also has holes at the library boundary.

### Spec findings

- **High — the knife input is not bind-confirmed against the windows used for
  the unfit oracle** (`src/nutrienv/bench/pipeline/resolver.py:300`,
  `src/nutrienv/bench/pipeline/resolver.py:504`). `_realize_evaluate` makes a
  legacy fit oracle with plate-derived two-key windows, then
  `_realize_evaluate_knife` ignores that `fit_task` and switches to Ada's
  six-key dinner windows. The committed milk fixture is already `kcal_lo`
  before the allergy knife (the result is `('allergy', 'kcal_lo')`), so this is
  not ADR 0017's fit→knife construction. **Fix:** bind the original plate
  against the same roster/occasion windows, reject unless it fits, and use that
  state as the source for the knife oracle.
- **High — non-allergy knife speech can contradict `evaluated_plan`**
  (`src/nutrienv/bench/pipeline/resolver.py:530`,
  `src/nutrienv/bench/pipeline/resolver.py:553`). `_name_knifed_foods` only
  appends names for new food ids: a bumped/stepped item retains its old spoken
  amount, a dropped or swapped item remains spoken, and an addition has no
  recoverable amount. A batch probe accepted an over-slot task whose query says
  `130 g of chicken` while `evaluated_plan` contains 140 g; `validate_draft`
  still returns `[]` because it only checks that table grams and food names are
  present. This also violates the agent-manual symmetry rule for the new bare
  `plus FOOD` wording. **Fix:** rewrite the complete knifed plate with its
  actual catalog-backed speakable amounts via the generate-one rewrite contract
  (and synchronize `react.py` for any genuinely new speech convention).
- **High — the frozen knife result is not reloadable**
  (`src/nutrienv/bench/pipeline/resolver.py:547`). The batch freezes
  `situations=["evaluate_unfit", "allergy"]`, neither of which belongs to
  `SITUATIONS`; `load_split(result.path, catalog=...)` reproduces
  `ValueError: unknown situations`. Calling this pre-existing does not make the
  newly emitted batch artifact usable end to end. **Fix:** emit reload-valid
  situation metadata (the quality gate already recognizes unfit oracle
  geometry), or extend the approved vocabulary in a separately authorized
  change, and add a freeze→load assertion.
- **Medium — recipe parsing is not consistently fail-closed**
  (`src/nutrienv/bench/pipeline/run_batch.py:409`,
  `src/nutrienv/bench/pipeline/resolver.py:295`). The global key set admits
  family/key combinations that their resolver branch silently ignores; for
  example `recommend:knife=bogus` is accepted as a normal Recommend. It also
  accepts null despite the report claiming non-string values are refused;
  `evaluate:tier=null` reaches an accepted `Task(tier=None)`. Recipes for a
  supported family absent from `family_quotas` are likewise unused at the
  library API (the CLI alone rejects them). **Fix:** define allowed keys and
  value types per family, require recipe families to be requested, and reject
  unsupported/null assignments before jobs are built.
- **Medium — Recommend `shell` transport does not meet the decided spec**
  (`src/nutrienv/bench/pipeline/resolver.py:394`). The spec says Recommend
  honors `candidate.shell`, but every non-empty shell becomes an unresolvable
  rejection. **Fix:** implement the existing generate-one shell semantics, or
  narrow the design authority before advertising `shell` as a batch recipe
  channel.

### Standards finding

- **High — batch exposure includes the unanchored `swap` knife**
  (`src/nutrienv/bench/pipeline/resolver.py:500`). Accepting every value in
  `KNIVES` exposes `swap`, whose `_iso_item` grams are calculated from target
  kcal rather than selected from an FNDDS/QNS portion. That conflicts with the
  repository's hard gram-anchor rule and ADR 0017's Stage-A `grams = table`
  gate. **Fix:** reject `swap` in this channel until it selects a catalog/QNS
  gram value, or change the knife to use a catalog portion.

### Test assessment and evidence

- `test_tier_recipe_is_carried_into_the_frozen_output`, the allergy knife test,
  the unknown-key control, and the leftover-scene rejection exercise real
  behavior. The empty-recipe test does not compare the result with a no-recipe
  run, so it does not establish the claimed byte identity. The knife test also
  omits the `evaluate_unfits` assertion, no-carrier control, non-allergy speech
  cases, CLI transport, and freeze→load.
- The allergy probe produced `reject`, empty `last_plan`, a populated
  `evaluated_plan`, reasons equal to the bind, `validate_draft == []`, and an id
  in `evaluate_unfits`. Removing the peanut carrier produced a clean
  `unresolvable` rejection. The lazy `apply_knife` import is justified by the
  documented import cycle and worked in both unit and CLI paths.
- `tests/test_run_batch.py`: **23 passed**. Full suite: **1306 passed**. The
  valid synthetic CLI allergy recipe accepted one item; the bogus CLI key was
  rejected by argparse. Commit scope contains no ADR, split, sqlite, scorer,
  validator, review-harness, or quality-gates changes.

## Fix round (codex findings)

Review: "## Review (codex)" above (verdict REV). All six findings addressed;
touched resolver.py, run_batch.py, generate_batch.py, react-adjacent tests.

- **High 1 — knife input now bind-confirmed.** `_realize_evaluate_knife`
  binds the ORIGINAL plate against the same roster/occasion windows the
  unfit oracle pins (`bind_evaluate_reasons`); any pre-knife reason raises
  ("knife input plate does not fit …") → clean rejection. The oracle then
  reuses exactly those windows. Regression:
  `test_knife_input_that_does_not_fit_is_rejected` (kcal_lo plate never
  reaches the knife); `test_knife_recipe_produces_an_evaluate_unfit` asserts
  the allergy reason comes from the knife (reasons == bind of evaluated_plan,
  `validate_draft == []`). Fixture plate rebuilt to genuinely fit dinner:
  two cups of rice + two tablespoons of olive oil (~654 kcal in [544.6,
  726.14]).
- **High 2 — complete gram-exact plate speech.** `_name_knifed_foods`
  replaced by `_speak_knifed_plate`: the WHOLE knifed plate is re-spoken as
  "Evaluate this as <occasion>: <N> g of <food>, and … ." from table-backed
  grams, so bumped/stepped/dropped/swapped items can never contradict
  `evaluated_plan`. Test asserts each evaluated item's "<N> g of" appears in
  the query. **react.py symmetry:** no new agent-side convention was
  introduced — gram-explicit queries are already covered by the v1 manual
  line "Grams (\u2018150 g\u2019) are already grams", and evaluate actions
  are unchanged (submit_plan the exact named meal); pinned implicitly by the
  existing manual tests, so react.py itself needed no edit.
- **High 3 — frozen knife output reloadable.** The unfit Task now carries
  `situations=()` (reload-valid vocabulary; the unfit shape lives in the
  oracle geometry that `evaluate_unfits` already reads) instead of the
  unloadable `("evaluate_unfit", knife)` tags. Knife test now freezes →
  `load_split`s → asserts tier/verdict/`validate_draft == []` on the reload.
- **Medium 4 — per-family fail-closed parsing.** `_RECIPE_KEYS` is now a
  per-family map (evaluate: knife/occasion/tier; recommend: occasion/tier;
  update/log/composite: tier). Null and empty-string values are refused
  (`must be a non-empty string`), unknown keys refused with the family's
  allowed set, recipe families must appear in `family_quotas` (library-level,
  not just CLI), and knives are restricted to allergy/over_slot/under_slot.
  Tests: `test_recipe_null_value_is_refused`,
  `test_recipe_for_unrequested_family_is_refused`,
  `test_swap_knife_recipe_is_refused`,
  `test_recommend_shell_and_scene_recipes_are_refused_at_parse`.
- **Medium 5 — shell transport narrowed.** `shell` removed from the
  advertised recipe keys (library `_RECIPE_KEYS` and CLI `RECIPE_KEYS`);
  it stays a `Candidate` field for generate_one, which owns shell semantics.
  Documented here and in the resolver docstring; pinned by
  `test_recommend_shell_and_scene_recipes_are_refused_at_parse`.
- **High 6 — swap excluded from the batch channel.** `_BATCH_KNIVES =
  frozenset(KNIVES) - {"swap"}` at parse plus a defensive dispatch check;
  swap's kcal-derived grams violate the gram-anchor rule until it selects a
  catalog/QNS portion.
- Empty-recipe identity strengthened: `test_empty_family_recipes_behave_like_today`
  now runs the same spec with and without recipes and asserts task equality.

CLI note: against catalog-v1 the knife recipe now rejects cleanly on random
pools (the synthetic plate must first FIT dinner windows and the pool needs a
peanut carrier) — the deterministic fixture test is the end-to-end unfit
evidence.

## Fix-round verification

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
...........................                                               [100%]
26 passed

$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1309 passed in 47.86s
```

(Previously 1306; net +3 tests after restructuring, 0 failures.)
