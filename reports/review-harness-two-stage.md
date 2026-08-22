# Review harness — two-stage committee (issue 09)

One report for the whole committee. This document describes the review design;
it intentionally carries no pytest pass counts (carry-over from superseded
oral-gate 11a: harness/review reports do not embed a frozen pytest total).

## Committee shape

Per candidate Task, in order:

1. **Stage A code hard-gate** (`stage_a_code_gate`) — pure code, no LLM:
   - `grams_off_table`: every oracle food gram must reproduce a catalog
     portion via `QUANTITY_MULTIPLES` (FNDDS/QNS anchor discipline).
   - Window reasons apply **only when the oracle pins `plan_windows`**
     (log tasks and other unpinned oracles skip them):
     - `windows_empty` — any key has lo > hi.
     - `windows_out_of_bounds` — a pinned key sits below zero or above the
       profile's daily ceiling for that nutrient.
     - `windows_unpassable` — Atwater-infeasible kcal window: macro floors
       force more kcal than the ceiling allows, or the floor needs more kcal
       than macro ceilings can reach (4/4/9 kcal per g protein/carb/fat,
       same physics as `nutrienv.bench.windows.KCAL_RATIO_CAP`).
   - Any gate reason drops the candidate **without an LLM vote**.

2. **Stage A votes (k=3)** — blind plate vote, prompt is food + grams only
   (`build_stage_a_prompt`). Voters never see the query or windows and never
   judge table-gram correctness. Each voter must return
   `{"eatable": bool, "reason": str}`; unparsable replies count as anomalies.
   Majority: ≥2 parsed yes ⇒ `pass`, ≥2 parsed no ⇒ `fail`, otherwise
   `undecided`. Fail/undecided raise an alarm — they do not drop and do not
   silently pass.

3. **Stage B code leak scan** (`stage_b_leak_scan`) — Recommend candidates
   only, mapped to the landed 07/08 realizations:
   - `leak_leftover`: non-empty S0 ledger with unpinned `plan_windows`
     (leftover timeline not bound into scoring).
   - `leak_remaining_kcal`: pinned windows budget more of a nutrient than the
     day still allows after the ledger (`daily − eaten` remainder cap).
   - `leak_allergy`: ledger foods carrying a profile-banned allergen tag.
   Naturalness alone never drops here; leak reasons are code reasons and a
   hit drops without Stage B LLM votes.

4. **Stage B speech votes (k=3)** — Recommend candidates only. Prompt is the
   spoken query plus resolved food names (`format_stage_b_prompt`); no grams,
   no windows. Same JSON contract, same k=3 majority, same alarm-not-drop
   rule as Stage A. Stages are separate prompts and separate model pools
   (`STAGE_A_MODEL_IDS` vs `STAGE_B_MODEL_IDS`); they are never one prompt.

## Verdicts

Each `per_candidate[id]` entry carries structured verdicts:

```json
{
  "stage_a": {"code_gate": [...], "votes": {"<model>": {"raw", "eatable", "reason"}}, "majority": "pass|fail|undecided|none"},
  "stage_b": {"leak_scan": [...], "votes": {...}, "majority": "pass|fail|undecided|none"},
  "verdict": "pass | alarm_majority | drop_code_gate | drop_leak_scan",
  "dropped": false, "alarm": false, "anomaly": false
}
```

Top-level result keys: `dropped` (with per-row `stage` attribution),
`anomalies`, `per_candidate`.

## Guards carried over from superseded oral-gate 11a

- There is no mill mode that skips the Stage A code-gate while also having no
  voter: both `review_candidates(...)` and `make_reviewer(...)` raise
  `ValueError` unless Stage A and Stage B model pools are non-empty, and the
  gate always runs before any vote.
- This report embeds no pytest passed total.
- Freeze-blocker note for the later admission ticket (not this ticket):
  `reports/gray-zone-probe-v2.md` (chicken-piece-105 / tuna-can-75 /
  beef-piece-65) must exist before any freeze; run it against the live
  `grams_gate` path even though the mill no longer uses the old portion judge.
