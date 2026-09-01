# NutriEnv Evaluate-Unfit Taxonomy Design Review

- **Target**: ADR 0017 Evaluate-unfit types & mill authoring pipeline
- **Reviewer**: AGY Scout
- **Verdict**: **accept-with-nits**

---

### 1. Completeness & Diet-App Failure Alignment

The proposed taxonomy (`allergy`, `over_slot`, `under_slot`, `leftover_over`, `leftover_under`, `sodium_hi`, `multi`) accurately reflects real-world diet app failure modes (MyFitnessPal, LoseIt, Cronometer):
- **Over budget**: Single heavy meal (`over_slot`) vs. cumulative day overflow (`leftover_over`).
- **Under target**: Skipping macros / snack-as-meal (`under_slot` with `protein_g_lo`, `kcal_lo`).
- **Condition / clinical spikes**: High sodium meals (`sodium_hi` with `sodium_mg_hi`).
- **Medical / safety**: Prohibited allergens (`allergy`).
- **Compound violations**: Multi-nutrient failures (`multi`).

The set is complete for v1 because it spans all closed code predicates (`allergy` + `{nutrient}_{hi/lo}`) across isolated meal-slot and timeline-remainder contexts. No extra families or out-of-scope medical/taste categories are needed.

---

### 2. `leftover_under`: Cut from v1

**Recommendation: Cut.**
- **Reasoning**: `plan_windows` is `meal_slot_share ∩ remainder`. A meal failing a lower bound (`_lo`) is almost exclusively caused by a sparse plate (e.g. eating an apple for dinner), which is already cleanly modeled by `under_slot`.
- In real diet tracking, users do not experience "I starved all morning, therefore this standard dinner is invalid because it's too small." A leftover scene forcing an artificial deficit lower bound is unnatural and redundant with `under_slot`.

---

### 3. Energy Overflow: Prefer `leftover_over` over `over_slot` Bumps

**Recommendation: Strongly prefer `leftover_over`.**
- **Eatable plates (ADR 0010)**: Bumping single-meal quantities to force an overflow in an empty ledger frequently creates cartoonish meals (e.g. 800g steak or 4 bowls of rice).
- **Realistic user behavior**: Most real-world calorie rejections happen on completely normal meals (e.g. standard pasta or burger) because earlier meals/snacks consumed the daily budget.
- `leftover_over` exercises the agent's ability to read S0 (`Profile + Ledger Remainder`) while keeping query plates realistic and eatable. Reserve `over_slot` for inherently calorie-dense or macro-skewed plates.

---

### 4. Collision with Current Scorer / Validator

**Identified Scorer Lag** (`src/nutrienv/bench/scorer.py`):
1. **Empty `last_plan` handling**: In `scorer.py::_score_plan`, `items == []` returns `"wrong_goal"` unless `oracle.allow_empty_plan` is true (currently intended as Recommend's sentinel). Evaluate-unfit requires `last_plan = []` on `reject`.
2. **Missing Verdict & Reason Check**: Current `Scorer` does not check `end_state.last_verdict` (`accept` vs `reject`) or `end_state.last_reasons` against ground truth closed codes.
3. **Collision Resolution**: Scorer must be updated to grade `expected_verdict` and `expected_reasons` (exact set match), and allow `last_plan == []` when `expected_verdict == "reject"`.

---

### 5. Concrete Nits

1. **Cut `leftover_under`**: Remove `leftover_under` from the v1 authoring pool to eliminate redundant and artificial day-shape tasks.
2. **Clarify `sodium_hi` taxonomy role**: `sodium_hi` is an authoring knife specializing `over_slot` for micronutrient/condiment additions, but resolves to closed code `sodium_mg_hi`. Keep it in authoring guidelines as a knife pattern, but clarify that evaluation treats it under standard nutrient bound checks.
3. **Scorer contract update**: Add explicit `expected_verdict: str` and `expected_reasons: set[str]` to `Oracle`, updating `_score_plan` so `reject + [] + reasons` passes binary scoring.
4. **Preserve speech naturalness in `leftover_over`**: Ensure the expander prompt keeps `leftover_over` queries pure ("Is this lasagna okay for dinner?"), preventing query leakage of earlier ledger events.
