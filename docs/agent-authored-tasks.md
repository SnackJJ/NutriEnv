# Agent-authored task admission

The active entry is `nutrienv.bench.pipeline.generate_one` and
`scripts/generate_one_cli.py`. The author writes the natural question and structured
interpretations together; a separate reviewer checks whether the question entails them.
Code does not parse or back-resolve natural-language quantities.

## Responsibilities

- Author: inspect real catalog facts; choose food identity, preparation, quantity evidence,
  complete ledger variants, profile changes, meal occasion and explicit extra requirements.
  Clarify the question conversationally, not with hidden gold grams or catalog labels.
- Code: validate IDs/evidence, multiply catalog units, derive goal windows and remaining
  budgets, check verdict reasons, and replay legal witnesses through Env and Scorer.
- Reviewer: inspect the exact question, interpretations and food facts independently.
  Check cuts, raw/cooked/frozen states, serving sizes, units, timestamps, inventory,
  allergies, updates and hypothetical-vs-consumed food. Reject hidden distinctions and
  qualitative promises without a corresponding scoring rule.

A code check cannot establish semantic entailment. A reviewer approval is not a mathematical
feasibility proof. Both are required; neither silently repairs the other's output.

## Draft format

A draft is `{author_id, item, witnesses?}`. `item` uses the frozen task schema, except:

- Every food row has `portion:{key,count}` or `portion:{grams}`, not precomputed `grams`.
  A key must exist on that actual food. Missing QNS never substitutes piece/cup. Measured
  grams must be justified by the natural question; witness recipe weights are proposals.
- S0 contains complete body facts and explicit `plan_scope: meal|snack|day`. Code derives
  its windows; the author cannot inject arbitrary nutrient windows.
- Each scored child declares its expected `profile`. A judged plan also declares
  `plan_occasion` and `budget_basis: s0|ledger`, not `plan_windows`. Day occasion means a
  whole-day remainder; named meals use meal-slot intersections.
  Expected profile window patches are permitted for explicit numeric user requests, which
  the reviewer must check against the question. Unrequested arbitrary caps are not allowed.
- A free recommendation keeps `last_plan:[]`. `plan_high_protein` is set only for an explicit
  request. Complete `ledger_variants` are authored, not inferred by a parser.
- Judged plans require `witnesses:[{actions:[...]}]`: legal successful action traces for
  every complete ledger interpretation. Food writes and submitted items carry the same
  structured portion evidence. These witness meals prove feasibility without a grid search
  inventing a plate; they do not restrict the tested agent's free recommendation.

The full instructions live in `AUTHOR_CONTRACT` and `REVIEW_CONTRACT` in `generate_one.py`.

## Independent review

Prepare the grounded request for another agent:

```sh
uv run python scripts/generate_one_cli.py --draft draft.json --prepare-review --output review-request.json
```

The reviewer returns `{reviewer_id, draft_sha256, verdict, findings}`. Its identity must differ
from the author's; approval cannot carry unresolved findings. The hash binds the original
packet, computed item, catalog identity, scorer version, prompt fingerprint, mass limits and
review instructions. Changing food nutrients/allergens or the draft invalidates an old review.

Admit the reviewed item:

```sh
uv run python scripts/generate_one_cli.py --draft draft.json --review review.json --output admitted.json
```

The output preserves the original author packet and review alongside the computed item.
Missing inputs, stale reviews, invalid evidence and illegal/incomplete witnesses fail loudly.
A deliberate revise/reject is returned as a rejection, not replaced by a fixture.
The CLI does not silently invoke a paid model: agents supply artifacts, or a caller injects
separate author/reviewer callables. Local tests use explicit fake callables, not model runs.

## Legacy consumers

`pipeline/legacy_generate_one.py`, `resolver.py`, `legacy_run_batch.py`, `expander.py`, the
curated `realize` tables and `world/portions.py` remain historical/calibration consumers.
Their grammar is not the active admission gate. The parser/template CLI is explicitly at
`scripts/archive/generate_one_cli.py`; legacy tests import the legacy module by name.
This preserves historical experiments without an implicit fallback from the new pipeline.

The v1.1 rebuild consumes the reviewed `portion:{key,count}` evidence in
`v1.1-content-revisions.json` directly. It reproduces existing authoring decisions; it does
not run a new model or infer new interpretations from their English wording.
