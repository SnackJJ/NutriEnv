# Profile body facts, Mifflin×PAL energy, FDA six-nutrient windows

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
- unscaled FDA 2000/50 for every person is rejected — it would make weight ornamental and kill gym items

Meal energy share (中国居民膳食指南 2022, as a handbook line and as `plan_windows` arithmetic): breakfast 25–30%, lunch 30–40%, dinner 30–40%. Daily windows are the extra constraint when this is the last meal (or a whole-day plan): `plan_windows = meal-slot ∩ remainder` (ADR 0007). Breakfast/lunch do not take the full-day fiber/protein floor. Log still ignores windows.

`get_dri` remains the static 2000 kcal FDA table plus the person's windows. Formula and PAL live in code, not in the LLM, and not as a leaked Oracle.

`update_profile` that patches body facts (`sex`, `age_y`, `height_cm`, `weight_kg`, `activity`) refreshes `windows` in Env with this same derivation. The agent writes the facts only. A windows-only patch does not re-derive. This is a narrow exception to ADR 0004: unmentioned window keys may change when body facts change; allergies, medications, and the Ledger still stay if unmentioned.
