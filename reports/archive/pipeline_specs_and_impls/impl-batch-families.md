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

## Review (codex)

**Verdict: REV.** The five-family dispatch, oracle shapes, update evidence,
gram handling, and quota accounting work on the tested paths, but one hard
project-discipline violation and two resolver acceptance gaps must be fixed.

### Standards

- **High — new question expressions were not synchronized into the agent
  manual** — `src/nutrienv/bench/pipeline/expander.py:197-228` adds “eat along
  with …” Recommend and “now allergic to …, so no more …” Update expressions,
  while `src/nutrienv/harness/react.py:49-63` was unchanged. This violates
  `AGENTS.md` hard discipline 4 and leaves the named Recommend food's role
  ambiguous to the agent. **Fix:** add concise `react.py` guidance for both
  expressions (especially whether the named accompaniment is context or part
  of the submitted plan) and pin the symmetry with a test.

- **Low — misleading containment comment** —
  `src/nutrienv/bench/pipeline/resolver.py:78-91` says context foods must still
  be named, but the `context_only` branch skips both gram back-resolution and
  containment. **Fix:** move containment outside the gram-only conditional
  (also resolving the correctness finding below).

No other documented-standard violation or material baseline smell was found.

### Spec

- **Medium — occasion-less Recommend silently receives dinner geometry** —
  `src/nutrienv/bench/pipeline/resolver.py:391`: `occasion_from_query(...) or
  "dinner"` accepts an unresolved query and pins dinner windows. A manual probe
  of “What should I eat?” produced a six-key dinner oracle and
  `validate_draft == []`. This contradicts `occasions.py:1-6`, whose shared
  contract says unresolved occasions return `None` so callers fail loudly.
  **Fix:** reject/raise when `occasion_from_query` returns `None`, and add an
  occasion-less regression test.

- **Medium — Recommend/Update context containment is unintentionally
  disabled** — `src/nutrienv/bench/pipeline/resolver.py:81-91`: setting
  `context_only` bypasses the enclosing block, so a Recommend payload can name
  an arbitrary item absent from its query and still pass `resolve_candidate`,
  `validate_draft`, and Stage A. The implementation report says containment
  remains enforced. **Fix:** skip only `query_backresolves_oracle` for these
  families; run `_mentioned` containment for every non-global-skip candidate.

- **Low — the documented smoke does not cover the full DoD family matrix** —
  `reports/impl-batch-families.md:54-79` exercises Recommend, Update, and a
  Composite whose task-level family is Log, but no single Log or Evaluate;
  spec lines 49-50 require all five through `generate_batch`. **Fix:** record a
  five-family synthetic smoke or cite equivalent existing CLI evidence for the
  missing singles.

No other spec mismatch or scope creep was found.

### Correctness and accounting

- `_realize_recommend` has the correct free-plan shape: empty `last_plan`,
  safe + fits-windows contracts, empty ledger, and six-key meal windows derived
  from the same ROSTER profile source as Composite. A dinner probe passed
  `validate_draft`, `validate_oracle_grams`, and Stage A. Only the unresolved
  occasion fallback is incorrect.
- `_realize_update` derives additions from the resolved foods' catalog tags,
  preserves windows, and is independently checked by `_validate_update` for
  tag-level query evidence. The valid egg probe passed; a query claiming soy
  while resolving egg produced `update allergy egg is not evidenced in the
  query`. A tagless synthetic pool returns an empty payload and is
  schema-dropped. There is no observed false-positive update path.
- Skipping **gram back-resolution** for Recommend/Update is correct: neither
  oracle carries `ledger_tail`, `last_plan` items, nor `evaluated_plan` grams;
  `validate_oracle_grams` and Stage A therefore have no oracle gram pairs to
  check. The skip should not also disable query containment.
- `quota_ledger` counts any task with `sub_oracles` exactly once as Composite,
  and every other task once under `task.family`; Recommend/Update singles count
  toward 240 and Composite remains capped at 36. No double-count was found.
- The composite `1 oz` → 28.35 g versus table `oz` → 20 g Stage-A rejection is
  pre-existing: the same seed/count command produced one `code_gate` rejection
  on both parent `6f79dd5` and the reviewed checkout.

### Test quality and verification

The three new tests assert real end-to-end behavior. In particular,
`test_recommend_family_job_yields_a_recommend_task` pins the exact former
Recommend→Log dispatch bug; `result.rejected == []` also proves the internal
draft and code gates passed. Add regression controls for unresolved occasion
and context containment.

- `tests/test_run_batch.py`: **16 passed**.
- Full suite: **1293 passed**.
- Commit scope contains no ADR, split, SQLite, scorer, validator, or review
  harness change.
- Review-only: no code was edited or merged.

Summary: Standards has **2 findings** (worst: High manual-symmetry violation);
Spec has **3 findings** (worst: Medium resolver acceptance errors).

## Fix round (codex findings)

Review: "## Review (codex)" above (verdict REV). Fixes on main; only
`resolver.py`, `expander.py`-adjacent tests, and `harness/react.py` touched.

