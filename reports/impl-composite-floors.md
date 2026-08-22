# Impl report: composite recommend children count toward situation floors

Spec: `reports/spec-composite-floors.md` (ADR 0016). Commit: `fec223d`
("quality-gates: composite recommend children count toward ADR 0016 situation floors").

## What changed (`src/nutrienv/bench/quality_gates.py`)

- New `_Lens` frozen dataclass: `(oracle, profile)` — one recommend geometry
  carrier inside a task. Query/catalog stay on the parent task.
- New `_recommend_lenses(task)`: single-family recommend → `[Lens(task.oracle,
  task.s0.profile)]`; composite → one lens per child passing `_is_recommend_child`
  (`plan_windows is not None and last_plan == [] and plan_must_fit_windows`,
  mirroring validator `_validate_composite`); else `[]`. Lens profile is
  `child.profile or task.s0.profile` (validator S10-5: post-update children
  carry their own profile).
- New `_evaluate_lenses(task)`: symmetric — `[task.oracle]` for family
  evaluate; otherwise each sub-oracle child with `last_verdict == "reject" and
  last_plan == []`.

## Gates widened vs deliberately not

| Gate | Change |
|---|---|
| `constrained_recommends` | Widened: iterates `_recommend_lenses`; unpassable-pinned judged with lens oracle/profile; leftover scene = parent `s0.ledger` OR any child `ledger_tail`, plus lens `plan_windows`; named-dish trap still via `_query_names_allergen_food(task)` (spec: query+catalog shared), but only for tasks that have ≥1 lens (keeps evaluate/log singles excluded). Each task counted once even across multiple lenses/categories. |
| `leftover_recommends` | Widened: composite carriers count when (parent ledger or any child tail non-empty) AND some lens has `plan_windows`; persona==leftover legacy counting kept for single-family recommends. |
| `recommend_coverage` | Widened: personas of all carriers (parent persona) + union of lens profiles' allergies back the claim. |
| `evaluate_unfits` | Widened symmetrically via `_evaluate_lenses`: composite evaluate children (reject + empty plan) count. Single-family behavior identical. |
| `window_leaks` | Not changed (already widened for composites in 6039070). |
| `leftover_floor` | Not changed (derives from `leftover_recommends`, inherits widening). |
| `situation_floors` | Not changed structurally (derives from the two widened gates). |
| `evaluate_tier_coverage` | **Left as-is**: tiers live only on `Task.tier` (authoring data on the frozen row); child oracles carry no tier field, so there is nothing to widen. |

## Spec ambiguities and how they were resolved

1. `leftover_recommends` spec text could be read as requiring
   `plan_windows is not None` also in the single-family branch, which would
   break `test_leftover_recommends_count_by_scene_ledger_or_persona`
   (`rec-scene` has a ledger but a default oracle). Implemented the reading
   stated above: single-family keeps the old rule (persona OR ledger);
   composites require scene + pinned windows.
2. The named-dish trap category: spec says "`_query_names_allergen_food` keeps
   using `task`" — implemented literally (task profile/query/catalog), but the
   category only fires for tasks with at least one recommend lens, so
   `test_constrained_recommends_are_verified_hard_s0_items`'s evaluate item
   (`ev-x`) stays out exactly as before.

## Tests added (`tests/test_quality_gates.py`)

- `test_composite_recommend_child_counts_toward_constrained_floor`
- `test_composite_recommend_child_leftover_counts_toward_leftover_floor`
- `test_composite_allergen_child_counts_toward_coverage`
- `test_composite_evaluate_unfit_child_counts_toward_unfit_floor`

All compose children with `compose_oracles` and mirror existing `_task` /
`LedgerRow` / `Oracle` patterns; each includes a clean control task.

## Verification evidence

```
$ .venv/bin/python -m pytest tests/test_quality_gates.py -q
......................................                                   [100%]
38 passed in 0.44s

$ .venv/bin/python -m pytest -q
........................................................................ [ 83%]
........................................................................ [100%]
1287 passed in 50.45s
```

(Previously 1283 passed + 34 gates tests; now 1287 / 38 with zero failures or
weakened assertions.)

## Bookkeeping

- `.scratch/exam-generation-pipeline/issues/14-split-agnostic-quality-gates.md`:
  Status note appended under the situation-floors checkbox (checkbox itself
  still awaits a frozen exam).
- `reports/issue-consistency-audit.md`: 追记 noting item 2 (composite floor
  口径) is decided and landed.

## Review: composite floors (claude opus)

**Verdict: REV.** The carrier/lens widening is directionally consistent with
ADR 0016/0017, and both requested test suites pass, but two correctness issues
can miscount situation floors.

### Standards

- **Low — duplicated/misleading evaluate-lens predicate** —
  `src/nutrienv/bench/quality_gates.py:237-260`: `_evaluate_lenses` filters
  composite children by the complete unfit predicate, then `evaluate_unfits`
  repeats it; the helper returns all single-family Evaluate oracles but only
  already-unfit composite oracles. **Fix:** return actual evaluate carriers and
  apply the unfit predicate once, or replace the helper with a clearly named
  `_is_evaluate_unfit` predicate.

No hard `AGENTS.md` discipline is violated by this diff.

### Spec

- **High — named-dish traps ignore the recommend lens profile** —
  `src/nutrienv/bench/quality_gates.py:269-295,364`: the spec requires all
  constrained categories to be judged with `child.profile or s0.profile`, but
  `_query_names_allergen_food(task)` always reads `task.s0.profile`. A probe of
  an update→recommend that adds shellfish missed “shrimp?”, while the inverse
  removal case was falsely counted. **Fix:** accept lens allergies/profile in
  `_query_names_allergen_food` and count the task when any lens profile makes
  the shared query/catalog an allergy trap.

