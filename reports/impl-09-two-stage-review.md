# Impl 09 — two-stage review committee (Stage B, window gate, k=3 majority)

Branch `ship-09`, on top of c328bd0 (Stage A code-gate + injection seam).

## Files and functions changed

- `src/nutrienv/bench/pipeline/review_harness.py`
  - New constants: `REASON_WINDOWS_EMPTY` / `REASON_WINDOWS_OUT_OF_BOUNDS` /
    `REASON_WINDOWS_UNPASSABLE`, `REASON_LEAK_LEFTOVER` / `REASON_LEAK_ALLERGY`
    / `REASON_LEAK_REMAINING_KCAL`, `STAGE_B_SYSTEM`.
  - `stage_a_code_gate`: now appends `_window_reasons(task)` after the existing
    grams check. Window reasons fire **only when `oracle.plan_windows is not
    None`** (unpinned oracles, e.g. log tasks, skip them).
  - `_window_reasons`: empty-intersection (any lo > hi) → `windows_empty`;
    else per-key bounds vs the profile's daily ceilings →
    `windows_out_of_bounds`; else Atwater kcal feasibility (`_kcal_infeasible`)
    → `windows_unpassable`. Order matters: malformed windows stop at EMPTY.
  - `_kcal_infeasible`: physics-only check using 4/4/9 kcal per g
    protein/carb/fat (matches `nutrienv.bench.windows.KCAL_RATIO_CAP`). No
    catalog needed, so it cannot disagree with catalog artifacts.
  - `stage_b_leak_scan(task)`: recommend-family only. Maps to landed 07/08
    realizations (see below). Empty list = clean.
  - `format_stage_b_prompt(task)`: speech view — query + resolved food names,
    no grams/windows.
  - `_parse_vote(text)`: uses the previously unused `_json_blob` helper +
    `json.loads`; requires a bool `eatable`; returns `(eatable, reason)` or
    None.
  - `_run_stage_vote(voters, prompt, parse_retries)`: collects k votes with
    the existing retry-on-empty loop, parses each, computes majority:
    ≥2 parsed yes ⇒ `pass`, ≥2 parsed no ⇒ `fail`, otherwise `undecided`;
    returns unparsed count for anomaly tracking.
  - `review_candidates`: full committee flow (below) + structured verdicts.
  - `_live_caller(model_id, system)`: Stage B live pool posts with
    `STAGE_B_SYSTEM`.
  - Module docstring updated; `__all__` extended.
- `tests/test_review_harness.py`: all tests in this file were written in
  2a6bff7 alongside the code they test, including the five window tests
  (the working tree at that point held only one committed test and no
  `REASON_WINDOWS` references — they were not pre-existing WIP specs).
  They cover window gates, leak scan, speech votes, majority/verdicts.

## Committee flow (`review_candidates`)

1. `stage_a_code_gate` → any reason: drop, verdict `drop_code_gate`, no LLM.
2. Stage A votes (food+grams prompt) → majority; fail/undecided ⇒ `alarm`
   (never silently passes, never drops); unparsed replies ⇒ `anomaly`.
3. `stage_b_leak_scan` → any reason: drop, verdict `drop_leak_scan`, no
   Stage B LLM vote (code fails drop; naturalness alone never drops).
4. Recommend candidates only: Stage B speech votes (query + food names) →
   same majority/alarm/anomaly rules. Log candidates get no second vote —
   their plate was already voted by Stage A (this also keeps the committed
   `test_code_gate_off_table_grams_rejects_without_llm_vote` expectation
   intact, whose injected Stage B voters are never called).
5. Verdict per candidate: `pass` | `alarm_majority` | `drop_code_gate` |
   `drop_leak_scan`. Per-stage detail lives in
   `entry["stage_a"]` / `entry["stage_b"]`
   (`{"code_gate"|"leak_scan": [...], "votes": {model: {raw, eatable,
   reason}}, "majority": pass|fail|undecided|none}`), plus top-level
   `dropped` / `alarm` / `anomaly`.

## Leak-scan mapping to 07/08 realizations

- `leak_leftover` ← `realize._leftover_from_row` (07): leftover S0 carries a
  non-empty ledger copied from parent Logs, so a non-empty ledger with
  `plan_windows is None` means the leftover timeline is not bound into scoring.
- `leak_remaining_kcal` ← `generate_one._recommend_from_template` +
  `meal_slot_and_remainder` (08): pinned windows may never budget more of any
  daily nutrient than `daily − eaten` (rounded remainder hi, 1e-6 tolerance).
- `leak_allergy` ← `realize.bind_evaluate_reasons` "allergy" code (07/08):
  ledger foods whose catalog `allergen_tags` intersect normalized profile
  allergies make the world unsafe.

## Carry-over resolutions from superseded oral-gate 11a

- No skip-code-gate-and-no-voter mode: both `review_candidates` and
  `make_reviewer` raise `ValueError` unless Stage A and Stage B pools are
  non-empty; the gate always runs before any vote. Nothing re-adds the old
  `--skip-gram-backresolve` shape.
- Harness/review reports embed no pytest passed total;
  `reports/review-harness-two-stage.md` documents this explicitly.
- Freeze-blocker note recorded, not fabricated: `reports/gray-zone-probe-v2.md`
  (chicken-piece-105 / tuna-can-75 / beef-piece-65) belongs to the later
  admission ticket and must run against the live `grams_gate` path before any
  freeze. This ticket does not create it.

## Test evidence

