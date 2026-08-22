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

## Re-review (claude opus)

**Verdict: REV.** All six codex findings are genuinely resolved — verified in
the code and re-probed end to end. The fix round, however, closes finding 3's
defect class only for `situations` and leaves the identical hole open on the
`tier` knob it also owns: `run_batch` still emits a frozen split that
`load_split` refuses. One further knob (`evaluate.occasion` without a knife)
silently no-ops, contradicting the fail-closed contract finding 4 established.
Both are inside the reviewed diff.

### Prior-finding status

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | High — knife input not bind-confirmed | **Resolved** | `resolver.py:519` binds the ORIGINAL plate with `bind_evaluate_reasons` against the same `windows`/`profile` the unfit oracle pins (`resolver.py:513`, reused at `:540`, `:548`). Probe: fitting plate → `reasons=('allergy','kcal_hi')`, rebind of `evaluated_plan` == `last_reasons`; half-a-cup-of-rice plate → `[('unresolvable','evaluate')]`, no bogus pre-overflow. |
| 2 | High — non-allergy knife speech contradicts `evaluated_plan` | **Resolved** | `_name_knifed_foods` gone; `_speak_knifed_plate` (`resolver.py:565`) re-speaks the whole plate from table grams. Probe over all three exposed knives (allergy / over_slot / under_slot): parsed query amounts == `evaluated_plan` amounts exactly in every case; `validate_draft == []`. react.py correctly untouched — the fix *removed* the novel `plus FOOD` wording instead of adding one, and gram-explicit speech is already covered by the v1 manual line "Grams (\"150 g\") are already grams" (`harness/react.py:75`). Discipline 4 satisfied. |
| 3 | High — frozen knife result not reloadable | **Resolved (for `situations`)** | `situations=()` at `resolver.py:557`; `evaluate_unfits` reads oracle geometry (`quality_gates.py:237`), asserted in `test_knife_recipe_produces_an_evaluate_unfit` alongside a real freeze → `load_split` → `validate_draft` round trip. See NEW-1: the same class re-opens via `tier`. |
| 4 | Medium — recipe parsing not fail-closed | **Resolved (with one gap)** | Per-family `_RECIPE_KEYS` (`run_batch.py:412`). Probes: `evaluate:tier=null` → "must be a non-empty string"; `evaluate:tier=3` → same; `recommend:knife=allergy` → "not supported for 'recommend'"; `evaluate:knife=bogus` → "unsupported evaluate knife"; recipe for a family absent from `family_quotas` → refused at the **library** API. Gap: see NEW-2. |
| 5 | Medium — Recommend shell transport | **Resolved (authority narrowed)** | `shell`/`scene` removed from both `run_batch._RECIPE_KEYS` and `scripts/generate_batch.py:53`; `_realize_recommend` keeps the loud guard as defence in depth (`resolver.py:394`) and its docstring now says generate_one-only. Probes: `recommend:shell=…` and `recommend:scene=leftover` both raise at parse. Consistent across CLI, library, and docstring. |
| 6 | High — swap knife exposed | **Resolved** | `_BATCH_KNIVES = frozenset(KNIVES) - {"swap"}` (`run_batch.py:419`) plus the dispatch guard at `resolver.py:497`. Probe: `evaluate:knife=swap` → `ValueError: unsupported evaluate knife 'swap' (allowed: ['allergy','over_slot','under_slot'])`. |

### New findings

