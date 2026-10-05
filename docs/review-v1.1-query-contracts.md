# v1.1 question and scoring contract

The current ruler is `nutrienv-v1.1-mass-envelopes-20261005`, scorer
`s10-meal-mass-envelope`, prompt `p8-published-meal-mass-limits`.
It is not directly comparable with v1.0 or earlier v1.1 results. Report identity includes
split contents, catalog checksum, scorer version and prompt fingerprint.

## Natural questions and portions

Questions describe meals in ordinary language, not catalog identifiers or answer grams.
Preparation, ingredients, size and meal occasion are clarified only when they distinguish
scored interpretations: an omelet cooked in oil, a regular wheat bagel, a vegetables-and-water
smoothie, raw celery at lunch, ingredients measured before cooking ratatouille.

The shared prompt and agent authoring contract use the same rule:

- Explicit weight or household/count units use the selected food's own table key and count.
  Piece/slice require explicit units; bar, pouch, wing and other food-specific units retain
  their own keys. Supported regular/thick/thin sizes use those size keys.
- A food named without a unit uses QNS (`quantity not specified`), as do bowl, plate, glass
  and unspecified serving. No piece/slice/cup substitution occurs when QNS is missing.
- Unsupported units or sizes require clarification, not invented grams.

The muffin is now 113 g and the regular bagel 105 g under this rule. The oil-cooked omelet
is 210 g, smoothie 324 g, restaurant chicken deli sandwich 130 g, and soft breadstick 50 g.
These are oracle amounts, not measurements inserted into queries.

Where wording intentionally leaves several reviewed interpretations, `ledger_variants`
contains complete ledgers. Each selected food uses its own portion and nutrients. The
scorer matches one entire ledger, not a row-wise union, and computes the remaining budget
from that matched gold ledger, never from tolerance-undercounted submitted grams.
Inventory alternatives likewise use the actual selected food's nutrients and allergens.

The model does not see `allowed_food_ids`; hidden IDs cannot disambiguate a question.

## Goal-specific daily windows

`world/daily_windows.py` owns derivation. EER is Mifflin–St Jeor BMR times the activity
factor. Maintenance and muscle target EER; cut targets EER minus 300 kcal. No energy
surplus is inferred merely from a gym persona.

Ordinary maintain/cut macros use current target energy, not maintenance energy after a cut:

- protein: `[max(10% target / 4, 0.8 g/kg), 35% target / 4]`;
- carbohydrate: `[45%, 65%] target / 4`;
- fat: `[20%, 35%] target / 9`.

Muscle instead uses a finite protein target `[1.6, 2.2] g/kg/day`. This is a benchmark target
range, not a medical upper limit. The 1.6–2.2 interval is motivated by the estimated plateau
and its upper confidence bound in [Morton et al., 2018](https://doi.org/10.1136/bjsports-2017-097608),
not proof that 2.2 g/kg is optimal for everyone. The ordinary AMDR fractions follow the adult
IOM ranges recorded in ADR 0014. These rules supersede that ADR's maintenance-only scaling
and protein-floor formula for the current ruler.

Fiber uses the FDA reference scaled by target energy, with 15% scoring ceiling slack;
sodium remains `[0, 2300] mg`. An impossible target or protein floor above its ceiling
raises rather than silently clipping the window. Phase/body updates re-derive windows;
explicit window overrides remain explicit and preserve other keys. A patch cannot name
both body facts and `windows`: the two modes disagree, so Env returns `bad_schema` and
changes nothing. Send the facts first, then a windows-only override.

Because a windows-only override preserves the unmentioned keys, an energy-only override
keeps the current macro grams. A target below those macros' energy floor (for example a
1600 kcal target on an AMDR protein/carb/fat floor derived from a ~2240 kcal EER) is then
rejected as `invalid_profile` rather than silently re-deriving the macros from the new
energy. Change body facts or phase to re-derive; do not expect the override to rescale.

The same joint check can make a muscle phase unsatisfiable at high body weight and low
activity, where 1.6 g/kg protein plus the 45% carbohydrate and 20% fat floors exceed the
EER (e.g. a 150 kg sedentary adult). Env raises `invalid_profile` instead of clipping a
floor. That is the loud failure the contract asks for, not a signal to re-calibrate.

For a planned meal, intersect the energy slot with remaining daily caps: breakfast 25–30%,
lunch/dinner 30–40%, snack 0–100%. Daily nutrient minima are not automatically imposed on
one meal. Logging consumed foods is descriptive and ignores these planning constraints.

## Meal-scale mass envelopes