```
$ /home/jzq/Projects/nutri-env/.venv/bin/python -m pytest tests/test_review_harness.py -q
.................                                                        [100%]
17 passed in 0.14s

$ /home/jzq/Projects/nutri-env/.venv/bin/python -m pytest -q
1199 passed in 51.56s
```

Counts above are session evidence, not frozen harness output. Unmodified:
docs/adr text, `data/splits`, catalog sqlite files, the scoring rule
(`Pass ⇔ end state == Oracle`), and all pre-existing test expectations.

---

## Fix round — S09 findings (claude opus review, verdict REV)

Commit: "09: enforce code gate structurally in run_batch, fix S09 review findings".

- **S09-1 (blocker)** — `run_batch` now applies `stage_a_code_gate`
  structurally (`_code_gate` in `run_batch.py`) after candidate assembly and
  before any `reviewer(...)` call; gate failures become
  `Rejected(query, "code_gate", family)` and never reach the reviewer or the
  freezer. No mill mode can reach a freeze without the gate, regardless of
  which reviewer is injected. `pass_through_reviewer` stays vote-level-only;
  its docstring now says the gate cannot be skipped. Regression test:
  `test_run_batch_structural_code_gate_drops_off_table_grams` (real pipeline,
  `300 g` milk, pass-through reviewer → accepted=[], rejected=[code_gate]).
- **S09-2** — the false provenance sentence above corrected; issue Status line
  now names the right commits.
- **S09-3** — restored coverage in `tests/test_review_harness.py`: empty-pool
  `ValueError` for `review_candidates` and `make_reviewer`; `_route` DashScope
  routing + missing-key `RuntimeError`; monkeypatched `call_reviewer` posting
  (no network); `resolved_items`/`format_stage_a_prompt` portion facts;
  empty-candidates result shape.
- **S09-4** — Stage B speech votes now run for **every** candidate that
  survives the leak scan (leak scan stays recommend-only). Updated
  `test_stage_b_log_candidates_get_no_speech_vote` →
  `test_stage_b_speech_votes_cover_log_candidates` (log query IS seen by
  Stage B, still hidden from Stage A); committed
  `test_code_gate_off_table_grams_rejects_without_llm_vote` updated to give
  Stage B real voters and assert the 3+3 split (Stage A prompts hide the
  query; Stage B prompts carry it).
- **S09-5** — `_kcal_infeasible` returns False when no macro span
  (protein_g/carb_g/fat_g) is present; also dropped the redundant
  `kcal_lo > forced` conjunct. Test: `test_macro_free_window_is_not_unpassable`.
- **S09-6** — `windows_out_of_bounds` appended once, not per offending key.
  Test: two offending keys still yield exactly one reason.
- **S09-7** — `parse_retries` now retries parse failures (loops until
  `_parse_vote` returns a vote). Test: `test_parse_failure_is_retried_then_parsed`
  (6 voter slots × 2 calls = 12 calls, all parsed on retry).
- **S09-8** — leak-scan docstring cites `daily_windows.meal_slot_and_remainder`
  correctly and states the allergy mapping precisely; allergy check moved out
  of the `if ledger:` block and now also scans `oracle.last_plan`,
  `oracle.evaluated_plan`, and `s0.last_plan` food ids, so a Recommend whose
  named-dish plan item carries a banned allergen is flagged with an empty
  ledger. Test: `test_named_dish_allergen_leak_with_empty_ledger`.
- **S09-9** — pools are now three distinct families per stage:
  Stage A qwen3.8-max / deepseek-v4-flash-0731 / glm-5.2; Stage B
  kimi-k2.7-code / deepseek-v4-pro-0813 / qwen3.8-2.4t-a95b (cross-stage
  family reuse is unavoidable with six registry ids; no single vendor carries
  either ≥2 majority alone). Module docstring records this.
- **S09-10** — dead `if entry["dropped"]:` branch removed.

Test evidence:

```
$ .venv/bin/python -m pytest tests/test_review_harness.py -q
.............................                                            [100%]
29 passed in 0.18s

$ .venv/bin/python -m pytest -q
1211 passed in 48.78s
```

---

## Fix round 2 — N09-1 / N09-2

Commit: "09: window-gate composite children and pin worst-case skip/no-voter mode".

- **N09-1** — `_window_reasons` now iterates `oracle.sub_oracles` when present
  (`_window_oracles`, mirroring `_oracle_pairs`), gating each composite child
  that pins `plan_windows` on its own; a child without pinned windows still
  skips. Reasons are collected once across children. While wiring this, the
  composite fixtures exposed an adjacent bug in `_kcal_infeasible`: absent
  macro keys were treated as zero instead of unconstrained, so a legitimate
  kcal+protein-only window (exactly what composite rec children pin) was
  called unpassable. Absent macros now leave the reachable kcal unbounded.
  Test: `test_composite_child_windows_are_gated` — a Task whose composite
  child pins `{'kcal': (900, 200)}` yields `['windows_empty']` through
  `stage_a_code_gate` even though the parent container pins nothing.
- **N09-2** — `test_run_batch_structural_code_gate_drops_off_table_grams` is
  now parametrized over `skip_gram_backresolve` False/True with the no-voter
  `pass_through_reviewer`; both parametrizations assert
  `accepted == []` / `rejected == ["code_gate"]`, pinning that the worst-case
  mode cannot bypass the structural gate. Module docstring reworded to what is
  true: per-stage pools are three distinct families; cross-stage family reuse
  exists.

Test evidence:

```
$ .venv/bin/python -m pytest tests/test_review_harness.py -q
..............................                                           [100%]
31 passed in 0.18s

$ .venv/bin/python -m pytest -q
1213 passed in 49.93s
```