- **High — the `tier` recipe value is unvalidated, so `run_batch` freezes an
  unloadable split** (`src/nutrienv/bench/pipeline/run_batch.py:449`). The
  parser only requires a non-empty string; nothing checks the value against
  `EVALUATE_TIERS`. `family_recipes={"evaluate": {"tier": "bogus-tier"}}` is
  accepted, `validate_draft` returns `[]`, `freezer.py:112` writes
  `"tier": "bogus-tier"`, and `load_split` on run_batch's **own** output file
  raises `ValueError: v10-evaluate-0001: tier must be empty or one of
  ['explicit_grams','long','pair','single','synonym','triple']`. This is
  finding 3's defect verbatim — a newly emitted batch artifact that cannot be
  loaded end to end — re-entering through the other knob the same commit
  hardened. It is reachable from the documented CLI (`--recipe
  evaluate:tier=bogus`; `scripts/generate_batch.py:53` advertises `tier` and
  validates no value either).
  A second half of the same hole: `_RECIPE_KEYS` allows `tier` for `log`,
  `update`, and `composite`. `family_recipes={"log": {"tier": "single"}}` is
  accepted and produces a reloadable but semantically wrong row — a tiered
  log — which `generate_one` explicitly forbids with a stated rationale
  ("tier is evaluate-only authoring data … so nobody can invent a tier or tier
  a log", `generate_one.py:165-173`). The mill and the batch now disagree on
  the same invariant.
  **Fix:** mirror the mill's guard in `_parse_family_recipes` — `tier` only for
  `evaluate`, value only from `EVALUATE_TIERS` — and add a freeze→load
  assertion for a bogus tier, the same shape as the knife one.

- **Medium — `evaluate.occasion` without a knife is silently ignored**
  (`src/nutrienv/bench/pipeline/resolver.py:466`). `occasion` is in evaluate's
  allowed key set, but `_realize_evaluate` never reads `candidate.occasion`;
  only `_realize_evaluate_knife` does (`resolver.py:509`). Probe:
  `{"evaluate": {"occasion": "breakfast"}}` and `{"evaluate": {"occasion":
  "lunch"}}` each produce a task **equal** to the no-recipe run (`a == b == c`,
  `plan_windows is None`). That is exactly the behaviour `_RECIPE_KEYS`'s own
  docstring says the parser refuses: "A key outside the family's set would be
  silently dropped or ignored by the realize branch, so the parser refuses it."
  **Fix:** either require `knife` alongside `occasion` for evaluate, or drop
  `occasion` from evaluate's allowed set and let the knife branch read it from
  the query, so no accepted knob is a no-op.

- **Low — `fit_task` is now a dead parameter**
  (`src/nutrienv/bench/pipeline/resolver.py:481`). `_realize_evaluate_knife`
  never references it; `_realize` still builds the full legacy fit oracle at
  `:466` and discards it. The call is not entirely inert (its `realize()` can
  raise and reject a candidate whose query does not contain the spoken foods),
  but that gate is implicit and unnamed. Either drop the parameter or make the
  containment intent explicit.

- **Low — producer asymmetry on the situations contract (pre-existing,
  outside this diff).** `generate_one.py:956` still stamps
  `("evaluate_unfit", knife)`, neither of which is in `SITUATIONS`;
  `_situations(['evaluate_unfit','allergy'])` raises `unknown situations`. The
  batch is now reloadable while the mill's knife output is not, so the
  rationale committed here ("the unfit shape lives in the oracle geometry") is
  not yet the project-wide contract. Worth a follow-up so the two producers
  agree.

- **Low — test fixture writes `catalog["olive_oil"]` twice**
  (`tests/test_run_batch.py:341` and `:351`). The first block, including its
  `dict(_STAPLE_NUTRIENTS["olive_oil"])` read, is fully overwritten by the
  second. Dead code introduced by this commit.

- **Low — plate speech reads "A, and B, and C"**
  (`src/nutrienv/bench/pipeline/resolver.py:583`, `', and '.join(parts)`).
  Probe output: "Evaluate this as dinner: 316 g of rice, and 27 g of olive oil,
  and 16 g of peanut butter." Ungrammatical for 3+ items where the mill's LLM
  rewriter would produce natural speech. Stage B votes on the spoken request so
  it would alarm rather than pass silently, but the deterministic rewriter
  should not be generating text the speech gate is expected to catch.

### Evidence

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
26 passed in 0.22s

$ .venv/bin/python -m pytest -q
1309 passed in 48.95s          # 0 failed
```

Probes (fixture catalog, `pass_through_reviewer` → `stage_a_code_gate`):

```
[1a fit->knife]  reasons=('allergy','kcal_hi')  rebind-match=True
                 query="Evaluate this as dinner: 316 g of rice, and 27 g of
                 olive oil, and 16 g of peanut butter."
                 spoken == evaluated_plan grams: True
[1b unfit-input] accepted=0  rejected=[('unresolvable','evaluate')]
[over_slot]      GRAM-EXACT=True   [under_slot] GRAM-EXACT=True
[6 swap]         ValueError: unsupported evaluate knife 'swap'
[4 null/int/bogus-knife/cross-family/unrequested-family]  all raise
[5 shell/scene]  ValueError: recipe key … is not supported for 'recommend'
[NEW-1 tier]     accepted, Task.tier='bogus-tier', validate_draft=[],
                 load_split(run_batch output) -> ValueError: tier must be
                 empty or one of [...]
[NEW-1 log tier] accepted, family=log tier='single', reloads OK
[NEW-2 occasion] task(occasion=breakfast) == task(no recipe) == task(lunch)
```

Alias fallback in `_speak_knifed_plate` checked against the real catalog: of
5431 foods, 0 would fall back to a `food_id` slug (5404 have no alias but a
speakable comma-free or comma-headed name), so no slug can leak into exam
speech. Catalog portion grams all have ≤2 decimals, so the `round(grams, 2)`
in the rewriter is lossless for portion-table amounts.

Commit scope confirmed: `188a2ee` touches `reports/impl-recipe-channel.md`,
`scripts/generate_batch.py`, `resolver.py`, `run_batch.py`,
`tests/test_run_batch.py` only — no ADR, split, sqlite, scorer, validator,
review-harness, or quality-gates change. `react.py` is correctly absent (see
finding 2).

**Blockers:** NEW-1 (High). NEW-2 (Medium) should land with it since both are
one-line guards in the same parser.

## Fix round 2 (claude opus findings)

Review: "## Re-review (claude opus)" above. All findings addressed.

- **NEW-1 High — tier value/family validated at parse.** `_RECIPE_KEYS` now
  carries `tier` only for `evaluate`, and `_parse_family_recipes` checks the
  value against `EVALUATE_TIERS` (imported from quality_gates) — mirroring
  generate_one's guard, so nobody can freeze a bogus tier or a tiered log.
  Tests: `test_bogus_tier_recipe_is_refused_at_parse`
  (`"tier must be one of"`), `test_tier_recipe_is_evaluate_only`
  (`log.tier` → "not supported for 'log'"). The valid-tier freeze→load
  round-trip stays pinned in `test_knife_recipe_produces_an_evaluate_unfit`.
- **NEW-2 Medium — evaluate.occasion knob removed.** `occasion` dropped from
  evaluate's allowed keys: the fit realize path never read it, so it was a
  silent no-op; the knife branch now derives the occasion from the spoken
  query ("… for dinner …"), consistent with the recommend branch.
  Regression: `test_evaluate_occasion_knife_is_no_longer_accepted` —
  `{"evaluate": {"occasion": "breakfast"}}` raises "not supported for
  'evaluate'" instead of producing an identical task. Knife fixture payload/
  recipe updated accordingly (query speaks "for dinner").
- **Low — dead `fit_task` parameter removed.** `_realize_evaluate_knife` no
  longer takes the discarded fit oracle; the named-foods gate it implicitly
  provided is now an explicit comment on the `_realize_evaluate` call site
  ("Building the fit oracle doubles as the named-foods gate…").
- **Low — plate speech join fixed.** `_speak_knifed_plate` emits a plain
  comma list ("316 g of rice, 27 g of olive oil, 16 g of peanut butter")
  instead of "A, and B, and C". No react.py change needed: no new agent-side
  convention (gram-explicit speech already covered by the v1 manual's "150 g"
  line).
- **Low — dead fixture write merged.** `_nutrient_catalog` writes
  `olive_oil` once (setdefault + update), removing the overwritten first
  block.
- Review-noted producer asymmetry (generate_one still stamps unloadable
  `("evaluate_unfit", knife)` situations) acknowledged as pre-existing and
  outside this diff's constraints (validator/split vocabulary untouched) —
  flagged as follow-up.

## Fix-round-2 verification

```
$ .venv/bin/python -m pytest tests/test_run_batch.py -q
.............................                                            [100%]
29 passed in 0.25s

$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1312 passed in 57.78s
```

(Previously 1309; net +3 tests, 0 failures.)
