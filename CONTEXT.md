# NutriEnv

A steppable nutrition world and a bench that scores episodes against it. The product UI is a later client, not this context.

## Language

**Env**:
The objective nutrition world: catalog, personal state, legal actions, transitions, and observations. It does not invent recommendations.
_Avoid_: library-only search engine, harness, model

**Bench**:
A versioned exam over Env: a frozen Split of Tasks plus a Scorer that reads the finished episode and world state. v1 / v2 are different rulers, not extra points on the same test.
_Avoid_: leaderboard, product eval, rubric-for-taste, a newly sampled seed as the published number

**Catalog**:
A frozen local snapshot of USDA FoodData Central (FNDDS, SR Legacy, optional Branded). Runtime reads sqlite; it does not call the USDA API. `food_id` is the FDC id; staple slugs are aliases.
_Avoid_: USDA live API, knowledge RAG, dumping the whole id list into the opening observation

**Profile**:
The authenticated person's structured constraints and nutrient windows (allergies, targets). Not free-text advice.
_Avoid_: nutrition suggestion document, chat memory

**Ledger**:
Append-only record of what the person ate. Descriptive: an allergen meal that was actually eaten is a valid fact.
_Avoid_: meal plan, recommendation

**Action**:
A structured move the agent issues to Env (lookup, submit a plan, …). A UI card is a projection of an action, not a second action.
_Avoid_: prompt, tool name, button click

**Recommend**:
The agent's choice of foods, issued as one Action (`submit_plan` or equivalent). Env does not generate the menu.
_Avoid_: env recommendation, ranking, taste quality

**Episode**:
One user task: many internal Actions, then hand-in. v1 scores only at hand-in.
_Avoid_: chat session, product turn

**Hand-in**:
The moment Bench grades: nutrient windows, allergen intersection, and resolver-minted ids. Full trajectory is kept.
_Avoid_: mid-episode semantic abort, rubric jury

**Illegal Action**:
Malformed or unminted ids. Env rejects immediately as physics. This is not Hand-in scoring.
_Avoid_: safety gate, task failure

**Task**:
One exam item: initial world, a user query, and one primary goal. The full Action catalog is always available; which Actions are *necessary* is a property of the Task, not of a hidden tool subset.
_Avoid_: hidden tool menu, teaching-simplified action space

**Persona**:
A named S0 flavor used when authoring the Split (everyday, cut, gym, leftover, flex; medical ones stay thin). The judged facts are still windows and allergies, not the name.
_Avoid_: NGQA tag-count as Pass, diagnosis as rubric, medication tasks in v1

**Pass**:
Binary Hand-in verdict for a Task. All hard checks hold (allergen, minted ids, the Task's nutrient windows or log/update contract). The Bench headline is how many Tasks Pass, not a taste score.
_Avoid_: rubric jury, 0–100 quality, mid-episode abort

**pass@k**:
The chance a Task Passes on at least one of k independent episodes. The usual coding-bench reading of “try k times.”
_Avoid_: treating a single lucky episode as pass^k

**pass^k**:
The chance a Task Passes on all of k independent episodes. Used when comparing stochastic agents; pass^1 alone is luck-sensitive.
_Avoid_: single lucky run as model rank

**Generator**:
An optional factory that can emit a Task triple from a seed. It is not the published exam. Env does not invent Task-specific worlds; it only loads S0 from the Split (or, in tests, from this factory).
_Avoid_: sampling a new seed split as the reported number, hidden tools per Task

**Split**:
The frozen list of Tasks that is the exam. Each item is a reviewed (S0, query, Oracle). Quality is controlled by editing this file, not by hoping a template samples well.
_Avoid_: live generation at eval time, NutriBench/NGQA item drop-in

**Situation**:
A literature-inspired *kind* of nutrition problem (fuzzy portion, mixed dish, condition-suitability, unit convert, near-synonym). Generator samples Situations; it does not import foreign gold labels or official leaderboard scores.
_Avoid_: NutriBench item, NGQA graph question as a drop-in Task

**Runner**:
The composition root that binds frozen Env+split to one Harness and one Model, then writes `env × harness × model` and Pass / pass^k. The subject under test is Harness+Model, not Env.
_Avoid_: env importing a harness, scoring inside the prompt

**Harness**:
The presentation and loop that turns observations into Env Actions. It may rename tools and reshape text; it may not change gates, arithmetic, or Oracle.
_Avoid_: world logic, scorer, catalog

**S0**:
The start world of one Task: structured Profile, Ledger, Catalog view, and any pending proposals. It is data, not prompt flavor text.
_Avoid_: system-prompt backstory as the only state

**Oracle**:
The expected end world for a Task (Profile fields, Ledger rows as required). Generator derives it from (S0, query): fields the query asks to change must match; fields it does not mention must stay as S0. Pass is end state == Oracle.
_Avoid_: “any update action was called”, LLM-as-judge of intent, pending tray as v1 truth