- **High — react.py manual symmetry (AGENTS.md discipline 4).**
  `_SYSTEM_V1_TAIL` gained two lines: Recommend "eat along with X" is spoken
  context — the agent submits its OWN safe meal via `submit_plan`; Update
  "now allergic to Y, so no more Z" means `update_profile` adds the catalog
  tag for Y and never `log_meal`/`submit_plan` Z afterwards. Pinned by
  `test_react_manual_covers_synthetic_recommend_and_update_speech`
  (tests/test_expander.py), mirroring `test_react_manual_covers_new_update_speech`.
  v0 budget untouched (lines live in the v1 tail).
- **Medium — occasion-less Recommend no longer defaults to dinner.**
  `_realize_recommend` raises `ValueError("recommend query names no meal
  occasion")` when `occasion_from_query` returns None (occasions.py
  fail-loud contract), which `resolve_candidate` turns into an
  `unresolvable` rejection. Regression test:
  `test_occasion_less_recommend_is_rejected_not_dinner_defaulted`.
- **Medium — containment re-enabled for recommend/update.** The
  `context_only` flag now skips ONLY gram back-resolution; the `_mentioned`
  containment loop runs for every candidate whenever
  `skip_gram_backresolve` is false. Regression test:
  `test_recommend_context_food_absent_from_query_is_containment_rejected`
  (egg named in items but absent from the query → `containment` rejection).
- **Low — five-family smoke matrix recorded:**

```
$ .venv/bin/python scripts/generate_batch.py --synthetic --model synthetic \
    --count 1 --family log --family evaluate --family recommend \
    --family update --family composite --seed 20260822 --workers 1 \
    --output /tmp/opencode/batch-five-families-smoke.json --force
pools=5 candidates=5 accepted=5
ledger: {'single_family_accepted': {'evaluate': 1, 'log': 1,
         'recommend': 1, 'update': 1}, 'composite_accepted': 1, ...}
freeze -> load_split -> validate_draft:
v10-composite-0001 log OK / v10-evaluate-0002 evaluate OK /
v10-log-0003 log OK / v10-recommend-0004 recommend OK / v10-update-0005 update OK
```

## Fix-round verification

```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1296 passed in 49.16s
```

(Previously 1293; +3 regression/symmetry tests, 0 failures.)

## Re-review (codex)

**Verdict: ACC.** Commit `343399a` resolves all four findings from the first
review. No new code or spec blocker was found.

| Prior finding | Status | Re-review evidence |
|---|---|---|
| High — `react.py` manual symmetry | **Resolved** | The two rules live in `_SYSTEM_V1_TAIL`; v0 is untouched. Recommend explicitly says X is spoken context, not part of the submitted plan, and directs the agent to submit its own safe plan. Update directs `update_profile` with the catalog tag and forbids logging/submitting Z. `test_react_manual_covers_synthetic_recommend_and_update_speech` pins the expression and action vocabulary. |
| Medium — occasion-less Recommend defaulted to dinner | **Resolved** | `_realize_recommend` now raises when `occasion_from_query` returns `None`; `resolve_candidate` converts that to `unresolvable`. The regression test and a direct probe both produced no task and `("unresolvable", "recommend")`. |
| Medium — Recommend/Update containment disabled | **Resolved** | `context_only` now skips only `query_backresolves_oracle`; `_mentioned` containment remains active whenever the explicit global skip is false. The regression test and direct absent-food probe both returned `containment`. The valid egg Update still resolved with `validate_draft == []`, so tag-evidence handling remains intact. |
| Low — incomplete five-family smoke | **Resolved** | The documented command was replayed independently: five pools/candidates yielded five accepted tasks — single Log, Evaluate, Recommend, Update, and one Composite carrier. Reloaded tasks all returned `validate_draft == []`, and accounting classified each family exactly once. |

### Standards

The prior hard `AGENTS.md` symmetry violation is closed. Applying the prose
contract confirms both manual lines are concise, imperative, and unambiguous:
they name the triggering speech, required operation, and prohibited action.
Because the additions are confined to `_SYSTEM_V1_TAIL`, the v0 manual and its
budget are unchanged.

One new **Low, non-blocking prose finding**:
`tests/test_expander.py:364-366` says the runtime test proves expressions land
“in the same commit,” which a runtime assertion cannot establish; it also
checks assembled v1 text rather than tail placement. **Fix:** describe only the
enforceable manual-symmetry contract in the docstring, or directly assert tail
placement if placement itself is required.

No actionable baseline code smell was found.

### Spec

All previous spec findings are resolved. Occasion resolution now follows the
shared fail-loud contract; containment and gram back-resolution have separate
conditions; and the complete five-family CLI matrix is evidenced. No scope
creep or forbidden-path change was found in `343399a`.

### Verification

- `tests/test_expander.py tests/test_run_batch.py tests/test_react.py`:
  **75 passed**.
- Full suite: **1296 passed**.
- Direct probes: occasion-less → `unresolvable`; absent context →
  `containment`; valid egg Update → accepted with no draft issues.
- Five-family CLI smoke: **5/5 accepted**, reload validation clean.
- Review-only: no code was edited or merged.

Summary: Standards has **1 Low prose finding**; Spec has **0 findings**.
