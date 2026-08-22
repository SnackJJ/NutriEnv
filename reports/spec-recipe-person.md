# Spec: recipe person knob — resolver uses a chosen roster person, not fixed ROSTER[0]

**Status:** decided by coordinator (base for the 14-assertion persona×allergen coverage: the
synthetic preview showed everyday-only + 1 allergen because the resolve path hard-codes
`ROSTER[0]` = roster-ada (peanut) at four sites; generate_one already samples 20 roster people).

## Problem

`src/nutrienv/bench/pipeline/resolver.py` uses `profile_for(ROSTER[0])` at 4 sites
(`_composite_windows` :334, recommend :397, update :438, knife :508). ROSTER[0] is roster-ada
(persona everyday, allergy peanut). So every batch item — composite/recommend/update/knife — is
profiled as ada: windows derived from her body facts, allergies {peanut} only. The 14-assertion
`recommend_coverage` (persona × allergen tags) can never pass: cut/gym personas and the other 6
catalog allergens (egg/milk/shellfish/soy/tree_nut/…) are unreachable through the batch path.
`generate_one` instead does `sample_roster_person(seed)` (roster.py:198) so the mill covers the
diversity; only the batch path is pinned to one person.

## Change

1. `types.Candidate` gains `person: str | None = None` (a roster user_id or index, default None).
2. `run_batch._RECIPE_KEYS`: add `person` to every family set ({"knife","tier","items",
   "amount_path","person"} evaluate; {"occasion","person"} recommend; {"person"} update,
   composite). Parse: accept `person=roster-ada` or `person=1` (index) — validate it resolves to a
   RosterPerson (reuse roster lookup; fail-closed on bad id).
3. `resolver`: thread `candidate.person` (via a small `_person_profile(candidate)` helper that
   falls back to `ROSTER[0]` when person is None — defaults byte-identical) into
   `_composite_windows`, `_realize_recommend`, `_realize_update`, `_realize_evaluate_knife`
   (their `profile_for(ROSTER[0])` calls become `profile_for(chosen)`).
4. `generate_batch.py --recipe evaluate:person=roster-cam` passes through (generic parsing).
5. Tests: `evaluate:knife=allergy + person=roster-cam` → task profile is cam's (cut persona, egg
   allergy — verify profile.allergies contains egg and windows match cam's); recommend person →
   recommend coverage now shows cam's allergen; a batch with personas over multiple roster people
   covers cut + egg + milk etc. (the 14-assertion need); `person=bogus` rejected at parse.

## Definition of done

1. Tests pass; full suite 0 failed (expect 1321+).
2. Demo: a synthetic batch mixing `evaluate:person=roster-cam` (egg), `recommend:person=roster-fay`
   (milk) covers those allergens/personas in `recommend_coverage` — the persona×allergen channel
   works.
3. Commit "pipeline: " prefix. Append evidence to reports/spec-recipe-items.md (or a new
   reports/impl-recipe-person.md).
4. Do NOT touch: docs/adr/*, data/splits/*, *.sqlite, scorer.py, validator.py, review_harness.py,
   quality_gates.py, generate_one.py.

Work autonomously. If blocked, stop and report.
## Implementation notes & demo

- `Candidate.person` (roster user_id or index); `_RECIPE_KEYS` carries
  `person` on every family; parse resolves it via
  `resolver._resolve_roster_person` (fail-closed on unknown id / bad index).
  Resolver sites now derive profiles via `_person_profile(candidate)`
  (`_realize_recommend` / `_realize_update` / `_realize_evaluate_knife` /
  composite windows), falling back to ROSTER[0] when unset (defaults
  byte-identical). When a person IS chosen, the Task persona becomes that
  roster person's persona (so `recommend_coverage` sees cut/gym personas).
- Tests: knife+person=roster-cam (cut profile, egg allergy, allergy reason,
  draft clean); recommend+roster-fay covers milk; mixed cam/fay covers
  cut/everyday + egg/milk in `recommend_coverage`; person=bogus/999 refused
  at parse; person=2 (index) resolves to roster-cam.
- Demo (catalog-v2, synthetic): `recommend:person=roster-fay` items reload
  with allergies ('milk',) and close the milk allergen + everyday persona in
  `recommend_coverage`. The `evaluate:knife=allergy + person=roster-cam`
  accept path is pinned by the deterministic fixture test
  (`test_person_recipe_uses_the_chosen_roster_profile`); on random catalog-v1
  pools it rejects cleanly (`unresolvable`) because a random plate rarely
  fits cam's tighter cut-phase dinner slot AND the pool lacks an egg carrier
  — fail-closed, documented.
```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1326 passed in 50.35s        # 0 failed (was 1321; +5 tests)
```
