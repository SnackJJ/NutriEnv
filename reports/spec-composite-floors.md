# Spec: composite recommend children count toward situation floors (ADR 0016)

**Status:** decided by coordinator (issue-consistency-audit follow-up). Design authority:
`docs/adr/0016-four-families-constrain-is-situation.md` — "Situation floors sit **inside**
evaluate / recommend"; "Remainder/leftover geometry stays a Recommend situation (ADR 0009's 24
leftover recommends)"; "Composite children are any of the four families".

## Problem

`src/nutrienv/bench/quality_gates.py` counts situation floors by `task.family`:
- `constrained_recommends` / `leftover_recommends` / `recommend_coverage` filter
  `task.family == "recommend"` only.
- But ADR 0016 puts constrain/leftover geometry **inside recommend**, and a composite task
  (family `log`/`update`) carries a **recommend child oracle** that implements exactly that
  recommend geometry (pinned `plan_windows`, remainder-after-log, possible allergy trap).
- Result: when the exam freezes composite items, their recommend geometry contributes **zero**
  to the recommend situation floors — silently undercounting against ADR 0016's 8 constrained /
  24 leftover minimums.

## Decision

A task "is a recommend geometry carrier" if either:
- `task.family == "recommend"` (existing single-family case), or
- `task.oracle.sub_oracles` is non-empty and **at least one child is a recommend child**.

A **recommend child** of a composite is a sub-oracle with `plan_windows is not None` and
`last_plan == []` and `plan_must_fit_windows` truthy (the same test ship-10's validator uses to
identify the recommend leg — see `src/nutrienv/bench/validator.py` `_validate_composite`).

For each carrier, the geometry judgment applies to **each recommend child in turn** (a composite
may have one; use `sub_oracles` children matching the recommend-child test; a single-family
recommend uses `task.oracle` itself as the only lens). A task counts once for each gate even when
several children/categories match.

## Changes to `src/nutrienv/bench/quality_gates.py`

Introduce a helper:

```
def _recommend_lenses(task: Task) -> list[...]:
    """One lens per recommend geometry carrier in task:
    single-family recommend -> [task.oracle]; composite -> each recommend
    child; else [].  Each lens carries (oracle, profile, query-ish) so the
    gates below can judge child-specific windows/allergies."""
```

Lens contents (adjust to what each gate needs):
- oracle: the recommend oracle (task.oracle or the child)
- profile: `child.profile or task.s0.profile` (mirror validator S10-5; a post-update recommend
  child carries its own profile)
- plan_windows: `oracle.plan_windows`
- catalog + query: still from `task.s0` / `task.query` (shared by the episode)

Then rewire the three gates to use lenses instead of the `task.family == "recommend"` filter:

1. `constrained_recommends` — for each lens of each task: keep the same three categories as today
   (unpassable `fitting_plan == None`; leftover/remainder ledger scene; named-dish allergy trap),
   judged with the **lens** oracle/plan_windows/profile; `_query_names_allergen_food` keeps using
   `task` (query + s0.catalog shared). Note: the leftover/remainder category today uses
   `task.s0.ledger`; for a composite lens use the **parent task's** `s0.ledger` OR the child's
   `ledger_tail` (whichever exists) — leftover geometry in composite = parent had food earlier
   that day (log step) + recommend child pins remainder windows.
2. `leftover_recommends` — id of any task whose recommend lens shows leftover/remainder geometry:
   `s0.ledger` non-empty (single-family) OR (composite: parent `s0.ledger` or any child
   `ledger_tail` non-empty) AND that lens's `plan_windows is not None`. Keep persona==leftover
   counting for legacy splits.
3. `recommend_coverage` — the personas/allergies of a carrier's lenses count toward
   persona×allergen coverage. For a composite, use the parent task's persona (episode persona)
   and — for allergens — the union of lens profiles' allergies (post-update child matters here,
   mirroring S10-5).

Do NOT change:
- `evaluate_unfits` (composite evaluate children keep contributing via their own evaluate
  geometry only if the episode is genuinely evaluate-family — evaluate is a *child* of composite;
  ADR 0016 floors sit inside evaluate/recommend; a composite whose child is evaluate should count
  toward the evaluate-unfit floor the same way: add the same lens treatment to `evaluate_unfits`
  for composite children whose child is an evaluate oracle — child has `last_verdict == "reject"`
  and `last_plan == []`). Decide and implement for evaluate too, symmetric.
- `window_leaks` (already widened for composites in post-merge commit 6039070).
- `leftover_floor` / `evaluate_tier_coverage` — leave as they are if they operate on the same
  task sets already covered; check whether `evaluate_tier_coverage` needs the composite evaluate
  child treatment (tiers live on the child oracle? if tiers are task-level only, leave).

## Tests (add to `tests/test_quality_gates.py`)

Mirror the existing patterns; use `compose_oracles` (already imported) with a recommend child
carrying pinned windows:
- `test_composite_recommend_child_counts_toward_constrained_floor`: composite (family log) with a
  recommend child whose `plan_windows` is unpassable (`fitting_plan is None`, e.g. kcal
  (10_000, 10_000)) → id in `constrained_recommends`.
- `test_composite_recommend_child_leftover_counts_toward_leftover_floor`: composite (family log)
  with parent `s0.ledger` non-empty and recommend child with pinned remainder windows
  (`plan_windows is not None`) → id in `leftover_recommends`.
- `test_composite_allergen_child_counts_toward_coverage`: composite whose recommend child profile
  carries an allergen the single-family recommend slice does not → `recommend_coverage` reports no
  missing allergen.
- `test_composite_evaluate_unfit_child_counts_toward_unfit_floor`: composite (family log) whose
  evaluate child has `last_verdict == "reject"` and `last_plan == []` → id in `evaluate_unfits`.
- Keep every existing test green — no weakening.

## Definition of done

1. `tests/test_quality_gates.py` passes (34 existing + new).
2. Full suite `/home/jzq/Projects/nutri-env/.venv/bin/python -m pytest -q` → 0 failed.
3. Commit to main with a "quality-gates: " prefix (this is a main-side change, not a branch).
4. Update `.scratch/exam-generation-pipeline/issues/14-split-agnostic-quality-gates.md`: tick the
   situation-floors checkbox impact note; and append a note to `reports/issue-consistency-audit.md`
   that composite floors are now counted.