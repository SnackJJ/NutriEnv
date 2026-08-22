# Impl 10 — composite log-remainder closeout (ship-10)

Branch `ship-10`, started from b20273c ("WIP: 10 fix round interrupted by grok
weekly quota wall"). Full suite at finish: **1217 passed, 0 failed**
(baseline on this branch was 1206 passed / 9 failed; the 7 environmental
catalog failures were already fixed here by copying gitignored
`data/fdc/raw/*.zip` into the worktree, and the 2 real issue-10 failures are
fixed below).

## What changed

### 1. Validator: composite Recommend remainder + unpassable on the child
`src/nutrienv/bench/validator.py` — `_validate_composite` now mirrors
`run_batch._composite_draft_issues` at admission time:

- Collects the log tail (first child with `ledger_tail`).
- For each recommend child (`last_plan == []`, `plan_must_fit_windows`):
  - **Remainder**: when `task.persona == "leftover"`, the child's
    `plan_windows` must equal the pure daily remainder after
    `s0.ledger + tail` (`round(max(0, lo-used), 2)` per key), matching the
    existing single-family leftover rule. Issue text:
    `composite plan_windows {key} != remainder {expected}`.
    Non-leftover composites keep judging the meal-slot intersection the mill
    pinned via `plan_windows_for_meal`, so valid drafts stay admissible.
  - **Unpassable**: `fitting_plan(catalog, plan_windows or s0 windows,
    s0 allergies) is None` → `composite recommend is unpassable`.
- Update children still route through `_validate_update`.

Fixes both previously failing tests:

```
tests/test_generate_one_composite.py::test_validator_checks_composite_recommend_remainder_on_the_child PASSED
tests/test_generate_one_composite.py::test_validator_checks_composite_recommend_is_passable_on_the_child PASSED
```

### 2. Slot accounting aligned to ADR 0016 (P4)
ADR 0016 supersedes ADR 0013's "240 base + composite extra": the 36 composite
slots sit **inside** the published 240 with the same roster.

- `pipeline/types.py`: `COMPOSITE_EXTRA_QUOTA = 24` → `COMPOSITE_ADMISSION_SLOTS = 36`
  (comment cites ADR 0016); `__all__` updated.
- `pipeline/generate_one.py`: imports the constant from `.types` instead of
  defining a second copy; public name unchanged.
- `run_batch.quota_ledger`: docstring now states ADR 0016; keys renamed
  `base_quota`→`exam_quota`, `composite_extra_quota`→`composite_admission_slots`,
  `base_accepted`→`single_family_accepted`. Composite vs single-family counts
  remain separate so drift from either slice stays visible.
- Tests updated to the aligned keys (bookkeeping only; no scoring change):
  `test_pipeline_composite.py` (2 sites), `test_composite_split.py`.
  ADR 0013 decision text untouched.

### 3. react.py manual symmetry (S3)
The mill teaches three composite chains (`templates/expander`: "already ate …
AND wants a recommendation", update+recommend "allergic to shrimp … what's for
dinner?", log+evaluate "Is this lunch okay?"). The agent manual taught only
log+next-meal. `_SYSTEM` in `src/nutrienv/harness/react.py` line 51 now reads:

> Text is not a hand-in: recommend/evaluate Pass only via submit_plan, log only
> via log_meal. A multi-step query needs every step's write: ate then "what to
> eat next" is log_meal then submit_plan; allergy change then dinner ask is
> update_profile then submit_plan; ate then "is this okay?" is log_meal then
> verdict=accept.

Two verbose bullets were condensed to keep the frozen budget
(`len(v0.split()) <= 400`; now exactly 399). New test:
`test_react_manual_teaches_composite_chains_need_every_write`.

### 4. Audible-gate audit (S4)
Verified fail-closed behavior of `_composite_speech_spans` / rec-span food
rejection / log-span binding (only-logs, named dinner foods, food-after-ask,
empty log span all reject). One genuine hole found and fixed:

- `validate_draft` applied `_WINDOW_LEAK` only when `family == "recommend"`,
  but composites carry family `"log"`/`"update"` — a rec-step window number
  ("… kcal 800") slipped past admission. Now composites
  (`task.oracle.sub_oracles`) get the same whole-query window-leak gate.
  New test: `test_validator_rejects_window_numbers_in_the_composite_query`.

### 5. Legal-pairs freeze survival audit (P3)
Probed `generate_one → task_to_item → load_split` for all three legal pairs.
Findings and fixes in `pipeline/freezer.py` / `pipeline/generate_one.py`:

1. Composite container serialized `"profile": "s0"`; the loader resurrected a
   full Profile where the fresh task has `profile=None` (parent fields unused).
   Freezer now omits the key for containers.
2. Evaluate children always serialized `"ledger": "s0"`, losing a non-S0
   ledger (log+evaluate child carries `s0+tail`) → loaded ledger was wrong.
   New `_ledger_payload` writes `"s0"` when equal to S0's, else explicit rows.
3. Update children carried `ledger=()` but no key → loaded as `None` →
   `validate_draft` on reload said "update oracle ledger is missing".
   Covered by the same fix.
4. log+evaluate composites were tagged `("multi_item_log", "evaluate_fit")`;
   `evaluate_fit` is not in the closed split vocabulary (`bench/situations.py`)
   so a frozen item could never load. Retagged to `("multi_item_log",)` — the
   same tag log+recommend composites already use; the evaluate-fit shape lives
   in the child oracle's accept verdict.

Result — all three pairs round-trip with identical oracles and empty draft
issues (probe script, post-fix):

```
log+recommend:    oracle_identical=True draft_issues_loaded=[]
log+evaluate:     oracle_identical=True draft_issues_loaded=[]
update+recommend: oracle_identical=True draft_issues_loaded=[]
```

## Test evidence

```
$ python -m pytest tests/test_generate_one_composite.py -q
13 passed in 0.18s

$ python -m pytest -q
1217 passed in 49.96s
```

Suite delta vs baseline: 1206 passed/9 failed → 1217 passed/0 failed
(+2 issue-10 validator tests pre-existing from WIP, +2 new tests added here:
react composite chains, composite window-number leak; net +9 pass, −9 fail).

## Not done / notes

- Mill evaluate tags outside the vocabulary beyond issue-10 scope:
  single-family evaluate items tag `("evaluate_fit",)` and knife items
  `("evaluate_unfit", knife, …)` — freezing those through `freeze_tasks`
  would also fail `load_split`. Same root class as P3(4); left untouched
  because run_batch freezes only log/evaluate/composite families whose
  current shapes survive, and retagging evaluate items belongs to ticket 07
  follow-up if mills ever feed the freezer directly.
- `reports/composite-quota-ledger.md` still shows the old ADR-0013 keys;
  it is a historical report, not code, and was left as-is.
