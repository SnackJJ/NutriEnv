# One exam-generation pipeline: roster worlds, natural queries, LLM only for spoken meals

The mill is a single pipeline that samples a world first, then either expands a spoken meal or fills a query template. It is not four `generate_one` scripts. Pass is still end state == Oracle (ADR 0004). LLM output is always a candidate, never a gram fact (ADR 0011 still holds for Log/Evaluate).

**Status**: accepted

## Roster and scene

Twenty adult roster people (ages 19–75; sex, height, weight, activity, phase, allergies) × about twelve tasks = 240. Composite uses the same people, not extra strangers. Children, pregnancy, and 80+ are out: energy is Mifflin×PAL (ADR 0014). Medical personas stay thin. Leftover is a scene (ledger geometry), not a persona name.

Each item is a person plus a scene (occasion and ledger). Mill **samples day shapes** and over-produces drafts; it does not stop when a family hits 48 or 72. Clock order only constrains leftover: a leftover Recommend may run only after earlier **Log** items that day, so the ledger is real. Breakfast may be Recommend, Evaluate, Log, or skipped. Empty-ledger Recommend at breakfast is first-class. Those freeze as independent episodes, not one saga, unless the item is one of the 36 Composite tasks. Do not invent an unpublished leftover meal just to fill S0. Do not implement “every person: breakfast Log → lunch Log → dinner Rec”.

The published 240 recipe (48/72/48/36 + 36 composite, ADR 0016) is an **admission target**, not a generate-time kill switch. Extra drafts stay in the pool (ADR 0009’s draft-to-exam ratio). If a family is short after selection, mill goes back and samples those day shapes — it does not pad with paraphrases. Do not shrink the four published family slices just because logs fell out of the timeline more easily.

## What the query may say