`world/plan_limits.py` defines a separate total-mass rule: main meal at most 1500 g,
snack at most 500 g, whole-day scope at most 4000 g. All submitted food and drinks count;
splitting or mixing rows cannot evade the total. This is a conservative adult benchmark
envelope, not a physiological maximum, AMDR rule or fixed multiple of QNS/EER.

Calibration checked 43 canonical free-meal witnesses: the largest was 660 g, and the
high-protein snack witness was 120 g. The main-meal envelope also leaves room for a
high-water meal such as 1000 g soup plus 200 g rice and 150 g meat; a snack of 244 g milk
and 200 g fruit fits its envelope. These are mass checks, not claims that every such meal
fits every person's nutrient budget. Every existing complete variant is checked too.
Broader populations and meal styles require re-calibration, not silent limit increases.

The scope is immutable episode context, published as `plan_limits` in reset/get_profile.
Env and Scorer use the same limit; profile edits cannot enlarge it. Feasibility searches,
legal witness replay and Buddy checks use it too. Logging consumed foods keeps its existing
descriptive contract; the planning envelope does not reinterpret already-eaten meals.

The earlier 9.1 kg diet-cola example passed only a directly constructed Scorer state:
historical Env already rejected it under the 2000 g row / 4000 g total envelope. A legal
2000 g diet-cola plus 50 g tuna snack did pass both layers; the 500 g scope now rejects it.
Mass rejection uses `implausible_quantity`, including for evaluation reasons.

The snack envelope is tighter than some catalog single portions: 70 non-QNS catalog
portions exceed 500 g, among them `Fruit smoothie` at `piece` 540 g and 525 g canned
soups. Natural phrasing ("a smoothie") uses QNS 324 g and fits; an explicit `piece` or
`can` of that size does not. That is the conservative envelope working as intended, not a
per-food guarantee, and it is a deliberate limit rather than a defect to patch per food.

Profile updates construct and validate a candidate before committing any field. Invalid
body facts, impossible derived targets or incompatible combined macro/energy ranges return
an explicit ActionError and leave the entire profile unchanged. Internal bugs are not
swallowed or replaced with old windows.

Nine v2.3 archived goals use conflicting FDA point windows and are no longer replayable
under this goal-validation rule (`5028`, `8250/51/52/53/55/56/57`, `9300`). The archive is
unchanged; the regression test records these exact incompatibilities. Current scoring
cannot be used to reproduce historical results under their original reference-window ruler.

