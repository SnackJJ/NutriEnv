# Spec: enable recommend / update families in the batch orchestrator

**Status:** decided by coordinator (Phase 5/6 forward, per user: new exam forms, not patching the archived pilot).
Design authority: `docs/adr/0016-four-families-constrain-is-situation.md` — the published exam has four
families (Log, Evaluate, Recommend, Update) plus Composite (36 of 240); situation floors sit inside
evaluate/recommend.

## Problem

`src/nutrienv/bench/pipeline/types.py:48` `SUPPORTED_FAMILIES = frozenset({"log", "evaluate", "composite"})`
— the batch orchestrator (`run_batch` / `scripts/generate_batch.py`) refuses `recommend` and `update`
families, even though:
- `generate_one` already implements all five families (`generate_one.py:162` allows
  log/evaluate/recommend/update/composite);
- issue 08 landed the Recommend/Update template shells and reactive manual;
- ADR 0016 sets recommend 72 / update 36 inside the 240.
So the mill CAN make recommend/update items but the batch entry cannot request them — recommend/update
floor coverage (24 leftover, 8 constrained) is impossible to produce at scale.

## Change

1. `types.py`: `SUPPORTED_FAMILIES = frozenset({"log", "evaluate", "recommend", "update", "composite"})`.
2. Check `run_batch._parse_spec` (`run_batch.py:338-343`) and `scripts/generate_batch.py` choices
   (line 91) pick it up automatically (they reference SUPPORTED_FAMILIES — verify).
3. Check `quota_ledger` / ADR 0016 accounting: verify `run_batch.py:236-245` ceilings
   (composite <= 36, total <= 240) still hold with recommend/update families requested — the ledger
   must count single-family accepteds (log/evaluate/recommend/update) + composite against 240.
   Look at how `quota_ledger` classifies families; if it has an explicit family list, extend it.
4. `scripts/generate_batch.py` `--family recommend --family update` parse without error (argparse
   choices come from SUPPORTED_FAMILIES — verify).
5. `--synthetic` smoke: run a SMALL offline batch (`--synthetic --family recommend --count 2
   --family update --count 1 --family composite --count 1 --seed <fixed>`) and confirm it completes
   and its output split passes `validate_draft` on every item. NOTE: `run_batch` now structurally
   runs `_code_gate` before the reviewer (S09-1), so the pass-through reviewer in synthetic mode is
   safe. Report what the smoke produced (families, counts, validate results) in your report — do not
   freeze anything or write into a published exam path.

## Tests (add to `tests/`)

- Update/extend the quota ledger tests: requesting recommend+update families in a batch spec no
  longer raises "unsupported family"; the 240/36 ceilings still enforce.
- If `run_batch` or `generate_batch` tests hardcode the old 3-family set, update them to the 5.
- A synthetic run (unit-level, tiny) that a recommend-family job produces a Task with
  `family == "recommend"` and a valid oracle (not rejected).

## Definition of done

1. `pytest -q` in /home/jzq/Projects/nutri-env → 0 failed (expect 1290+).
2. Small synthetic smoke run completes (families log/evaluate/recommend/update/composite all
   constructible through generate_batch), documented with evidence.
3. Commit to main with "pipeline: " prefix (e.g. "pipeline: enable recommend/update families in
   batch orchestrator (ADR 0016 floors)"). Do NOT push.
4. Append a short section to `reports/impl-composite-floors.md` or a new
   `reports/impl-batch-families.md` with the smoke evidence.
5. Do NOT touch: docs/adr/*, data/splits/* (except your own draft output file), *.sqlite,
   scorer.py, validator.py, review_harness.py.

Work autonomously. If blocked, stop and report what is done.