A real user does not announce remaining budget, recap that they already ate, or dictate allergy history to a nutrition assistant. Recommend speech is an occasion request (“What's for dinner?”). Tight remainder, leftover, and known allergies sit in S0; the agent reads Profile and Ledger. Saying “eggs are off the table, add that” is Update, or Composite if they also ask what to eat. Naming a dish (“shrimp tonight?”) without stating an allergy is still allowed: the trap is in the profile.

## Family contracts

| Family | Who writes the query | LLM JSON | Code binds |
|---|---|---|---|
| Log | expander from a food pool | `{query, foods: [food_id, …]}` | amount path → grams → `ledger_tail` |
| Evaluate | same, then unfit is a second speech pass | same shape | fit: exact `last_plan`, `last_verdict=accept`; unfit: empty `last_plan`, `reject` + closed reason codes |
| Recommend | template | none | `last_plan=[]` (any safe plan); `plan_windows` = meal-slot ∩ remainder |
| Update | template with slot fills | none | exact numbers/allergies, or Env re-derives windows, or a code-side band |
| Composite | expander on the log step; template or chained scene on step 2 | `{query, foods}` for the log foods only | two sub-oracles; recommend remainder after log |

Amount path (explicit grams, named measure, unspecified → qns) is a mill knob and a Log/Evaluate parse rule, not a Situation. They combine. Bowl of rice is qns, not cup. Explicit grams may appear in the query. Do not teach “a serving of”.

## Recommend world fill (no expander)

1. Pick a roster person (windows already derived).
2. Pick occasion. Query template follows occasion only (“What's for dinner?”), not leftover/allergy/tightness.
3. Ledger at an occasion is whatever **Log** items already happened earlier that day (empty if none). Do not LLM-author leftover grams. Do not code-lay a shadow meal that is never a Log item. Leftover recommend is queued later than those logs; empty-ledger recommend can sit at breakfast or any first meal.
4. Constrained recommends (≥8) are hard S0 (profile allergy, leftover remainder, or impossible windows), still with ordinary speech. Named-dish traps do not recite the allergy.
5. Oracle does not score `last_verdict`.

Update world fill is the same roster person plus an intent on the card (add/remove allergy, weight, phase, fatigue). The query *does* state the change, because that is the user problem.

## Evaluate verdict

`last_verdict` starts `None`. Fit: `accept`, `last_plan` is the named meal, `last_reasons` empty. Unfit: `reject`, `last_plan` empty, `last_reasons` equal the code-computed set. Silence is not reject. No free-text critique; Other is product-only, never gold. No new evaluate op: `submit_plan` carries verdict and reasons. Recommend's empty `last_plan` remains the any-safe-plan sentinel and does not use `last_verdict`.

Closed reason codes (exact match for Pass): `allergy`; for each judged nutrient `{kcal,protein_g,carb_g,fat_g,fiber_g,sodium_mg}` a `_hi` and/or `_lo` when that bound is violated. Gold = every code that actually fires after bind, not a single “primary” reason.

## Evaluate-unfit types (authoring)

Unfit means the **named meal** fails `plan_windows` (meal-slot ∩ remainder) or hits a profile allergen. Query still names the meal. Authoring is three dimensions, not seven peer families: **knife** × **scene** × **outcome**.

Knives (v1): `allergy` (add a profile-allergen food); `over_slot` (one catalog-legal bump or one ordinary accompaniment); `under_slot` (drop or step down); **`swap`** (iso-caloric substitution so gold can fire `fat_g_hi` / `fiber_g_lo` with **no** kcal code — in v1). Scene: empty ledger vs leftover (copy earlier Log rows). Outcome: `sodium_hi` and `multi` are coverage tags, not knives; never add a violation just to earn `multi`.

`leftover_over` / `leftover_under` are **derived** after bind: a hi/lo code is leftover iff the remainder leg binds and the slot leg would have passed. Prefer leftover_over for energy overflow when the timeline already has logs. `leftover_under` stays in the draft pool (last meal only, small floor): keep if probe shows it discriminates agents who skip the ledger; drop from the frozen split if it does not.

Also require some **fit** items with a non-empty leftover ledger, so “ledger present ⇒ reject” is not a free feature.

Not Evaluate-unfit: no named meal (constrained Recommend); announcing a new allergy (Update / Composite); a substitute (Recommend).

## Unfit speech (second expander call)

Start from a bind-confirmed fit meal, or from a leftover scene where the same plate is already unfit. Code applies the knife until the type’s predicate holds. Then a second LLM rewrites the query. Prompt may carry intent (bigger / smaller / add food / include the allergen) and the **code-chosen** foods and speakable amounts. It does not receive window numbers. `foods` in JSON must match that list.

Perturbations stay on a plate a person could eat (ADR 0010). If the next legal step is cartoonish, drop that knife and try another item, leftover_over, swap, or allergy. Do not double blindly. Prefer leftover_over for energy overflow when the timeline already has logs — that keeps the dinner itself ordinary.

## Review harness (two-stage committee)

After bind, review is a Claude-Code-style committee, not Pass. Two stages, different model families, k=3 (k=5 only for contested items). Majority (≥2/3) on the LLM legs.

- **Stage A numbers.** Code is a hard gate (one veto): portion back-resolve, pool membership, grams = table, windows/allergy, reason-set equality, which remainder/slot leg fired. Then 3 LLMs see **food+grams only** (no query) and vote “eatable plate?”. They do not vote whether 118 g is the QNS fact.
- **Stage B speech.** 3 LLMs see query + food names (no window numbers): natural speech, the query names that meal, Recommend does not leak leftover/allergy/remaining kcal. A code leak scan can sit beside the vote.

Code-gate failure drops the candidate. LLM majority-fail may start as a human alarm (issue 09) and later become a drop. One report; do not merge A and B into one prompt.

## Rejected

Four family pipelines; one universal day script; LLM Recommend/Update queries; leftover/allergy/tightness as Recommend wording; a leftover S0 whose foods were never a Log item; code-prebuilt Evaluate named meals as the first author; hiding every solid cup or forbidding “150 g”; merging vote and blind judge; putting remainder kcal in the expander prompt; Other as a gold reason; shrinking 48/72/48/36 or treating Constrain as a family (ADR 0016).
