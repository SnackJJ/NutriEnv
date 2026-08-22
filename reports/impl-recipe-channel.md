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
