# Phase on Profile; implicit Update Passes in a band

Everyone has a `phase` of `maintain` (default), `cut`, or `muscle`. It is a Profile fact, not a gym-only flag and not a Persona name. Changing phase is the same class of write as changing weight: the agent patches `phase`, Env re-derives daily windows (Mifflin×PAL + FDA six keys, then the phase shift). `plan_preset.goal` was a flavor dict that did not move windows; do not keep it as the ruler.

**Status**: accepted

Explicit Update stays exact (`end_state.profile == oracle.profile`): named calorie deltas, allergy add/remove. Implicit spoken intent does not. The handbook only states direction (deficit is tiring → raise energy toward maintain; asking to cut → energy below maintain; asking to build → protein above 0.8 g/kg). It does not publish step sizes. Pass is whether the resulting windows fall in a code-side band, same idea as Recommend’s any-fitting-plan sentinel.

Working bands (realize, not the prompt):

- maintain → cut: daily kcal hi in `[EER−500, EER−100]`
- cut + fatigue: daily kcal higher than S0 and ≤ maintain EER
- → muscle: protein lo `> 0.8 g/kg`, kcal lo ≥ maintain EER

Allergy tags and unmentioned fields stay exact. This is a narrow scorer exception to ADR 0004’s full Profile equality, only for implicit window intent.
