# Profile body facts, Mifflin×PAL energy, AMDR/FDA six-nutrient windows

Recommend and Evaluate Pass on whether a meal's six catalog nutrients (`kcal`, `protein_g`, `carb_g`, `fat_g`, `fiber_g`, `sodium_mg`) fall in judged intervals. Those intervals are this person's daily goals, not a universal 2000 kcal label, and leftover is remainder geometry rather than a Family.

**Status**: accepted

Profile stores body facts: `sex`, `age_y`, `height_cm`, `weight_kg`, `activity`. Daily windows are derived in code at realize time and written onto `Profile.windows`. The agent reads the windows; Pass does not grade whether the agent recomputed BMR.

Energy is Mifflin-St Jeor BMR × PAL (kcal/day):

- male: `10·kg + 6.25·cm − 5·age + 5`
- female: `10·kg + 6.25·cm − 5·age − 161`

PAL by `activity`: sedentary 1.2, light 1.375, moderate 1.55, active 1.725, very_active 1.9. Default everyday → light; gym → active; cut → moderate then a table-level kcal/protein shift. Rejected: China EER tables (catalog and `get_dri` are FDA); weight-only Profile (cannot compute energy).

The six keys follow the FDA Daily Value *template* already in `get_dri` (2000 kcal: protein 50 g, carb 275 g, fat 78 g, fiber 28 g, sodium 2300 mg), scaled to this EER except:

- `protein_g` lo = `0.8 × weight_kg` (the IOM/FDA origin of the 50 g DV), not a flat 50 g
- `sodium_mg` hi stays 2300
- gym/cut may raise protein (and cut kcal) after this derivation

**Judged ceilings (2026-09-24, `SCORER_VERSION = s5-target-ceilings`).** The derived hi of
`protein_g`, `carb_g`, `fat_g` and `fiber_g` is a scaled Daily Value -- a reference intake, not a
limit (the DV table in `get_dri` marks only sodium with an `upper_limit`; protein's hi is often
its own 0.8 g/kg floor). A plan is judged against `judged_ceiling`: those four ceilings carry 15%
slack (`TARGET_CEILING_SLACK`); `sodium_mg` hi (a health limit) and `kcal` hi (already given by the
meal-share band) stay exact, as does every floor. Profiles and `plan_windows` publish the unslacked
numbers; the slack is the ruler's, not the task's. Authoring uses the same ceiling
(`bind_evaluate_reasons`, `leftover_bound_labels`), so no newly authored reject names an overage
the Scorer accepts; in the live splits none does. Two archive evaluate items keep a reason the
slack now excuses (`adr20-eval-8212` protein, `adr25-eval-1202` fat, in v2.2-v2.7-gold); both stay
rejects on a surviving `kcal_hi`, and `validate_draft` flags them if re-frozen. On the 2026-09-24 run the 22 failures this removes were all protein-only overages of at
most 15%, against a cap that usually equalled the person's minimum requirement.

**AMDR macro windows (2026-09-28, `SCORER_VERSION = s7-amdr-windows`, split `nutrienv-v1.1`,
prompt `p6-amdr-window-ranges`).** The slack did not settle protein: its derived hi *was* the
0.8 g/kg RDA, a minimum requirement with no UL, so the cap judged a plan for exceeding the
person's minimum (on the 2026-09-27 leaderboard runs the two DeepSeek flash models' deficit was
almost entirely this cap). The macro windows are now the IOM Acceptable Macronutrient
Distribution Ranges on the day's energy (`AMDR_ENERGY_SHARE`, scaled by EER like the DV template
was, so a phase still moves kcal and the muscle protein floor only):

- `protein_g`: [0.8 g/kg (1.6 g/kg muscle), max(35% EER / 4, floor)] -- the RDA floor stays fixed
- `carb_g`: [45%, 65%] EER / 4; `fat_g`: [20%, 35%] EER / 9
- `fiber_g` stays the scaled DV (AMDR has no fiber range); `sodium_mg` stays [0, 2300]

AMDR is a whole-day guideline, so it is applied as daily gram windows through the existing
remainder geometry, never as a per-meal share: on the recorded runs a per-meal share check
failed 51-85% of plans that pass today (a chicken-and-greens dinner is not a bad diet). Only
`fiber_g` keeps the 15% slack; the AMDR ceilings are the edge of a range and are judged exactly.
The windows are now true ranges, so the task contract says what binds a single meal: each
remaining daily max caps it, its only floor is its energy share (v1.x has no last-meal item).
v1.1 re-derives every stored window of v1.0 with `scripts/build_split_v1_1.py`, which first
reproduces each v1.0 pin from the v1.0 windows the file stores. On the recorded trajectories
(rescored, so indicative only: the windows the models saw changed) the ranking gap closes,
v4.1-flash 43 -> 50 and v4-flash 47 -> 53 with the other three within a point.
- unscaled FDA 2000/50 for every person is rejected — it would make weight ornamental and kill gym items

Meal energy share (中国居民膳食指南 2022, as a handbook line and as `plan_windows` arithmetic): breakfast 25–30%, lunch 30–40%, dinner 30–40%. Daily windows are the extra constraint when this is the last meal (or a whole-day plan): `plan_windows = meal-slot ∩ remainder` (ADR 0007). Breakfast/lunch do not take the full-day fiber/protein floor. Log still ignores windows.

`get_dri` remains the static 2000 kcal FDA table plus the person's windows. Formula and PAL live in code, not in the LLM, and not as a leaked Oracle.

`update_profile` that patches body facts (`sex`, `age_y`, `height_cm`, `weight_kg`, `activity`) refreshes `windows` in Env with this same derivation. The agent writes the facts only. A windows-only patch does not re-derive. This is a narrow exception to ADR 0004: unmentioned window keys may change when body facts change; allergies, medications, and the Ledger still stay if unmentioned.
