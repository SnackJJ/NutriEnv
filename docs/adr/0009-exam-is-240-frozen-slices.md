# The published exam grows to 240 frozen, sliced items

The destination ruler is a versioned frozen split of **240** tasks, not a
live Generator seed. Allocation is Codex's:

| family | n |
|---|---|
| log | 48 |
| recommend | 72 |
| evaluate | 48 |
| update | 36 |
| constrain | 36 |

Within those, freeze at least **24** fuzzy-or-mixed-portion logs and **24**
leftover recommends. Report every family × persona × situation slice; do not
hide holes behind a single pass rate.

`data/splits/v0-gold.json` (40 items) stays the public calibration set. It is
not overwritten. Later increments are new files (`v0.1-gold.json`, then a
named `v1-gold.json` when the 240 are admitted).

Generator remains a draft factory (ADR 0006). Seed tables are the diversity
source: rows differ in food / portion / ledger geometry, not wording.
Paraphrases are not new rows. A 20:1 draft-to-exam ratio is a production
budget, not a requirement to dump thousands of items in one sitting.

Items are admitted only after: catalog-backed grams or remainder windows,
gold contract oracles, leak/unachievable/duplicate rejection, and human
review that the spoken query entails the scored end state.

`evaluate` items score exact-plan transcription (`last_plan` equality).
"Is this meal okay / what instead?" shapes belong in `constrain` (the
`v0-rec-conflict-001` / condition mechanism). Do not fill the 48 evaluate
slots with rejected-plan items that cannot have an achievable oracle.

Each increment file names the catalog path and a build hash. `v0.1` copies
the 40 KEEP items so "40 + slice" is verifiable. Slice reports print `n`
beside every cell and show counts, not percentages, when `n < 5`.

Validator: drop any row whose `resolve_portion` is `None`. Flag, do not
auto-admit, household measures whose official grams are implausible as
food knowledge (live examples: bread slice 10 g, broccoli piece 10 g).

v0.1 first increment target is **16 fuzzy/mixed-portion logs + 8 leftover
recommends** (permit +16..+24 if review rejects rows). Count the retained
v0 items toward the 240 totals. Do not pad.

No NutriBench / NGQA item drop-in. No LLM-as-judge. No Branded in the
default catalog. No new disease personas this round.

**Status**: accepted
