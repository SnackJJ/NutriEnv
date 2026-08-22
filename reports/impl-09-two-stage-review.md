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
- `tests/test_review_harness.py`: WIP window tests kept verbatim (all pass as
  written); added 11 tests for leak scan, speech votes, majority/verdicts.

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