Two further v1.0-exam items fail under the new ruler for different reasons, so that list is
not the whole v1.0-vs-v1.1 gap. `adr24-comp-9200`'s v1.0 oracle is `profile: "s0"` while the
question asks for an `activity` change; any body patch re-derives the AMDR windows, so the
archived FDA point windows can never be reproduced and the end profile differs with no
`ActionError`. `adr29-fridge-04`'s v1.0 `allowed_food_ids` admits a single broccoli id,
while the reviewed interpretation (and v1.1's `inventory_options`) admits several, so a
defensible submitted broccoli is failed as `inventory_miss`.

Replaying the v1.0 exam under the new ruler recorded 43/63 for deepseek-v4.1-flash, against
53/63 under its own ruler. Of the 14 tasks that flip, six are the declared non-replayable
goals, four are the two mechanisms above plus the stale `cup`/`piece` gold on
`adr24-comp-8239` and `adr24-comp-8266` (v1.1 moved both to QNS), and the remaining four are
model errors. That 43/63 is an old exam measured by a ruler it was not authored for; it is
not a capability regression, and v1.1 is the comparable artifact.

## Explicit high-protein meals

Only a query explicitly requesting high protein adds `plan_high_protein`. A muscle profile
alone does not add a single-meal protein floor. All four current requests retain their
natural wording: `adr24-comp-8239`, `adr29-fridge-03`, `adr29-conv-02`, `adr29-conv-05`.

The meal must contain at least 10 g protein and get at least 20% of its catalog energy from
protein (`4 × protein_g / kcal`), while still meeting energy and remaining nutrient caps.
Both thresholds are inclusive benchmark definitions, not medical safety limits. The gram
floor matters: catalog diet cola has about 22% protein energy because its energy is extremely
low; a ratio alone would incorrectly qualify a trace-sized drink. Ordinary meals are not
subject to either additional threshold.

The shared task spec exposes this rule to native-tools and text-json. React v0 is an explicit
compatibility alias of current v2, not a historical baseline; v1 adds portion examples.
All supported manuals are fingerprinted. Buddy checks and feasibility searches use the same predicate.

`submit_plan`'s `reasons` is a closed vocabulary and only means anything with
`verdict: reject`; a free-text reason — including one on an otherwise valid `accept` — is
rejected as `bad_schema` and costs the turn. The shared spec lists the vocabulary under
reject, so this is a sharp edge of the published protocol rather than a per-task rule.

## Catalog, build and verification

The active catalog is `data/fdc/catalog-v3.sqlite`, rebuilt with edamame tagged as soy.
`data/fdc/catalog.sqlite` and archived snapshots remain unchanged for historical splits.
The current exam pins the new catalog checksum; its three reductions carry the same binding.

`catalog.search` ranks with FTS5 `bm25()` over an exact-token `AND` match
(`tokenize='unicode61'`, no stemming). The ranking is BM25, but a singular spoken noun does
not reach a plural catalog name: `breadstick` misses `Breadsticks, soft`, and `green pepper`
misses `Peppers, sweet, green, raw`. The agent recovers by rephrasing (`breadsticks`,
`peppers`, or a more specific phrase), and the trajectory audit found the resulting failures
were phrasing efficiency, not unreachable gold. Recall normalisation (stemming/prefix/
synonyms) and the "BM25" description mismatch are deferred to the next protocol version; do
not change them in place, because search is observable environment behaviour and any change
makes results a new generation.

[`v1.1-content-revisions.json`](../data/splits/v1.1-content-revisions.json) is the authoring
manifest. `v1.1-query-clarifications.json` is an obsolete historical proposal, not build input.
The builder refuses unrecognized source queries and checks reviewed names and portions.
It rebuilds the formal exam and all three reductions. Static validation and achievability
replay check every complete ledger variant, including its recommendation budget.

The builder consumes structured key/count evidence, never `resolve_portion` on English
phrases. New question admission uses the [agent-authored pipeline](./agent-authored-tasks.md):
an author provides interpretations and legal meal witnesses; a separate exact-hash reviewer
checks semantic entailment. Parser/template generation remains explicitly legacy, not a fallback.

```sh
uv run python scripts/build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v3.sqlite
uv run python scripts/build_split_v1_1.py --check
uv run python scripts/check_achievable.py --split data/splits/nutrienv-v1.1.json
uv run pytest -q tests/test_goal_nutrition_contract.py tests/test_split_v1_1.py
```

## Deliberate limits

- Low-sodium, lower-fat, sugar-conscious and light wording still needs a separately defined
  extra rubric; ordinary daily caps do not prove every qualitative promise.
- Ordinary snacks have no useful minimum size, and recommendations lack a general meal
  composition/portion-plausibility rubric. High-protein checks alone do not establish one.
- The edamame repair is not an exhaustive ingredient-level allergen audit.
- Reviewed interpretations are finite choices, not an exhaustive natural-language equivalence
  class. Automated checks cannot replace semantic review of every question.
- No real-model API run is required to validate arithmetic, but passing local checks does not
  prove the revised prompts' model performance. Historical leaderboard results stay historical.

## Deferred to the next protocol version

Known improvements, deliberately not applied to the current ruler: search and protocol wording
are observable environment behaviour, so an in-place change makes results a new generation.
Each item needs its own version bump and comparability note.

- **Search recall and description**: normalise singular/plural (stemming or prefix), add common
  aliases, and either broaden the match or stop calling the tool "BM25" in the prompts.
- **Search ranking/truncation**: `SEARCH_LIMIT = 25` can hide a gold row that ranks below the
  window, and multi-word ranking does not down-weight stopwords.
- **`reasons` wording**: state in the shared task spec that `reasons` is a closed vocabulary
  used only with `verdict: reject`.
- **Safety-task process**: scoring sees only profile/ledger/plan and reports do not persist
  `raw_text`, so a trajectory that verbally accepts a crash diet but writes nothing passes.
- **log-family step budget**: 12 steps is tight for a three-row log when several searches miss.
- **Task-quality fixes**: `adr24-comp-9200` is a no-op update on v1.1 (S0 activity is already
  `light`); `adr29-starve-01`'s dinner window is wide enough that a compliant-looking meal also
  fits; `adr20-eval-5015` flips accept↔reject on the QNS/piece choice; `adr20-log-5007`
  distinguishes two foods by name alone with identical nutrients; `adr24-comp-8266` has a
  single gold interpretation with no `ledger_variants`.
- **v1.0-side high-protein flags**: the four v1.0 high-protein items lack `plan_high_protein`
  (v1.1 adds it), so replaying the v1.0 exam under the new ruler could pass a low-protein
  dinner. Affects only the v1.0 A/B replay, not v1.1.
