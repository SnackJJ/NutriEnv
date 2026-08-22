# Impl report: enable recommend/update families in the batch orchestrator

Spec: `reports/spec-batch-families.md` (ADR 0016). Commit on main, prefix
"pipeline:".

## What changed

- `src/nutrienv/bench/pipeline/types.py`: `SUPPORTED_FAMILIES` widened to
  `{log, evaluate, recommend, update, composite}`. `_parse_spec`
  (`run_batch.py`) and `scripts/generate_batch.py` argparse `choices` both
  reference `SUPPORTED_FAMILIES`, so they picked up the new families without
  edits — `--family recommend` / `--family update` parse (verified).
- `quota_ledger`: **no change needed** — it classifies generically (any task
  with `sub_oracles` counts as composite; everything else is counted per
  `task.family`), so recommend/update single-family accepteds count against
  `BASE_EXAM_QUOTA` (240) and composite stays capped at 36. Covered by a new
  test.
- Real bug found by the smoke (and fixed): `resolve_candidate._realize` only
  dispatched evaluate/log/composite — a `recommend`-family candidate was
  silently realized as a **log** task. Fixes:
  - `resolver.py`: new `_realize_recommend` (free-plan oracle:
    `last_plan=[]`, safe+fits-windows, `plan_windows` =
    `plan_windows_for_meal(ROSTER[0] windows, {}, occasion-from-query)`, same
    six-key window source as the composite leg) and `_realize_update`
    (add-allergy profile patch: named food's catalog allergen tags become the
    oracle's added allergies, so the change is always query-evidenced;
    windows untouched so they stay world-derived). Gram-backresolve is now
    skipped for recommend/update candidates (their oracles carry no bound
    grams); containment/leak checks still apply.
  - `expander.py` `synthetic_expander`: recommend payload ("What should I eat
    along with {meal} for dinner?" — foods stay spoken context, no window
    numbers) and update payload (names an allergen-carrying pool food AND its
    tag words, e.g. "I am now allergic to egg, so no more Egg." — validator
    demands tag-level evidence; a pool with no allergen food yields no
    candidate, fail-closed).
  - `sampler.py`/`types.py`: `PoolFood` gained `allergen_tags` (populated by
    `sample_pools`; default `()` keeps hand-built fixtures compatible).

Not touched (per constraints): validator.py, review_harness.py, scorer.py,
ADRs, splits, sqlite.

## Known limitations (documented, not fixed)

- Non-synthetic (LLM-expander) runs can now *request* recommend/update, but
  prompt shells for these families are not wired in `build_system_prompt`;
  quality of LLM-driven recommend/update payloads is mill-ticket territory.
- Pre-existing, unrelated to this diff: the composite tracer at seed 20260822
  against catalog-v1 can draw a pool whose log leg binds "1 oz" to 28.35 g
  while the table maps oz→20 g, failing the Stage-A code gate
  (`grams_off_table`). Reproduced identically with the diff stashed.

## Smoke evidence

Exact spec counts via `run_batch` (synthetic roles, catalog-v2, seed 20260822,
quotas recommend=2 / update=1 / composite=1):

```
rejected: []
accepted: ['log', 'recommend', 'recommend', 'update']   # 'log' = composite carrier (sub_oracles)
ledger: {'exam_quota': 240, 'composite_admission_slots': 36,
         'single_family_accepted': {'recommend': 2, 'update': 1},
         'composite_accepted': 1,
         'requested': {'composite': 1, 'recommend': 2, 'update': 1}}
freeze -> load_split -> validate_draft: OK on every item
(v10-composite-0001 log OK; v10-recommend-0002/0003 recommend OK; v10-update-0004 update OK)
```

CLI smoke (draft output to /tmp, nothing published):

```
$ .venv/bin/python scripts/generate_batch.py --synthetic --model synthetic \
    --count 2 --family recommend --family update --family composite \
    --seed 20260822 --workers 1 --output /tmp/opencode/batch-families-smoke.json --force
pools=6 candidates=6 accepted=5
per-model accepted: synthetic=6
rejections: code_gate=1          # pre-existing composite/pork oz issue, see above
ledger: ... 'single_family_accepted': {'recommend': 2, 'update': 2}, 'composite_accepted': 1 ...
reload validate_draft: v10-composite-0001 OK, v10-recommend-0003 OK,
                       v10-recommend-0004 OK, v10-update-0005 OK, v10-update-0006 OK
```

## Tests

`tests/test_run_batch.py` (+3):

- `test_quota_ledger_counts_recommend_and_update_against_the_exam` —
  recommend/update count as single families toward 240; exceeding raises.
- `test_recommend_family_job_yields_a_recommend_task` — end-to-end
  recommend-family job: family == "recommend", free-plan oracle with pinned
  windows, zero rejections.
- `test_update_family_job_yields_an_add_allergy_update_task` — end-to-end
  update-family job: add-allergy oracle ({'egg'}), ledger not None, no band,
  zero rejections.

No existing test hardcoded the old 3-family set (verified by grep).

## Verification

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1293 passed in 42.88s
```

(Previously 1290; +3 new tests, 0 failures.)
