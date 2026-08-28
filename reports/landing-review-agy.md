# AGY Scout Review: Mill Landing & Env Seam (ADR 0017 / docs/mill-landing.md)

**Role**: AGY Scout | **Focus**: Speech & Product-UI Mapping, Seam Coherence, Zero-Drift Freeze

---

### 1. Mill Section A: Accept with Nits

**Verdict**: `accept-with-nits`

- **Nit 1 (Product UI / Speech Semantic Mapping)**: In product UI, an Evaluate response maps to a binary verdict card: **建议** (`accept` + exact meal plan displayed) vs **不建议** (`reject` + empty plan + structured reason tags). Spoken queries must remain natural requests ("帮我看下这顿能不能吃" / "Is this burger fine for dinner?").
- **Nit 2 (Leftover Speech Discipline)**: In Recommend/Evaluate, queries must strictly remain occasion requests ("What's for dinner?"). Spoken text must **never** recite previous meals or leftover budgets (e.g. "I already ate 500 kcal"). Remainder lives in S0. Code leak scanner in Review Stage B must explicitly flag any leftover/macro leak in the query.
- **Nit 3 (Swap Knife Allergen Hygiene)**: For iso-caloric `swap` knives (e.g. replacing a side to trigger `fat_g_hi` / `fiber_g_lo`), the generator must ensure the swapped food does not accidentally introduce an allergen tag unless intended as an `allergy` knife.

---

### 2. Env Seam C Design Decisions

- **C2 (Rule 1: Infer `accept` vs explicit verdict)**: **Keep infer-accept in Env physics, but require explicit `oracle.last_verdict="accept"` on new Evaluate-fit tasks.**
  - *Why*: `submit_plan {"items": [...]}` without verdict must continue to work for Recommend and legacy frozen evaluate fixtures (`oracle.last_verdict is None`). For new Evaluate-fit items, `oracle.last_verdict == "accept"` ensures agents explicitly commit to an acceptance verdict (inferred or explicit), preserving 100% backward compatibility while scoring strict evaluate tasks.
- **C2 (Rule 3: Reject + Items)**: **Require `items=[]` (raise `ActionError("bad_schema")` if `items` is non-empty with `verdict="reject"`).**
  - *Why*: Fail-fast envelope physics. A reject verdict represents refusal/unfit. Submitting non-empty items under `reject` is ambiguous and risks masking substitute proposals (which ADR 0016 strictly forbids for Evaluate).
- **C2.4 (Env reason verification)**: **Confirm: Env does NOT validate reason codes against the meal at step time.**
  - *Why*: Env is physics, not policy. Env only checks schema/closed-set vocabulary (`ActionError` on unknown tokens). Evaluating whether reasons match the meal/windows is the responsibility of Bench Scorer at Hand-in. Env must not invent evaluation (ADR 0003/0004).
- **C5 (Profile PR Strategy)**: **Stacked PRs (PR 1: WorldState/submit_plan verdict + Scorer; PR 2: Profile body facts + window rederivation).**
  - *Why*: Keeps PR 1 focused on unblocking the Evaluate-unfit contract, action schema, and zero-drift verification of existing fixtures. PR 2 adds body anthropometry & Mifflin/PAL recalculation cleanly without coupling risks.

---

### 3. Implementation Order C7: Agree (with Minor Refinement)

1. **Step 1**: `WorldState` (`last_verdict`, `last_reasons`), `schemas.py`, `dispatch.py` (`submit_plan` envelope & validation), observation views (`get_profile`, `reset`), and unit tests.
2. **Step 2**: `Oracle` + `scorer.py` (`last_verdict`, `last_reasons`, reason set equality) + `validator.py`; verify frozen v0.x evaluate fixtures 100% Pass without verdict.
3. **Step 3 (PR 2)**: Profile anthropometry fields (`sex`, `age_y`, `height_cm`, `weight_kg`, `activity`, `phase`), automatic window rederivation on body patch, and `_evaluate_from_row` unfit realize path (six-key `plan_windows`).
4. **Step 4**: Update `react.py` handbook with symmetric 2-line instructions (staying ≤ 575 tokens).
5. **Step 5**: Enable mill candidate generation, committee review (Stage A numbers + Stage B speech), and admission.

---

### 4. Required Pre-Landing Tests (Must Pass Before Seam Done)

1. `test_frozen_v0_evaluate_passes_without_verdict`: Asserts existing frozen evaluate gold (`submit_plan` with items only, no verdict) achieves `pass` on legacy oracles.
2. `test_submit_plan_silence_vs_reject`: Asserts `submit_plan(items=[])` leaves `last_verdict=None` (silence), which fails an unfit Oracle (`oracle.last_verdict="reject"`).
3. `test_submit_plan_reject_requires_empty_items`: Asserts `submit_plan(items=[...], verdict="reject")` raises `ActionError("bad_schema")`.
4. `test_submit_plan_reject_invalid_reason_token`: Asserts unknown tokens (e.g. `"sugar_hi"`) raise `ActionError("bad_schema")`.
5. `test_scorer_evaluate_unfit_exact_reason_set`: Asserts subset or superset reasons (e.g. omitting `sodium_mg_hi`) fail the scorer with `wrong_goal` / `reason_miss`.
6. `test_scorer_evaluate_unfit_substitute_plan_fails`: Asserts submitting an alternative safe meal when the named meal is unfit fails.
7. `test_profile_body_facts_window_rederivation`: Asserts patching `weight_kg` or `phase` recomputes daily windows, while directly patching `windows` retains custom targets without overwrite.

---

### 5. ReAct Handbook (`react.py`) Two-Line Addition Check

```text
- Evaluate: submit_plan with verdict="accept" and the exact named meal if safe; or verdict="reject", items=[], and all applicable reason codes (allergy, or {kcal,protein_g,carb_g,fat_g,fiber_g,sodium_mg}_{hi|lo}).
- Recommend: submit_plan a safe meal for the meal budget; omit verdict.
```
*Token impact*: ~45 tokens, keeping total handbook well within the ~575 token budget.