- **Medium — a hybrid recommend/reject child false-positively counts as
  Evaluate-unfit** — `src/nutrienv/bench/quality_gates.py:237-260` and
  `src/nutrienv/bench/validator.py:738-780`: reject + empty plan is not mutually
  exclusive with the recommend-child shape. Replacing a mill-generated
  recommend child's verdict with `reject` made `evaluate_unfits` count it, and
  `validate_draft` returned no issues. **Fix:** require genuine Evaluate
  evidence (for example `evaluated_plan is not None` and no recommend fitting
  contract), and/or make the composite validator reject verdict-bearing
  recommend children.

- **Low — the “same test as validator” claim is not exact** —
  `src/nutrienv/bench/quality_gates.py:308-314` requires non-`None`
  `plan_windows`, whereas `src/nutrienv/bench/validator.py:759-778` recognizes a
  recommend leg from empty `last_plan` + `plan_must_fit_windows` and can fall
  back to profile windows. **Fix:** centralize the child-family discriminator or
  explicitly document and validate the stricter pinned-window gate contract.

- **Low — spec bookkeeping is not in commit `fec223d`** — the commit contains
  only the gate and test files, although spec lines 106-108 require the issue
  note and consistency-audit update. **Fix:** include those records in a
  traceable follow-up commit if they are part of the landing definition.

### Correctness / edge cases

- The leftover asymmetry is defensible for the current mill: legacy
  single-family rows retain persona/ledger counting, while both current
  composite recommend constructors pin non-`None` remainder windows. No
  default-window composite recommend is emitted by the mill. The validator is
  looser, however, so the discriminator-drift finding above is a forward/manual
  authoring risk rather than a current mill undercount.
- `constrained_recommends` appends an id only after the lens/category loops, so
  multiple matching children/categories do not duplicate-count a task.
  Requiring at least one lens correctly keeps evaluate/log singles and
  evaluate/log/update-only composites out of named-dish recommend counting.
- `recommend_coverage` correctly uses the parent persona and unions lens
  profiles. A real S10-5-style update→recommend probe carried shellfish only on
  the child profile and closed shellfish coverage.
- A normal mill recommend child has `last_verdict is None`, so it does not match
  `_evaluate_lenses`; nevertheless, the validator-admitted hybrid above proves
  the widened predicate is not false-positive-safe on all admitted inputs.
- `Task.tier` is task-level authoring data and `Oracle` has no tier field, so
  leaving `evaluate_tier_coverage` unchanged is correct.
- A single-family `family == "recommend"` always receives a lens, even with a
  default oracle. A composite with only evaluate/log/update children receives
  no recommend lens and is correctly excluded from recommend geometry gates.

### Test quality

The four added tests exercise real before/after behavior and contain clean
controls; the diff only adds tests and does not weaken existing assertions.
They do not cover the two failures above. Add (1) post-update add/remove
allergen named-dish controls and (2) a reject-bearing recommend-shape control
that must either fail validation or remain outside `evaluate_unfits`.

Verification rerun: `tests/test_quality_gates.py` — **38 passed**; full suite —
**1287 passed**. No code was edited or merged by the reviewer.

## Fix round (codex findings)

Review: lines above ("## Review: composite floors"), verdict REV. Fixes on
main; no changes to validator.py / scorer.py / ADRs / splits.

- **High — named-dish trap now judged per lens profile.**
  `_query_names_allergen_food(task, allergies)` takes the caller's allergy
  set; `constrained_recommends` passes each lens's `lens.profile.allergies`
  inside the lens loop (single-family unchanged: lens profile == s0.profile).
  Post-update add/remove allergen cases now count correctly.
- **Medium — verdict-bearing recommend children excluded from unfit.**
  `_evaluate_lenses` now requires genuine evaluate evidence for composite
  children: `evaluated_plan is not None` AND NOT `plan_must_fit_windows`
  (a recommend fitting contract). Single-family evaluate path is untouched
  (family-keyed), so legacy/realized evaluate oracles that carry
  `plan_windows` still count via their own family. Unfit predicate moved to
  a single shared `_is_evaluate_unfit` (Low finding #1).
- **Low — discriminator documented, not centralized.** `_is_recommend_child`
  docstring now states the gate contract is deliberately stricter than
  validator.py (pinned windows required; no profile-window fallback), with
  `test_recommend_child_without_pinned_windows_counts_toward_no_lens` pinning
  that such a child counts toward neither recommend nor evaluate lenses.
- **Low bookkeeping:** this commit also lands the previously untracked
  spec/reports (`reports/spec-composite-floors.md`,
  `reports/issue-consistency-audit.md`, this file). The `.scratch` issue note
  lives outside git tracking.

New tests (`tests/test_quality_gates.py`):
`test_composite_named_dish_allergen_trap_uses_child_profile`,
`test_composite_verdict_bearing_recommend_child_not_unfit`,
`test_recommend_child_without_pinned_windows_counts_toward_no_lens`.
Existing `test_composite_evaluate_unfit_child_counts_toward_unfit_floor`
already builds its genuine child with `evaluated_plan=[_FOOD]`, reject +
empty plan — verified sufficient, left as-is.

Evidence:

```
$ .venv/bin/python -m pytest tests/test_quality_gates.py -q
.........................................                                [100%]
41 passed in 0.49s

$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1290 passed in 44.63s
```
