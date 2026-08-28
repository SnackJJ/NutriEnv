# Mill landing + Env implementation sketch (for review)

Status: mill contract frozen in ADR 0017 / CONTEXT. This note is the handoff: what not to reopen, and a proposed Env seam so Evaluate-unfit is scoreable. Not code yet.

Pointers: `docs/adr/0017-exam-generation-pipeline.md`, `docs/mill-query-templates.md`, `CONTEXT.md`.

---

## A. Mill — settled

One pipeline. Code samples a roster person + day-shape + scene first. LLM only writes spoken meals for Log / Evaluate / Composite-log as `{query, foods: [food_id, …]}`. Grams, windows, Mifflin, remainder, fit/unfit, reason codes: code. Recommend / Update queries are templates (`docs/mill-query-templates.md`).

Roster: ~20 adults (19–75) × ~12 tasks; Composite uses the same people. Mill **over-produces** drafts. Published 240 (48/72/48/36 + 36 composite, ADR 0016) is an **admission** target, not a generate-time kill switch. Sample day shapes; do not implement “every person: breakfast Log → lunch Log → dinner Rec”. Clock order only: leftover Rec/Eval copies earlier **Log** items from that day. Breakfast Rec with empty ledger is first-class.

Query speech: Recommend is an occasion request (“What's for dinner?”). Leftover, known allergies, tight remainder live in S0. Announcing a new allergy is Update (or Composite if they also ask what to eat). Named dish without stating allergy is allowed.

Evaluate-unfit authoring: knife × scene × outcome. Knives: allergy, over_slot, under_slot, **swap** (iso-caloric so gold can be `{fat_g_hi}` or `{fiber_g_lo}` with no kcal code). leftover_over / leftover_under **derived** after bind. leftover_under stays in draft (last meal, small floor); drop at freeze if it does not discriminate. Also mint **fit** items with leftover ledgers. Prefer leftover_over over cartoon bumps.

Review harness: two-stage committee after bind, not Pass. Stage A: **code hard gate** (table grams, windows, reasons) then 3 LLMs vote “eatable plate?” on food+grams only. Stage B: 3 LLMs vote speech (query + food names). k=3, majority. Different model families. Code fail drops; LLM fail starts as alarm.

Do not reopen: Constrain as a family; shrinking 48/72/48/36; LLM grams; merging the two review stages into one model; leftover/allergy as Recommend wording; four `generate_one` scripts.

---

## B. Env — what is blocked today

Codex/Claude already listed these. Unfit rows must not be generated until this seam lands.

| Gap | Today |
|---|---|
| World | `WorldState` has only `last_plan` (default `[]`). Silence and explicit reject are identical. |
| Action | `submit_plan` requires `items` only; extra keys are schema errors. |
| Scorer | Empty plan → `wrong_goal` unless `allow_empty_plan`. That flag also lets a *different fitting meal* pass (Recommend-substitute), which ADR 0016 forbids for Evaluate-unfit. |
| Realize | `_evaluate_from_row` builds **fit** oracles and derives windows from the meal (`evaluate_windows`, kcal+protein only). |
| Validator | `_validate_evaluate` rejects empty `last_plan` and requires the meal inside S0 windows. |
| Profile | ADR 0014 body facts (`sex`, `age_y`, `height_cm`, `weight_kg`, `activity`) and ADR 0015 `phase` are **not** on `Profile`. Windows are not Env-rederived on weight/phase patch. |
| Handbook | `react.py` says empty `items` for a violating last_plan; no verdict/reasons. |

Existing frozen evaluate items are fit-only (`submit_plan` exact items, no verdict). **v0.x must keep passing.**

---

## C. Proposed Env seam (to debate)

### C1. World fields

Add to `WorldState` (and `reset` / `get_profile` observation):

- `last_verdict: None | "accept" | "reject"` — S0 is `None`
- `last_reasons: tuple[str, ...]` — S0 is `()`

Keep `last_plan` as the adopted plan. Reject does **not** adopt: `last_plan=[]`.

Closed reason tokens: `allergy`, and `{kcal,protein_g,carb_g,fat_g,fiber_g,sodium_mg}_{hi|lo}`. Store sorted unique tuple (same idea as `normalize_tags`).

### C2. `submit_plan` envelope

```
submit_plan { items, verdict?, reasons? }
```

`items` remains required. `verdict` / `reasons` optional (backward compatible).

Proposed physics (Illegal Action if broken; world unchanged):

1. `verdict` omitted:
   - non-empty `items` → write `last_plan`, set `last_verdict=accept`, `last_reasons=()`
   - empty `items` → write `last_plan=[]`, **leave** `last_verdict` as it was (`None` if never submitted) = silence
2. `verdict=accept` → `items` must be non-empty; write plan; `last_reasons=()`
3. `verdict=reject` → force `last_plan=[]` (ignore or require empty `items` — **reviewers pick**); set `last_reasons` from `reasons` (must be subset of the closed token set; unknown token → schema error)
4. Env does **not** check whether reject reasons match the meal. That is Bench at hand-in (Env does not invent evaluation).

Recommend agents keep today’s `submit_plan {items:[...]}` with no verdict. Oracle.`last_verdict` is `None` → scorer skips verdict.

### C3. Scorer

- If `oracle.last_verdict is None`: today’s plan scoring (Recommend / old evaluate).
- If `oracle.last_verdict == "accept"`: `state.last_verdict == "accept"` and `state.last_plan == oracle.last_plan` (exact). Reasons empty.
- If `oracle.last_verdict == "reject"`: `state.last_verdict == "reject"` and `state.last_plan == []` and `set(state.last_reasons) == set(oracle.last_reasons)`. **Do not** use `allow_empty_plan`. A substitute non-empty plan fails even if it fits windows.
- Silence (`last_verdict is None`) fails both new Evaluate oracles.

Failure tags: keep `wrong_goal` for verdict/plan mismatch; optional `reason_miss` if we want it distinct.

### C4. Oracle / realize / validator / split

- `Oracle` gains `last_verdict` and `last_reasons` (default `None` / empty so old JSON loads).
- New evaluate realize: `plan_windows` = meal-slot ∩ remainder over **six** keys (ADR 0014), not `evaluate_windows` from the meal. Fit: exact plan + accept. Unfit: empty plan + reject + bind-computed codes.
- Validator: empty last_plan legal iff reject; reasons must equal bind of the named meal vs `plan_windows` + allergies; query must still name the foods.
- Composite: empty-plan child is **not** inferred as Recommend if that child has `last_verdict=reject`.

### C5. Profile anthropometry (roster mill depends on this)

Add Profile fields: `sex`, `age_y`, `height_cm`, `weight_kg`, `activity`, `phase` (`maintain` default). Patch via `update_profile`. Body facts or `phase` refresh `windows` in Env (ADR 0014/0015). A windows-only patch does not re-derive. Observation via `profile_view`. Old splits without these keys: defaults (everyday light + maintain) so v0.x still loads.

### C6. Handbook (`react.py`) — two lines, not a treatise

- Evaluate: you must `submit_plan` with `verdict=accept` and the exact named meal, or `verdict=reject`, empty items, and the closed reason codes that actually apply. Doing nothing fails.
- Recommend: `submit_plan` a safe meal; omit `verdict`.
- Keep leftover subtract + portion table; add one line meal share 25–30 / 30–40 / 30–40 (survey: stay ~575 tokens).

### C7. Implementation order (do not mill-unfit before 1–4)

1. WorldState + schema + dispatch + observations + tests (silence vs reject vs accept).
2. Oracle + scorer + validator; old evaluate fixtures still Pass.
3. Realize evaluate unfit + six-key plan_windows; Profile body facts + window rederive.
4. `react.py` two lines.
5. Then mill can emit unfit candidates.

---

## E. Review consensus (Claude / Codex / AGY, 2026-08-20)

All three: mill **accept-with-nits**; Env infer-accept **keep**; reject **requires `items=[]`**; Env **does not** check reasons vs the meal.

| Topic | Decision |
|---|---|
| Non-empty `submit_plan` without `verdict` | Infer `accept` (legacy evaluate + Recommend). `submit_plan` is total on the triple: non-empty+omit → `(accept, items, ())`; empty+omit → `(None, [], ())` so accept-then-empty-items is **silence**, not stale accept. |
| `verdict=reject` + non-empty items | Illegal Action, world unchanged |
| `accept` + non-empty reasons; `reasons` without `verdict` | Illegal |
| `reject` + empty reasons | Legal physics; Bench fails a new unfit Oracle (gold set non-empty) |
| Reason tokens | Frozen constant in `world/types.py`; Env checks vocabulary only |
| Named meal on unfit | Bench `evaluated_plan` on Oracle/Task (Env does not adopt it) |
| Profile | Stacked: (a) fields+defaults, (b) Mifflin in `world/` + re-derive + ADR 0015 bands. Not bundled with the verdict PR. |
| Scorer | Branch on `last_verdict` **before** empty-`last_plan` Recommend sentinel. Reject oracles: `plan_must_fit_windows=False`, `allow_empty_plan=False`. |
| Stage A prompt | “Could one person eat this at one meal?” Large plates allowed; not judging wisdom. |

Must-have tests: silence ≠ reject; reject vs fitting substitute fails; Env accepts a legal-but-wrong reason (scorer fails); Illegal leaves world byte-identical; all **240** still Pass including evaluate without verdict; freezer `_sub_family` is verdict-aware.

## D. Questions for reviewers

1. Mill landing (section A): anything still underspecified or contradictory?
2. C2 rule 1: infer `accept` from non-empty items when `verdict` omitted — keep for Recommend/old gold, or require explicit verdict on all new Evaluate-fit?
3. C2 reject: require `items=[]`, or ignore items and always clear `last_plan`?
4. Env vs Bench: confirm Env does not validate reason codes against the meal (C2.4).
5. C5 Profile fields in the same PR as verdict, or a stacked PR first (roster mill is blocked on windows-from-body)?
6. File-level change list and tests you would require before calling the seam done.
