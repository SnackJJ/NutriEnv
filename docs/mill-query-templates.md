# Mill query templates (draft for review)

Recommend and Update queries are filled from these shells. Difficulty lives in S0, not in wording. English only. Slot `{occasion}` ∈ breakfast / lunch / dinner / snack. Do not add leftover recap, remaining-budget talk, or allergy dumps on Recommend.

## Recommend

| id | shape | query | S0 does the work |
|---|---|---|---|
| rec-occasion | empty ledger or leftover | `What's for {occasion}?` | leftover = earlier Log rows on the timeline |
| rec-occasion-eat | same | `What should I eat?` | occasion from scene |
| rec-dinner | dinner | `What's for dinner?` | default dinner shell |
| rec-breakfast | breakfast | `What's for breakfast?` | empty-ledger morning Rec is first-class |
| rec-lunch | lunch | `What should I eat for lunch?` | |
| rec-snack | snack | `I need a snack.` | keep thin; snack is optional |
| rec-post-gym | gym persona, post-workout scene | `Just finished lifting — what should I eat?` | phase/windows on Profile, not “I'm cutting” |
| rec-named-dish | allergy trap in profile | `Thinking of {dish} tonight — what should I eat?` | `{dish}` is a catalog food the person is allergic to; query does **not** say allergic |

Not Recommend (those are Update or Composite):

- `Eggs are off the table for me. What can I have tonight?`
- `I already ate breakfast and lunch. What should I eat?`
- `I only have room for a small lunch.`
- `I'm cutting. What should I eat?` (phase is Profile; saying “I'm cutting” is Update)

## Update

`{n}` is a number from the slot card. `{allergen}` / `{food}` are spoken names; Oracle stores catalog tags.

| id | intent | query |
|---|---|---|
| upd-add-allergy | allergy_exact | `I just found out I'm allergic to {food}. Add that to my profile.` |
| upd-add-allergy-short | allergy_exact | `Add {allergen} to my allergies.` |
| upd-rm-allergy | allergy_exact | `I got tested — I'm not actually allergic to {allergen}. Take that off my list.` |
| upd-weight | weight_exact | `I weigh {n} kg now. Update my weight.` |
| upd-phase-cut | phase | `I'm cutting now.` |
| upd-phase-muscle | phase | `I want to start building muscle.` |
| upd-phase-maintain | phase | `Stop the cut — maintain for a while.` |
| upd-fatigue | fatigue (band) | `I've been exhausted. Can we ease the deficit a bit?` |
| upd-kcal-explicit | weight_exact / window number | `Raise my calorie range by {n} at both ends.` |

Composite (not a Rec shell): Update speech **and** a meal request in one query, e.g. `I'm allergic to shrimp now. What's for dinner?`

## Notes

- Same shell + different person/timeline = different items. Do not mint 72 unique Rec paraphrases.
- `{dish}` / `{food}` must exist in the catalog and match the Profile tag after expansion (`shrimp` → `shellfish`).
- Reviewer: mark any shell that announces leftover, remaining kcal, or known allergies on a pure Recommend item.
