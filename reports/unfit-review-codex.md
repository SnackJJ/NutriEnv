# Codex review: Evaluate-unfit taxonomy

## Verdict

**Accept-with-nits**, for the taxonomy only. It covers the complete v1 failure space:
a named meal is unfit iff it has an allergen intersection or a judged nutrient is
outside `plan_windows`. Do not admit unfit rows until the current state/action/oracle/
scorer/validator seam implements ADR 0017; today they are unrepresentable or mis-scored.

## Taxonomy

No semantic failure type is missing. The closed reason set remains authoritative after bind.

Two entries are redundant **as peer types**:

- `sodium_hi` is `over_slot` with a sodium coverage target. Keep it as an
  authoring/quota tag because salty-food coverage is useful, but define it as a
  specialization, not a mutually exclusive family.
- `multi` is not a knife or cause; it is the post-bind result of any knife firing
  multiple codes. Make `multi=true` an outcome/modifier and retain the actual
  knife (`over_slot`, `allergy`, etc.). Never force extra violations merely to
  obtain this label.

Cleaner interface: primary knife = `allergy | over_slot | under_slot`; scene =
`empty_ledger | leftover`; modifiers = `sodium_hi`, `multi`. `leftover_over` may
remain an admission bucket to guarantee remainder-reasoning coverage.

## `leftover_under`

**Cut it as a required v1 type/quota; permit it as an optional leftover-scene
`under_slot`.** Consumption makes remainder lo `max(0, lo - used)`, so the ledger
relaxes rather than tightens a lower bound.
A sparse dinner below the remaining floor is ordinary `under_slot`; the leftover
scene did not create it. A dedicated knife risks artificial examples. If kept,
require a real earlier Log timeline and no special quota.

## Energy overflow preference

**Prefer `leftover_over` when the roster timeline already contains eligible
earlier Logs and the ordinary plate crosses remainder-hi but not meal-slot-hi.**
That isolates the capability and preserves plate plausibility. Use an `over_slot`
bump when no real ledger exists, the plate already violates slot-hi, or direct
portion reasoning is the target. Record which bound fired to prove remainder causality.

## Current code contradictions (rollout blockers)

1. `WorldState` has only `last_plan`; it has no `last_verdict` or
   `last_reasons`. `Oracle` likewise cannot express either gold field.
2. `submit_plan` strictly accepts only `items`; `verdict`/`reasons` are rejected
   as unknown keys. Although `items: []` mutates successfully, it cannot record
   reject versus silence.
3. `_score_plan` rejects an empty plan as `wrong_goal` unless
   `allow_empty_plan=True`. Setting that flag is not a workaround: initial
   `last_plan=[]` would let silence pass, and no exact reason-set comparison is
   possible. Its `allergy`/`window` outputs are scorer failure tags, not the
   agent-authored closed reasons.
4. `_validate_evaluate` explicitly emits `evaluate last_plan is empty`, then
   requires the candidate to be within `s0.profile.windows` and allergen-safe.
   It therefore rejects every intended unfit oracle and does not validate
   Evaluate against `oracle.plan_windows`.
5. `_evaluate_from_row` only realizes fit exact-plan oracles and derives local
   kcal/protein margins around that plan. It does not construct reject oracles,
   all-six-nutrient meal-slot/remainder windows, verdicts, or reason sets.
6. Split parsing/freezing serializes none of the new verdict fields, and
   `_sub_family` infers any empty-plan sub-oracle as Recommend. Thus an unfit
   Evaluate inside Composite collides with the existing empty-list sentinel.
7. The React manual says to submit `items: []` for a violating `last_plan`, but
   neither teaches verdict/reasons nor can Env accept them. Update it with the seam.

## Concrete nits before acceptance into the mill

- Specify authoring labels as non-exclusive dimensions (knife, scene, outcome)
  and require gold reasons to be recomputed after final bind/rewrite validation.
- Drop mandatory `leftover_under`; reserve minimum counts for genuine
  remainder-induced `leftover_over` instead.
- Make reject distinguishable from untouched S0, and compare verdict plus the
  exact normalized reason set in the scorer; do not overload Recommend's empty
  `last_plan` sentinel.
- Update validator, realization, split/freezer, Composite family metadata,
  action schema/state, and `react.py` atomically before generating unfit rows.
