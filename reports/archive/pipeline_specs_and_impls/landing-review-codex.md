# Landing review — Codex

## Verdict

**Mill A: accept-with-nits.** The single world-first pipeline, code-owned grams/windows/reasons, admission quotas, ordinary Recommend speech, and two-stage review agree with ADR 0017 and the CONTEXT contracts. Do not reopen the settled choices.

Required nits before implementation:

1. **Persist the evaluated meal separately from adopted state.** For unfit Evaluate, `Oracle.last_plan=[]` loses the bound named meal. Add a Bench-side `evaluated_plan` (name negotiable) to the frozen Task/Oracle representation. Validator, reason binding, Stage-A plate review, and query-food entailment must read it; Env must not adopt it or invent a replacement.
2. **Specify six-key `plan_windows`.** ADR 0014 defines a slot share only for kcal and says breakfast/lunch do not inherit full-day protein/fiber floors; “meal-slot ∩ remainder over six keys” does not say what happens for carb/fat/sodium or non-final-meal lower bounds. Freeze one pure rule before minting reasons.
3. **Specify empty intersections and numeric comparison.** `normalize_window` forbids `lo > hi`, yet a slot/remainder intersection can be empty. State whether such drafts are dropped or represented another way, and define rounding/tolerance at exact bounds so bind, validator, and scorer cannot disagree.
4. **Specify old-Profile defaults.** “Everyday light + maintain” supplies only activity and phase, not sex/age/height/weight. Prefer optional legacy body facts that preserve serialized old windows; require complete facts for roster worlds and for re-derivation. Do not silently assign a fictional body to frozen users.

## Env seam decisions (D2–D5)

- **C2 infer-accept: keep.** A non-empty legacy `submit_plan {items}` should set `last_verdict="accept"`; this preserves Recommend and frozen fit-Evaluate actions. New Evaluate instructions/gold should emit explicit `accept`, but end-state scoring cannot require explicit syntax without adding trajectory provenance. Do not claim that omission fails new Evaluate-fit under this design.
- **C2 reject+items: require `items=[]`.** Rejecting while supplying a plan is contradictory. Treat it as an Illegal Action after full validation and leave the world unchanged; silently discarding items masks agent errors.
- **C2.4: confirm Env does not check reasons against food, allergies, or windows.** Env checks only envelope shape, exact closed tokens, normalization, and accept/reject state invariants. Bench computes and compares semantic reasons at Hand-in. This preserves ADR 0003/0004: Env neither evaluates nor recommends.
- **C5: stacked Profile PR first.** Body facts/window derivation are independently useful, block roster generation, and should live behind one pure derivation interface reused by realize and dispatch. Landing them first reduces the verdict PR's compatibility surface and makes six-key `plan_windows` testable against stable daily windows.

Reason tokens should use an exact enum normalizer (sorted, unique), not `normalize_tags`: case-folding `KCAL_HI` into a valid token would weaken the closed interface. `reject` may carry an empty reason list as legal physics; a new unfit Oracle will fail it semantically because its exact reason set is non-empty.

## C7 order

Reorder:

1. Profile body facts + phase; pure Mifflin/PAL/FDA derivation; patch/re-derive and legacy-load compatibility.
2. `WorldState` verdict fields; submit schema/dispatch; reset/get_profile observations; action atomicity.
3. Bench representation and persistence: `evaluated_plan`, Oracle verdict/reasons, split loader, freezer, scorer, validator, and Composite classification. Prove all frozen fit-only Evaluate gold still Passes via verdict-less actions.
4. Realize/bind fit and unfit Evaluate using the frozen six-key window rule and exact reason computation; wire review/gates.
5. Update `react.py`, then allow mill unfit candidates.

## File-level change list

- `src/nutrienv/world/types.py`: Profile fields/default compatibility; World verdict/reasons; observation helpers/normalizers.
- `src/nutrienv/world/dri.py` or a new focused world module: one pure daily-window derivation interface; no duplicate formula in Bench.
- `src/nutrienv/actions/schemas.py`, `actions/dispatch.py`: optional verdict/reasons, Profile patch keys and validation, atomic transitions/re-derive.
- `src/nutrienv/env/nutri_env.py`: expose verdict/reasons on reset; `get_profile` path must match.
- `src/nutrienv/bench/realize.py`, `scorer.py`, `split.py`, `validator.py`: new fields/defaults, exact verdict branches, evaluated-meal binding, six-key validation.
- `src/nutrienv/bench/pipeline/freezer.py`, `run_batch.py`, review/gate helpers: serialize the evaluated meal/verdict/reasons and classify empty reject separately from empty Recommend.
- `src/nutrienv/harness/react.py`: action shape and the short Evaluate/Recommend/meal-share guidance.
- Frozen split JSON: **no rewrite required**; loaders default omitted verdict/reasons/body facts compatibly. New split rows serialize all new gold fields.

## Tests required for “done”

- Transition matrix: initial silence; omitted non-empty → inferred accept; explicit accept; explicit reject; repeated submissions. Assert plan/verdict/reasons together and both reset/get_profile observations.
- Illegal-action atomicity: accept+empty, reject+non-empty, bad verdict, unknown/ill-typed reason, bad item, and excessive grams leave the entire world byte-identical.
- Reason normalization: exact tokens only, sorted unique output; all 12 nutrient hi/lo codes plus allergy; equality at each bound emits no code; multi-reason exact set.
- Scorer cross-product: legacy Oracle `None`; new accept exact vs substitute/silence/reject; new reject exact vs silence/substitute/wrong or missing reasons. Prove `allow_empty_plan` cannot bypass a verdict Oracle.
- Frozen compatibility: load and replay every existing fit-only Evaluate using old `{items}` and assert Pass; also run existing Recommend/conflict gold to catch the omitted-empty transition.
- Serialization round-trip: old omitted fields retain defaults; new S0/Oracle/evaluated meal survive freeze/load exactly; no mutable-default aliasing.
- Composite regression: empty reject is never inferred/serialized/validated as Recommend; reject+Recommend in one episode remains disallowed by the documented one-`last_plan` constraint.
- Profile table tests: both sexes, PAL values, phase shifts, six keys, sodium cap, windows-only patch no re-derive, body/phase patch re-derives, partial invalid patch is atomic, legacy Profile preserves old windows.
- Plan-window/binder tests: empty and leftover ledgers, breakfast/lunch/dinner, last-meal floors, slot-vs-remainder provenance, empty intersection policy, allergy plus nutrient collision, and swap yielding fat/fiber without kcal.
- Validator/review tests: unfit `evaluated_plan` is portion-traceable and named in speech; fit with leftover remains accepted; substitute plan cannot Pass Evaluate-unfit.
