# Review — ship-09 (issue 09) and ship-10 (issue 10)

Reviewer: claude (Opus), independent. Main checkout `/home/jzq/Projects/nutri-env` @ `63c1bf4`.
Review only — no code was changed, nothing merged, both worktrees left clean (`git status --porcelain` empty).

## Branch state (verified, not taken on trust)

| | branch HEAD | merge-base with main | commits under review |
|---|---|---|---|
| ship-09 | `2a6bff7` | `57434b1` | `2a6bff7` (new), `c328bd0` (prior, still unmerged) |
| ship-10 | `7892df1` | `57434b1` | `6402b45`, `7892df1` (new); 7 earlier 10-* commits still unmerged |

Both branches are ~20 commits behind main (main's whole Ticket-14 series). `git diff main..HEAD`
therefore shows main's work as deletions; every diff below uses **three-dot** `main...HEAD`.

## Axis 1 — zero drift / ground trust: PASS on both branches

`git diff --name-only main...HEAD | grep -E 'docs/adr/|data/splits/|\.sqlite|scorer\.py'` → empty on
both branches. Neither branch touched an ADR file, a frozen split, a catalog sqlite, or
`src/nutrienv/bench/scorer.py`. The judge rule (`Pass ⇔ end state == Oracle`) is untouched.
ship-10 removed no tests and weakened no assertion — the only deleted test lines are the five
`quota_ledger` key names, each replaced by an equal-or-stronger assertion.

Two ADR-consistency issues survive and are filed below as **S10-1** (blocker) and **S10-7** (minor);
neither is an ADR *edit*, both are code/ADR disagreements that need a main-agent ruling.

## Test evidence I ran myself

```
ship-09  tests/test_review_harness.py                                   17 passed
ship-09  pytest -q  (full)                                            1199 passed in 63.70s
ship-10  tests/test_generate_one_composite.py                            13 passed
ship-10  tests/test_react.py test_run_batch.py test_pipeline_composite.py
         test_composite_split.py                                         44 passed
ship-10  pytest -q  (full)                                            1217 passed in 64.28s
```

All four claimed counts reproduce exactly. The two previously failing ship-10 tests
(`test_validator_checks_composite_recommend_remainder_on_the_child`,
`test_validator_checks_composite_recommend_is_passable_on_the_child`) do pass — but see **S10-2**
for what the first one actually asserts. The ship-09 `REASON_WINDOWS_*` tests pass — but see
**S09-2** for their provenance.

---

# ship-09 — verdict: **REV**

The shape of the two-stage committee is right and the code is readable. It is held back by one
falsely-ticked carry-over checkbox, a report that misstates where its tests came from, and a net
loss of coverage on the module the ticket owns.

### S09-1 — blocker — the forbidden "skip-code-gate-and-no-voter" mode still ships, wired into two writers

`src/nutrienv/bench/pipeline/run_batch.py:70` — `pass_through_reviewer` returns the required
`{anomalies, per_candidate}` shape with **no code gate and no voter**. It is exported from
`nutrienv.bench.pipeline` and wired at `run_batch.py:215` (`write_composite_draft_sample`) and
`run_batch.py:264` (`write_tracer_sample`) — both write into `data/splits/`
(`types.py:57-58`). `--skip-gram-backresolve` also still exists end to end
(`scripts/generate_batch.py`, `run_batch.py:371`, `run_batch.py:604`).

The guard `reports/impl-09-two-stage-review.md` cites — `review_candidates` / `make_reviewer`
raising `ValueError` on empty pools (`review_harness.py:292`, `review_harness.py:413`) — only
protects a caller who already chose the real reviewer. `run_batch` accepts any callable, and the
repo itself ships and uses the empty one. Issue checkbox
"[x] There is no skip-code-gate-and-no-voter mill mode" is a cosmetic tick.

*Fix:* run `stage_a_code_gate` inside `run_batch` before `reviewer(...)`, or have `run_batch`
reject a reviewer that is not the two-stage committee; move `pass_through_reviewer` into the test
tree.

### S09-2 — major — the "WIP window tests" did not exist before this commit

`reports/impl-09-two-stage-review.md:38` claims *"WIP window tests kept verbatim (all pass as
written); added 11 tests"*. At `c328bd0`, `tests/test_review_harness.py` held exactly **one** test
and zero `REASON_WINDOWS` references:

```
$ git show c328bd0:tests/test_review_harness.py | grep -c REASON_WINDOWS   → 0
$ git show c328bd0:src/nutrienv/bench/pipeline/review_harness.py | grep -c REASON_WINDOWS → 0
$ git show 2a6bff7 -- tests/test_review_harness.py | grep -c '^+def test'  → 16
```

All 16 tests — the five window tests included — were written in `2a6bff7` alongside the code they
test. Presenting them as pre-existing WIP specification overstates the evidence. Separately,
`.scratch/exam-generation-pipeline/issues/09-review-harness-two-stage.md:13` says the work "landed
on c328bd0", which is the wrong commit.

*Fix:* correct both the report sentence and the issue Status line to name `2a6bff7`.

### S09-3 — major — 16 pre-existing tests deleted, several guarantees now uncovered

`c328bd0` replaced `tests/test_review_harness.py` wholesale. No other test file imports
`review_harness` (`grep -rln review_harness tests/` → one file). Symbols with **zero** coverage in
the entire suite now:

| symbol | ship-09 location | previously covered by |
|---|---|---|
| `ValueError` on empty stage pools | `review_harness.py:292`, `:413` | `test_review_candidates_requires_models` |
| `call_reviewer` | `review_harness.py:427` | `test_call_reviewer_posts_to_dashscope` |
| `_route` / missing `DASHSCOPE_API_KEY` | `review_harness.py:458` | `test_route_always_uses_dashscope`, `test_route_requires_dashscope_key` |
| `resolved_items`, `format_stage_a_prompt` | `review_harness.py:183`, `:212` | `test_prompt_carries_query_and_portion_facts` |
| `parse_retries` behaviour | `review_harness.py:360` | `test_empty_reply_retries_once` |
| empty-candidate result shape | `review_harness.py:345` | `test_empty_candidates_return_required_keys` |

The first row is the guarantee **S09-1** turns on, so the carry-over is now neither enforced at the
seam nor asserted anywhere.

*Fix:* re-add at minimum the empty-pool `ValueError` test and a monkeypatched `call_reviewer`
routing test.

### S09-4 — major — Stage B speech votes never run for log / evaluate / update

`review_harness.py:328` gates the Stage B vote on `task.family == "recommend"`. Stage A
deliberately hides the query (`review_harness.py:212`, prompt built at `generate_one.py:790-809`,
which prints only food + grams). Net effect: for three of four families **no voter ever sees the
spoken query**, so a leaky or nonsensical Log/Evaluate/Update query passes the committee unreviewed.

The issue text reads "Stage B k=3 votes speech (query + food names) plus a code leak scan for
leftover/allergy/remaining-kcal **on Recommend**" — "on Recommend" scopes the leak scan; the speech
vote is unqualified. The docstring at `review_harness.py:289` justifies the restriction with
"other families were already plate-voted by Stage A", which conflates a blind plate vote with a
speech vote. `tests/test_review_harness.py:377` (`test_stage_b_log_candidates_get_no_speech_vote`)
locks the narrower reading in.

*Fix:* run Stage B speech votes for every candidate that survives the leak scan; keep the leak scan
recommend-only. If the narrow reading is intended, get it ruled on and record it in the issue.

### S09-5 — minor — `_kcal_infeasible` calls any macro-free window unpassable

`review_harness.py:158-180`. With `protein_g`/`carb_g`/`fat_g` absent, `forced = reachable = 0`,
so the second branch reduces to `kcal_lo > 0` and returns `True`. Reproduced:

```
_kcal_infeasible({"kcal": (540.0, 880.0)})            → True
stage_a_code_gate(<task with that plan_windows>)      → ['windows_unpassable']
```

Live `plan_windows` always carry all six keys (`daily_windows.py:154-178`,
`realize.py:560-566`), so this is latent — but it is a **hard drop**, so a partial pin would delete
a good candidate silently. (Also: `kcal_lo > forced` at `:180` is implied by
`reachable < kcal_lo` since `reachable >= forced`.)

*Fix:* return `False` when no macro span is present.

### S09-6 — minor — duplicate `windows_out_of_bounds` reasons

`review_harness.py:143-152` appends one entry per offending key. Reproduced:
`stage_a_code_gate` → `['windows_out_of_bounds', 'windows_out_of_bounds']`. Tests use `in`, so it
is invisible today; the drop record in `review["dropped"][i]["reasons"]` is noisy.

*Fix:* append the reason once, or carry the offending keys in the string.

### S09-7 — minor — `parse_retries` never retries a parse failure

`review_harness.py:359-363` breaks as soon as the reply is non-empty, so the retry only covers an
**empty** reply. Reproduced with `parse_retries=1`: a junk-prose voter is called **1** time; an
empty-string voter is called **2** times. The constant name, the `__all__` export
`PARSE_RETRIES`, and the report's "JSON parsing" wording all imply otherwise.

*Fix:* retry when `_parse_vote` returns `None`, or rename to `empty_reply_retries`.

### S09-8 — minor — leak-scan docstring mis-cites its mapping, and the allergy scan looks at the wrong set

`review_harness.py:221-266`:
- The docstring names `generate_one._recommend_from_template / meal_slot_and_remainder`;
  `meal_slot_and_remainder` lives in `nutrienv/world/daily_windows.py:154`, not `generate_one`.
- It maps the allergy check to `realize.bind_evaluate_reasons`, but that function scans the
  **evaluated plate** (`realize.py:367-372`), while the scan here walks `s0.ledger`
  (`review_harness.py:260-265`). Scanning the ledger is defensible for Recommend, but it is not the
  mapping claimed.
- All three checks sit under `if ledger:` (`:245`). A Recommend whose *named dish* carries a banned
  allergen (the `rec-named-dish` shell at `generate_one.py:305-311` deliberately picks one) is
  never scanned, because such tasks have an empty ledger.

*Fix:* correct the docstring, and decide explicitly whether the allergy leak should also cover the
named dish / plan side.

### S09-9 — minor — the k=3 pools are 2+1, not three families

`review_harness.py:65-74`: Stage A is `qwen3.8-max`, `qwen3.8-2.4t-a95b` (both Qwen) + `glm-5.2`;
Stage B is `deepseek-v4-flash-0731`, `deepseek-v4-pro-0813` (both DeepSeek) + `kimi-k2.7-code`. All
six ids resolve in the model registry (checked), so nothing is broken — but with a ≥2 majority rule
one family alone carries the vote in either stage, against the issue's "Different model families".

*Fix:* make each k=3 pool three distinct families, or record that "different families" was meant
only across stages.

### S09-10 — minor — dead branch

`review_harness.py:338` `if entry["dropped"]:` can never be true — both paths that set it
`continue` at `:312` and `:326`.

### Verified clean on ship-09

- `reports/review-harness-two-stage.md` carries **no** pytest total — the carry-over is honoured
  for the harness report. `reports/impl-09-two-stage-review.md:88-96` does quote `17 passed` /
  `1199 passed`, but it is an implementation log, not a harness report, and it labels them
  "session evidence, not frozen harness output". Acceptable; note the 1199 is already stale against
  main.
- Window checks fire only when `oracle.plan_windows is not None` (`review_harness.py:135`) —
  asserted by `test_log_without_pinned_windows_skips_window_checks`.
- k=3 majority semantics (`review_harness.py:370-377`) match the spec: ≥2 parsed yes ⇒ pass, ≥2 no
  ⇒ fail, else undecided; fail/undecided ⇒ alarm without drop
  (`test_stage_b_majority_fail_alarms_without_dropping`, `test_stage_b_unparsed_votes_are_anomaly_with_alarm`).
  The 1-yes/1-no/1-unparsed case is not covered by any test.
- Code-gate failure really does skip the LLM (`_boom` voters at `tests/test_review_harness.py:53`
  are asserted never called).

---

# ship-10 — verdict: **REV**

The new mill code is the strongest work in either branch: `_log_then_recommend`,
`_log_then_evaluate_fit` and `_update_then_recommend` are ADR-0014-correct, each is proved
end-to-end through `NutriEnv` + `Scorer`, and the S4 window-leak hole is a genuine find with a real
test. It is held back by one unresolved ADR conflict, a validator change that does not do what the
commit message says, and two claimed fixes with no regression test.

### S10-1 — blocker — two contradictory composite `plan_windows` conventions now coexist, and the freeze path uses the one that contradicts accepted ADR 0014

ADR 0014 (**Status: accepted**) states `plan_windows = meal-slot ∩ remainder`.

- The new mill follows it: `generate_one.py:358` and `generate_one.py:474` pin
  `plan_windows_for_meal(...)`.
- The older composite constructor does not: `resolver.py:326` pins `_remainder_after(...)`
  (`resolver.py:331-337`) — the **pure daily remainder**, no meal-slot share. This is the path
  `write_composite_sample` / `write_composite_draft_sample` use to write
  `data/splits/pipeline-composite-draft.json` (`types.py:58`).
- `run_batch.py:314-322` (`_composite_draft_issues`) enforces the *pure remainder* convention.

The two admission gates therefore disagree about the same item. Reproduced against the mill's own
valid log+recommend task (the one `tests/test_generate_one_composite.py:114` proves passes the
Scorer):

```
validate_draft(task)          → []
_composite_draft_issues(task) → ['composite plan_windows kcal != remainder (1609.94, 1609.94)',
                                 'composite plan_windows protein_g != remainder (45.33, 45.33)',
                                 'composite plan_windows carb_g != remainder (205.05, 205.05)',
                                 'composite plan_windows fat_g != remainder (70.32, 70.32)',
                                 'composite plan_windows fiber_g != remainder (24.78, 24.78)']
rec_oracle.plan_windows['kcal'] = (544.6, 726.14)      # meal-slot ∩ remainder, ADR 0014
pure daily remainder    ['kcal'] = (1609.94, 1609.94)  # what run_batch demands
```

Same result for the update+recommend pair. So (a) the moment the `generate_one` mill feeds
`run_batch`, every composite is dropped with `draft_fail=True`, and (b) today's composite freeze
path writes windows that contradict an accepted ADR.

The text conflict is real and needs a ruling, not an implementer's judgement call: ADR 0013
(**Status: proposed**) says the composite recommend child pins "S0 ⊕ lunch 之后 的 remainder
(ADR 0007)"; ADR 0016 (accepted) supersedes 0013's pair list but not that sentence; ADR 0014
(accepted) is the later authority and says meal-slot ∩ remainder. ship-10 correctly did not edit
any ADR.

*Fix:* rule on ADR 0013's `plan_windows` sentence (I read ADR 0014 as controlling), then move
`resolver._attach_recommend` and `run_batch._composite_draft_issues` onto `plan_windows_for_meal`,
and record the override in ADR 0013.

### S10-2 — major — the new composite remainder check cannot fire on anything the mill produces, and is not the mirror the commit claims

`validator.py:761` gates the remainder check on `task.persona == "leftover"`.

`persona == "leftover"` is set only by the legacy row realization at `realize.py:275`. The 20-person
roster is `Counter({'everyday': 11, 'gym': 5, 'cut': 4})` (`pipeline/roster.py`), so no
`generate_one` composite can ever carry it; `resolver._attach_recommend` copies
`candidate.persona`, which for both composite writers is `"everyday"`. The check is dead for the
deliverable it was added for. It is also strictly weaker than
`run_batch._composite_draft_issues`, which the commit message and
`reports/impl-10-composite-closeout.md:14` say it "mirrors" — it does not.

The test that certifies it, `tests/test_generate_one_composite.py:338-343`, takes a **valid**
everyday composite and relabels `persona="leftover"`, then asserts an issue appears. It never
constructs a wrong remainder, so it asserts that the gate reacts to the label, not that it catches a
defect. (By contrast `test_validator_checks_composite_recommend_is_passable_on_the_child` at
`:346` builds a genuinely impossible window — that one is a real assertion.)

*Fix:* once S10-1 is ruled, derive the expected windows from the same helper the mill uses and drop
the persona gate; rewrite the test to mutate `plan_windows`, not `persona`.

### S10-3 — major — the P3 freezer fixes have zero test coverage

Verified by reverting `src/nutrienv/bench/pipeline/freezer.py` to `6402b45` and running the full
suite in the ship-10 worktree: **1217 passed** — identical to HEAD. So none of

- `_oracle_payload` dropping `"profile": "s0"` for containers (`freezer.py:119-127`),
- `_ledger_payload` (`freezer.py:173-186`),
- the trailing `if "ledger" not in payload` (`freezer.py:168-169`)

is exercised by any test. I confirmed by probe that the fixes do work for log+recommend and
update+recommend (`freeze_tasks` → `load_split` → `loaded.oracle == task.oracle` is `True`,
`validate_draft(loaded) == []`, parent payload keys reduce to `['sub_oracles']`), but a claimed
round-trip fix with no regression test can silently regress on the next freezer edit.

*Fix:* add one freeze/load round-trip test per legal pair asserting `loaded.oracle == task.oracle`
and `validate_draft(loaded) == []`.

### S10-4 — major — the "log+evaluate-fit is constructible" evidence rests on an item that cannot be frozen

`tests/test_generate_one_composite.py:256-292` builds the pair from "three cups of rice" = 474 g.
`QUANTITY_MULTIPLES = (0.5, 1.0, 1.5, 2.0)` (`types.py:48`), so `freeze_tasks` refuses it:

```
ValueError: oracle grams gate failed:
one-comp-0000: oracle ledger_tail[0] grams 474.0 for white_rice do not match portion table
one-comp-0000: oracle last_plan[0] grams 474.0 ...
one-comp-0000: oracle evaluated_plan[0] grams 474.0 ...
```

while the same task passes `validate_draft(task) == []` (asserted at `:292`). Admission gate and
freezer disagree about the same item. Every table-legal alternative I tried against the committed
fixture (`a cup`, `two cups`, and three multi-food plates) is rejected `not_fit`, so I could not
reproduce the `log+evaluate: oracle_identical=True` line in
`reports/impl-10-composite-closeout.md:104` from the repo as committed. That line is unverifiable
here, and the "[x] Other legal pairs … are constructible" checkbox is backed by an item that cannot
enter a frozen split.

*Fix:* give the log+evaluate fixture a table-legal plate that still yields `last_verdict == "accept"`,
and assert `freeze_tasks` + `load_split` on it.

### S10-5 — minor — the composite unpassable check judges against S0's profile, not the child's

`validator.py:773-774` uses `task.s0.profile.windows` and `task.s0.profile.allergies`. The
single-family path at `validator.py:276-283` correctly resolves `_judged_profile(task)`. For
update+recommend the recommend child carries the **post-update** profile
(`generate_one.py:480`); `test_update_then_recommend_is_constructible` asserts
`rec_oracle.profile.allergies` contains `shellfish` while `task.s0.profile.allergies` is `()`. The
Scorer judges against the child profile; the validator does not. No live counterexample in the
fixture catalog (both allergy sets still yield a fitting plan), so this is latent.

*Fix:* use `child.profile or task.s0.profile` for both windows and allergies, mirroring
`_judged_profile`.

### S10-6 — minor — `COMPOSITE_ADMISSION_SLOTS` is a label, not a budget

`run_batch.py:238-239` reports `exam_quota` and `composite_admission_slots`, but nothing checks
`composite_accepted <= 36` or `single_family + composite <= 240`. The only assertion is
`assert COMPOSITE_ADMISSION_SLOTS == 36` (`tests/test_generate_one_composite.py:392`) — a constant
echoing itself. The checkbox "[x] Composite counts toward the 36 admission slots, not extra people"
is backed by the roster half only (`ROSTER` membership is properly asserted).

*Fix:* enforce the ceiling in `quota_ledger` or at the freeze gate, and assert it.

### S10-7 — minor — ADR 0012 still asserts the superseded "extra quota" decision

`docs/adr/0012-composite-tasks-extra-quota.md` says composites "额外占用配额，在基础 240 题之外另加".
ADR 0016 (accepted) says "not 240+extra" and puts composite's 36 inside the 240, but names only ADR
0009 and 0013 as superseded. The code change (`types.py:51-52`,
`COMPOSITE_EXTRA_QUOTA = 24 → COMPOSITE_ADMISSION_SLOTS = 36`) follows ADR 0016 and is **correct**.
Flagging so the main agent can add the supersede note to 0012 — ship-10 rightly left ADR files alone.

### S10-8 — minor — log+evaluate composites are tagged `("multi_item_log",)`

`generate_one.py:424-428`. Documented in the report as a closed-vocabulary workaround
(`evaluate_fit` is not in `bench/situations.py`), but it makes a log+evaluate composite
indistinguishable from a plain multi-item log for any downstream slicing by situation — including
main's `quality_gates` floors.

### Verified clean on ship-10

- `_validate_composite` does **not** reject valid non-leftover composites: `validate_draft` returns
  `[]` for the mill's log+recommend, log+evaluate and update+recommend outputs, before and after a
  freeze round-trip.
- The composite window-leak widening (`validator.py:232-236`) is a real fix with a real test.
  `_WINDOW_LEAK` (`validator.py:31`) only matches `kcal|protein_g|carb_g|fat_g` followed by a digit,
  so widening it to all composites cannot false-positive on ordinary "two eggs" phrasing.
- `quota_ledger` key renames are consistent across `run_batch.py`, `types.py`,
  `test_pipeline_composite.py` and `test_composite_split.py`; no orphaned key remains in code.
- `react.py:50-56` teaches all three composite chains, with the `<= 400` word budget assertion kept.
  Editing `_SYSTEM` in place is established practice here (commits `41caca7`, `509cbb3`, `6b0d841`,
  `c2d3527`, `d92f51c` all did the same) and hard discipline 4 requires the sync, so this is **not**
  a finding — but note `react_manual`'s docstring calls the manual "frozen", and the archived gold
  splits were graded against older text, so cross-version result comparisons drift.

---

## Merge notes (both branches, for whoever integrates)

1. Both branches fork at `57434b1`; main has since landed the full Ticket-14 series
   (`quality_gates.py`, `test_quality_gates.py`, and edits to `realize.py`, `split.py`,
   `validator.py`). Neither branch has seen any of it. Rebase before merging, not after.
2. **ship-10's S4 fix needs mirroring into main.** `src/nutrienv/bench/quality_gates.py:81-83`
   (`window_leaks`) filters `task.family == "recommend"` — the exact blind spot ship-10 fixed in
   `validate_draft`. Composites carry family `log`/`update`, so main's split-level leak gate still
   lets a composite window leak through. Same for `leftover_recommends` (`:183`) and
   `recommend_coverage` (`:113`): composites will not count toward the ADR 0016 situation floors.
3. ship-09 rewrote `review_harness.py` wholesale while main independently grew `quality_gates.py`;
   no file overlap, but the two now hold overlapping "leak scan" logic in different modules. Decide
   which one owns the recommend leak rules before both land.

## Blocker list

1. **S09-1** — `pass_through_reviewer` (`run_batch.py:70`) still provides a
   no-code-gate-and-no-voter mill mode and is wired into two `data/splits/` writers; issue 09's
   carry-over checkbox is falsely ticked.
2. **S10-1** — two contradictory composite `plan_windows` conventions coexist;
   `resolver.py:326` + `run_batch.py:314-322` contradict accepted ADR 0014 and would reject every
   composite the issue-10 mill builds. Needs a main-agent ruling on ADR 0013's `plan_windows`
   sentence before either branch freezes composites.

---

# Re-review after fix rounds (claude opus)

Second pass, 2026-08-22. ship-09 `bce1a0f`, ship-10 `ecc3389` + `b374c3f`. Review only; no code
changed, nothing merged, both worktrees left clean.

**ADR ruling respected:** ADR 0014 (accepted) controls composite Recommend `plan_windows`
(meal-slot ∩ remainder). Code judged against ADR 0014, not ADR 0013's superseded sentence. ADR
files remain untouched on both branches.

## Verdicts

| branch | HEAD | verdict | reason |
|---|---|---|---|
| **ship-09** | `bce1a0f` | **ACC** | blocker S09-1 resolved and proven in the exact worst case; S09-2…S09-10 all resolved with real tests. One new follow-up finding (N09-1), not a merge blocker. |
| **ship-10** | `b374c3f` | **REV** | blocker S10-1 and every finding S10-2…S10-8 resolved and verified. Held on one new finding (N10-1): the fix round removed the last code enforcement of ADR 0014's six-nutrient contract. Needs a main-agent ruling or a small fixture change — nothing else outstanding. |

## Axis 1 re-check

`git diff --name-only main...HEAD | grep -E 'docs/adr/|data/splits/|\.sqlite|scorer\.py'` → empty
on both branches. Judge rule untouched. ship-10's fix round removed no test and weakened no
assertion — the only deleted test lines are the three superseded fixtures (the 474 g log+evaluate
plate and the `persona="leftover"` relabel), each replaced by a strictly stronger one.

## Test evidence I ran myself

```
ship-09  tests/test_review_harness.py                              29 passed
ship-09  pytest -q (full)                                        1211 passed in 47.28s
ship-10  tests/test_generate_one_composite.py                      15 passed
ship-10  tests/test_generate_one_composite.py + test_run_batch.py   28 passed
ship-10  pytest -q (full)                                        1220 passed in 47.42s
```

All four claimed counts reproduce exactly.

## ship-09 — finding-by-finding

| # | sev | status | evidence |
|---|---|---|---|
| S09-1 | blocker | **resolved** | `run_batch.py:83` `_code_gate` applies `stage_a_code_gate` structurally at `run_batch.py:150`, before `reviewer(...)`. Proven in the exact worst case the carry-over named — `skip_gram_backresolve=True` **plus** `pass_through_reviewer` (no voter) → `accepted=0, rejected=['code_gate']`. Both guards can no longer be empty. Regression test `test_run_batch_structural_code_gate_drops_off_table_grams`. Neither writer regressed: `write_tracer_sample` accepted=3 rejected=[], `write_composite_sample` accepted=2 rejected=[]. |
| S09-2 | major | **resolved** | `reports/impl-09-two-stage-review.md:36-40` now states the tests were written in `2a6bff7`, not kept from WIP. Issue Status line now names `2a6bff7`. |
| S09-3 | major | **resolved** | Six restored tests: `test_review_candidates_requires_models`, `test_make_reviewer_rejects_empty_pools`, `test_empty_candidates_return_required_keys`, `test_resolved_items_and_stage_a_prompt_carry_portion_facts`, `test_route_always_uses_dashscope` / `test_route_requires_dashscope_key`, `test_call_reviewer_posts_to_dashscope` (monkeypatched `post_chat_completion`, no network). |
| S09-4 | major | **resolved** | `review_candidates` (`review_harness.py:353`) votes Stage B for every candidate surviving the leak scan; leak scan still recommend-only (`:232`). `test_stage_b_log_candidates_get_no_speech_vote` → `test_stage_b_speech_votes_cover_log_candidates`, asserting the log query is hidden from Stage A and visible to Stage B. |
| S09-5 | minor | **resolved** | `_kcal_infeasible` returns `False` with no macro span (`review_harness.py:172-177`); redundant `kcal_lo > forced` conjunct dropped. `test_macro_free_window_is_not_unpassable`. |
| S09-6 | minor | **resolved** | Early `return [REASON_WINDOWS_OUT_OF_BOUNDS]` (`review_harness.py:154`). `test_out_of_bounds_reason_appended_once` asserts exact list equality on a two-offending-key window. |
| S09-7 | minor | **resolved** | `_run_stage_vote` loops until `_parse_vote` returns a vote (`review_harness.py:382-387`). `test_parse_failure_is_retried_then_parsed` pins 12 calls for 6 voter slots. |
| S09-8 | minor | **resolved** | Docstring now cites `nutrienv.world.daily_windows.meal_slot_and_remainder` and states the `bind_evaluate_reasons` mapping precisely. Allergy scan moved out of `if ledger:` and now also walks `oracle.last_plan`, `oracle.evaluated_plan`, `s0.last_plan` (`review_harness.py:275-289`). `test_named_dish_allergen_leak_with_empty_ledger`. |
| S09-9 | minor | **resolved** | Stage A = qwen / deepseek / glm; Stage B = kimi / deepseek / qwen — three distinct families each, so no vendor carries a ≥2 majority alone. All six ids resolve in the registry. |
| S09-10 | minor | **resolved** | Dead `if entry["dropped"]:` branch removed. |

### N09-1 — new, major (follow-up, not a merge blocker) — the structural gate does not window-gate composites

`_window_reasons` (`review_harness.py:139`) reads only `task.oracle.plan_windows`. A composite's
parent oracle is a container with `plan_windows = None`, so every window reason is skipped for
composites, while `_oracle_pairs` (`:470`) already walks `sub_oracles` for the grams check.
Measured:

```
single recommend, plan_windows {'kcal': (900, 200)}  -> ['windows_empty']
the SAME windows inside a composite child            -> []          (parent plan_windows = None)
```

Latent before `bce1a0f` (composites were reviewed by `pass_through_reviewer`); now that the gate
is structural in `run_batch` and runs on every accepted task, the asymmetry is a live hole in the
guard this fix round introduced — and composites are exactly what ship-10 ships.

*Suggested fix:* have `_window_reasons` iterate `oracle.sub_oracles` when present, mirroring
`_oracle_pairs`, and add a composite-child window test.

### N09-2 — new, minor

- `--skip-gram-backresolve` is neutralized, not removed (`scripts/generate_batch.py:120`,
  `run_batch.py:392`). The structural gate makes it harmless — but no committed test pins the
  `skip_gram_backresolve=True` + `pass_through_reviewer` combination (I verified it by probe; the
  committed test uses the default flag). One line in
  `test_run_batch_structural_code_gate_drops_off_table_grams` would lock it in.
- The module docstring says "family sets differ between stages so no single vendor carries both
  votes" (`review_harness.py:14-15`); DeepSeek and Qwen appear in both stages. The report body is
  accurate about this ("cross-stage family reuse is unavoidable with six registry ids") — only the
  docstring sentence overstates.

## ship-10 — finding-by-finding

| # | sev | status | evidence |
|---|---|---|---|
| S10-1 | blocker | **resolved** (by consolidation) | `resolver._attach_recommend` (`resolver.py:320-327`) now pins `plan_windows_for_meal` via the new `_rec_occasion(tail)`. `run_batch._composite_draft_issues` was **deleted** with its call site rather than ported — verified `hasattr(run_batch, "_composite_draft_issues") is False`. One gate (`validate_draft` → `_validate_composite`), one convention. Verified end to end: all three mill pairs return `validate_draft == []`, and the resolver path (`write_composite_sample`) gives accepted=2, rejected=[], `validate_draft == []`, freeze round-trip `oracle` identical. The two constructors and the single gate now agree on ADR 0014. |
| S10-2 | major | **resolved** | `persona == "leftover"` gate gone; `_validate_composite` (`validator.py:766-773`) recomputes expected windows with the same `plan_windows_for_meal` helper the mill uses. Test rewritten to shift the child's kcal window by +50 on a valid everyday composite: `CORRUPTED kcal +50 → ['composite plan_windows kcal != expected meal windows (819.56, 1092.75)']`, clean task → `[]`. It now asserts a real defect. |
| S10-3 | major | **resolved, proven to bite** | Three round-trip tests, one per legal pair, each asserting `loaded.oracle == task.oracle` and `validate_draft(loaded) == []`. Reverting `freezer.py` to `6402b45` now fails all three (`3 failed, 12 passed`) — the same revert previously left 1217 passing. |
| S10-4 | major | **resolved** | Fixture is now "two cups of rice and a cup of milk" = 316 g + 244 g, both `QUANTITY_MULTIPLES`-legal. The test freezes and loads the item inside `test_log_then_evaluate_fit_is_constructible`; no `ValueError` from the grams gate. |
| S10-5 | minor | **resolved** | `profile = child.profile or task.s0.profile` (`validator.py:762`) drives both the expected windows and `fitting_plan`'s allergy set, mirroring `_judged_profile`. |
| S10-6 | minor | **resolved** | `quota_ledger` raises on `composite_accepted > 36` and on `total > 240` (`run_batch.py:236-245`). `test_quota_ledger_enforces_adr_0016_ceilings` covers the legal 36+204 case and both breaches. |
| S10-7 | minor | **documented, as expected** | `reports/impl-10-composite-closeout.md:214-220` hands ADR 0012's supersede note to the main agent, folded together with the ADR 0013 `plan_windows` ruling. No ADR file touched. Correct handling. |
| S10-8 | minor | **documented, acceptable** | `reports/impl-10-composite-closeout.md:222-234` states the tag workaround, why `evaluate_fit` cannot be added without weakening `test_realize_covers_every_situation`, the downstream-slicing risk, and that scoring is unaffected because the shape lives in the child oracle's accept verdict. Correctly declined to weaken a pre-existing test. |

### N10-1 — new, major — the ADR 0014 six-nutrient contract is now enforced nowhere

`ecc3389` changed `meal_slot_and_remainder` (`daily_windows.py:165`) and `plan_windows_for_meal`
(`daily_windows.py:201`) from iterating `SIX_WINDOW_KEYS` to iterating the caller's `daily` dict.
`SIX_WINDOW_KEYS` is now referenced in no logic — only in `__all__` re-exports.

This is load-bearing for the S10-1 fix: `resolver.py:301` builds composite materials with
`GOLD_WINDOWS = {"kcal": (1800.0, 2200.0), "protein_g": (90.0, 140.0)}` — two keys — so under the
old six-key loop `_attach_recommend` would `KeyError`.

Measured consequence:

```
plan_windows_for_meal(GOLD_WINDOWS, {}, "dinner")
  before: KeyError('carb_g')          # loud
  after : {'kcal': (540.0, 880.0), 'protein_g': (0.0, 140.0)}   # silent, 2 of 6

write_composite_sample -> rec child plan_windows =
  {'kcal': (540.0, 880.0), 'protein_g': (0.0, 82.85)}
```

ADR 0014 (accepted): "Recommend and Evaluate Pass on whether a meal's **six** catalog nutrients
(`kcal`, `protein_g`, `carb_g`, `fat_g`, `fiber_g`, `sodium_mg`) fall in judged intervals." The
recommend leg of a resolver-built composite is now judged on kcal + protein only; a plan that
blows the fat, fiber, or sodium ceiling Passes.

Two things keep this from being a blocker: the resolver's composites were **already** 2-key before
this round (the deleted `_remainder_after` also iterated `s0.profile.windows.items()`), so no
frozen output changed; and the implementer disclosed the change in
`reports/impl-10-composite-closeout.md:158-162`. What is new is that a caller with a partial
profile used to fail loudly and now degrades silently, across all eight call sites — including
`realize.realize_evaluate` (`realize.py:427`) and the whole `generate_one` mill.

*Suggested fix (small, either one):*
- give the resolver's composite material a six-key profile (roster person or
  `derive_profile_windows`, as the mill does) and restore the `SIX_WINDOW_KEYS` loop; or
- keep the six-key loop as the default and make the relaxation an explicit named argument, so a
  2-key legacy fixture is a deliberate opt-in rather than a silent widening.

This is the only item holding ship-10 at REV. It is the same class of question the main agent
already ruled on for S10-1, so it may simply need a ruling rather than code.

### N10-2 — new, minor — `_recommend_occasion` fails silently, and the two occasion helpers disagree on the fallback

`validator._recommend_occasion` (`validator.py:783`) returns `None` when neither the tail stamp nor
a spoken "for &lt;meal&gt;" phrase resolves, and `_validate_composite` then **skips the whole
plan_windows equality check**, keeping only passability. Across the eight committed recommend
shells, four produce no occasion signal without a tail:

```
OK   rec-occasion     "What's for dinner?"                        -> dinner
NONE rec-occasion-eat 'What should I eat?'                        -> None
OK   rec-dinner / rec-breakfast / rec-lunch                       -> dinner/breakfast/lunch
NONE rec-snack        'I need a snack.'                           -> None
NONE rec-post-gym     'Just finished lifting — what should I eat?'-> None
NONE rec-named-dish   'Thinking of creamy pasta tonight — …'      -> None
```

Latent today: `generate_one` rejects `occasion="snack"` upstream (`generate_one.py:169`,
`ValueError: unknown occasion 'snack'`), and the three occasions that do reach
`_update_then_recommend` all map to shells that resolve. But
`_RECOMMEND_SHELLS_BY_OCCASION` already carries a `"snack"` entry, so the moment snack is enabled
the remainder gate goes quiet with no signal — the same fail-silent shape as the original S10-2.

Separately, `resolver._rec_occasion` (`resolver.py:346`) has no `None` branch: an unrecognised
stamp silently defaults to `"dinner"`, while the validator would fall through to the query regex
and may return a different meal or `None`. Both agree on today's fixtures (`today-lunch` → dinner
on each side), but `"now"` — the stamp `react.py` documents for `log_meal` without `eaten_at` —
resolves to `dinner` in the resolver and to the query word in the validator.

*Suggested fix:* make an unresolvable occasion an explicit issue rather than a skip, and share one
occasion helper between `resolver` and `validator`.

## Remaining blockers

None on ship-09. None on ship-10 in the original S10-1…S10-8 set; ship-10's REV rests solely on
**N10-1**, which needs a main-agent ruling on ADR 0014's six-nutrient contract or a small fixture
change.

---

# Final re-review (claude opus)

Third pass, 2026-08-22. ship-09 `432e2ac`, ship-10 `6052a36`. Review only; no code changed,
nothing merged, both worktrees left clean.

## Verdicts

| branch | HEAD | verdict | note |
|---|---|---|---|
| **ship-09** | `432e2ac` | **ACC** | N09-1 and N09-2 resolved and reproduced. The round also caught and fixed a false positive that round 1 had introduced into `_kcal_infeasible`. One new cross-branch finding, **N09-3**, does not affect ship-09 alone but must be fixed before the two branches share a trunk. |
| **ship-10** | `6052a36` | **ACC** | N10-1 and N10-2 resolved, both proven load-bearing by revert-bite tests. S10-1 consolidation re-verified after the `daily_windows` change. No new findings. |

## Axis 1 re-check

`git diff --name-only main...HEAD | grep -E 'docs/adr/|data/splits/|\.sqlite|scorer\.py'` → empty on
both branches. Judge rule untouched. No pre-existing test weakened: ship-09's only deleted test
lines are one import line and one test signature, both replaced by wider versions (the signature
became `@pytest.mark.parametrize`); ship-10's second round deletes **zero** test lines — pure
additions.

## Test evidence I ran myself

```
ship-09  tests/test_review_harness.py + tests/test_run_batch.py        43 passed
ship-09  pytest -q (full)                                            1213 passed in 45.46s
ship-10  test_generate_one_composite + test_run_batch
         + test_pipeline_composite                                     38 passed
ship-10  pytest -q (full)                                            1224 passed in 45.63s
```

Both claimed counts reproduce exactly.

## ship-09 — N-finding status

| # | status | evidence |
|---|---|---|
| N09-1 | **resolved** | `_window_reasons` (`review_harness.py:139`) now iterates `_window_oracles(task)` (`:157`), mirroring `_oracle_pairs`, and dedupes reasons across children. My earlier measurement reproduced exactly: single recommend with `{'kcal': (900, 200)}` → `['windows_empty']`; the **same windows inside a composite child** → now also `['windows_empty']` (was `[]`), with the parent container still pinning `None`. Test `test_composite_child_windows_are_gated`. |
| N09-2 | **resolved** | `test_run_batch_structural_code_gate_drops_off_table_grams` is parametrized over `skip_gram_backresolve` `[False, True]` against the no-voter `pass_through_reviewer`; both assert `accepted == []` / `rejected == ["code_gate"]`. The docstring no longer claims the family sets differ between stages — it now reads "cross-stage family reuse exists; no single vendor carries a stage's majority alone" (`review_harness.py:14-15`), which matches the pools. |

### Round-1 regression caught by the implementer

Wiring N09-1 exposed a false positive that `bce1a0f` had introduced into `_kcal_infeasible`:
treating an absent macro span as zero rather than unconstrained. Verified by checking out the
round-1 file:

```
bce1a0f : _kcal_infeasible({'kcal': (540,880), 'protein_g': (0,82.85)}) -> True   # false positive
432e2ac : same input                                                     -> False
```

That two-key shape is exactly what composite recommend children pinned at the time, so the
structural gate would have started dropping them. Current semantics verified across four cases:
kcal-only → False; kcal+protein → False; all macros genuinely unreachable → True; macro floors
exceeding the kcal ceiling → True. The check still bites where it should.

### N09-3 — new, major — merge-time blocker: the window gate has no float tolerance and bounds every child against S0

`_single_window_reasons` (`review_harness.py:166`) compares `float(hi) > daily_hi` with **no
epsilon**, while `_kcal_infeasible` in the same module uses `1e-6` throughout. `plan_windows_for_meal`
sets the non-kcal meal ceiling to `round(daily_hi, 2)` (`daily_windows.py:176`) while
`Profile.windows` keeps full precision, so a legitimately-constructed child ceiling sits a few
thousandths above the profile value and trips the gate.

Measured by exporting ship-10's composite windows and feeding them to ship-09's real
`stage_a_code_gate`:

```
mill log+recommend     -> []
mill update+recommend  -> ['windows_out_of_bounds']    fiber_g child hi 38.25 vs daily hi 38.24625
resolver composite     -> []
```

Swept across the roster on ship-10: **16 of 39 constructible composites** are affected — every
update+recommend pair, for `roster-ada`, `ben`, `drew`, `eve`, `fay`, `gus`, `ina`, `jay` and more,
on `protein_g` / `carb_g` / `fat_g` / `fiber_g`. Update+recommend composites carry an empty ledger,
so the remainder never caps those macros and the rounded slot ceiling is the binding value.

Neither branch shows this alone: ship-09 has no update+recommend constructor, and ship-10 has no
structural gate. It bites the moment both land, and it fails **silently** — the items surface as
ordinary `code_gate` rejections, so the exam would quietly lose its whole update+recommend slice.

A second, smaller issue sits in the same three lines: `_single_window_reasons` reads
`task.s0.profile.windows` for every child, so a child carrying a post-update profile is bounded by
the pre-update daily ceiling. ship-10 already fixed this class in its own gate (S10-5,
`validator.py:762` uses `child.profile or task.s0.profile`); ship-09's gate has not.

*Suggested fix (two lines):* compare with the module's existing tolerance
(`float(hi) > daily_hi + 1e-6`, and likewise for the `lo` comparisons), and resolve the bound from
`oracle.profile or task.s0.profile` so post-update children are judged against their own windows.
Add a composite-child regression case built from a real `plan_windows_for_meal` output rather than
hand-written round numbers — the hand-written fixtures are what let this through.

## ship-10 — N-finding status

| # | status | evidence |
|---|---|---|
| N10-1 | **resolved** | `SIX_WINDOW_KEYS` is back in logic at `daily_windows.py:168` and `:201`, with the comment "A caller with a partial window dict fails loudly here instead of silently widening the judged keys". The resolver no longer feeds the two-key legacy fixture: `_composite_windows()` (`resolver.py:365`) returns `profile_for(ROSTER[0]).windows` — the same roster-derived source the mill uses. Measured: `write_composite_sample` rec child `plan_windows` now carries **all six** keys (`carb_g, fat_g, fiber_g, kcal, protein_g, sodium_mg`) where it carried two, `validate_draft == []`, freeze round-trip `oracle` identical. |
| N10-2 | **resolved** | New shared module `src/nutrienv/bench/occasions.py`; both sides import from it (`validator.recommend_occasion.__module__ == 'nutrienv.bench.occasions'`, `resolver.occasion_from_stamp.__module__` likewise), and the resolver's private `_rec_occasion` — the one that silently defaulted to `"dinner"` — is deleted. Unresolvable is now loud on both sides: the resolver raises `ValueError("composite recommend occasion unresolved")` (`resolver.py:334`), and the validator emits an issue instead of skipping the equality check (`validator.py:766-768`). Verified live: a tail stamped `"now"` with a query carrying no meal word → `['composite recommend occasion unresolved']`. `occasion_from_stamp("now")` → `None` on both sides, where the resolver previously answered `dinner`. |

### Both fixes proven load-bearing

Revert-bite tests, each restored afterwards:

```
revert daily_windows loops to `for key in daily:`
  -> FAILED tests/test_pipeline_composite.py::test_partial_daily_windows_fail_loudly
     (DID NOT RAISE KeyError)                                       1 failed, 33 passed

revert resolver composite profile to dict(GOLD_WINDOWS)
  -> KeyError at daily_windows.py:169; 4 failed, 13 passed, including
     test_composite_recommend_child_judges_all_six_nutrients
```

The two new tests cover complementary halves — one pins the helper contract, one pins the resolver
fixture — and each bites for its own half. `test_composite_recommend_child_judges_all_six_nutrients`
asserts `set(rec.plan_windows) == set(SIX_WINDOW_KEYS)` both fresh and after `load_split`, so the
six-key guarantee is checked through the freeze boundary.

### S10-1 consolidation re-verified after the `daily_windows` change

The N10-1 fix touched a helper the whole mill depends on, so I re-ran the three legal pairs
end to end:

```
log+recommend    : validate_draft=[]  round-trip identical=True  child window keys=6
log+evaluate-fit : validate_draft=[]  round-trip identical=True  child window keys=6
update+recommend : validate_draft=[]  round-trip identical=True  child window keys=6
corrupted kcal +50 -> ['composite plan_windows kcal != expected meal windows (544.6, 726.14)']
```

One gate, one convention, still catching real defects. `_composite_draft_issues` remains deleted.

### Observations, not findings

`synthetic_expander` now builds the composite tracer plate from the single lightest pool food
(`expander.py:155-170`) instead of up to two foods, because six-key windows leave a finite daily
budget that a heavy tracer plate exhausts. The composite tracer tail is now one row where it was
two; the log tracer is unchanged at two. This is a synthetic tracer fixture, not exam data, and the
rationale is documented in the code — but a composite tracer tagged `("multi_item_log",)` now
covers a one-item log.

## Remaining blockers

- **ship-09 and ship-10 are each independently ACC.** Every finding raised in the two earlier
  passes — S09-1…S09-10, S10-1…S10-8, N09-1, N09-2, N10-1, N10-2 — is resolved with code and test
  evidence I reproduced.
- **One merge-time blocker remains: N09-3**, owned by ship-09 (`review_harness.py:166`). It is
  invisible on either branch alone and silently drops 16 of 39 composites — every update+recommend
  pair — once both are on the same trunk. Fix it before or at the merge, not after: the failure
  mode is an ordinary-looking `code_gate` rejection, so nothing will flag the missing slice.

---

# Merge preflight (claude opus)

Scope: the N09-3 fix only. ship-09 `c44012f`; ship-10 unchanged at `6052a36` (its ACC from the
final re-review stands). Review only; nothing merged, both worktrees clean.

## N09-3 — **resolved**

`_single_window_reasons` (`review_harness.py:169`) now takes the child `oracle` and resolves
`profile = oracle.profile or task.s0.profile`, so a post-update child is judged against its own
daily windows. The bound became `daily_hi = max(float(bounds[1]), round(float(bounds[1]), 2))` and
all three comparisons carry the new `_WINDOW_TOL = 1e-6`. Taking the coarser of the exact and the
2-decimal-rendered ceiling is the right shape: it absorbs `plan_windows_for_meal`'s round-**up**
without loosening the bound when rounding goes the other way.

`c44012f` touches `review_harness.py`, `tests/test_review_harness.py`, and the impl report only —
no `docs/adr/`, `data/splits/`, `*.sqlite`, or `scorer.py`. Zero deleted test lines: three tests
added, none changed.

### Reproduction 1 — the exact case I measured as failing now passes

ship-10's real composite windows, exported and fed to ship-09's fixed `stage_a_code_gate`:

```
mill log+recommend     -> []
mill update+recommend  -> []        (was ['windows_out_of_bounds'])
                          child fiber_g hi 38.25 vs exact daily hi 38.24625
resolver composite     -> []
```

Full roster sweep, the same measurement that produced the 16/39 figure:

```
total ship-10 composites gated : 39
dropped by the fixed gate      : 0        (was 16 — every update+recommend pair)
```

### Reproduction 2 — a genuinely out-of-bounds window still fails

```
daily fiber_g hi = 38.24625
child fiber_g (0.0, 39.00)  -> ['windows_out_of_bounds']
child fiber_g (0.0, 38.26)  -> ['windows_out_of_bounds']   # one cent past the rounded ceiling
```

The tolerance is tight, not a blanket loosening: one cent over the rounded ceiling still trips.
Committed regression tests cover all three directions —
`test_composite_child_rounded_slot_ceiling_passes_gate` (built from real `plan_windows_for_meal`
output against a full-precision profile, not hand-written round numbers),
`test_composite_child_judged_against_its_own_profile`, and
`test_composite_child_genuinely_out_of_bounds_still_flags`.

### Test evidence

```
ship-09  tests/test_review_harness.py    34 passed
ship-09  pytest -q (full)              1216 passed in 50.54s
```

## Sign-off

**Both branches are cleared for merge.** ship-09 `c44012f` and ship-10 `6052a36` are each ACC, and
the one cross-branch defect that only appeared when they were combined — N09-3 — is fixed and
re-measured to zero. Every finding raised across the four passes (S09-1…S09-10, S10-1…S10-8,
N09-1…N09-3, N10-1, N10-2) is resolved with code and test evidence I reproduced myself.

Two carry-forward items for the main agent, neither blocking:

1. **ADR supersede notes** (S10-7, and the ADR 0013 `plan_windows` ruling): ADR 0012 still states
   composites take extra quota beyond 240, and ADR 0013 still carries the superseded pure-remainder
   sentence. Implementers correctly left ADR files untouched; the notes are a main-agent edit.
2. **Rebase before merging** — both branches fork at `57434b1` and have not seen main's Ticket-14
   series. In particular, main's `quality_gates.window_leaks` (`quality_gates.py:81-83`),
   `leftover_recommends` and `recommend_coverage` all filter `task.family == "recommend"`, so they
   miss composites (which carry family `log`/`update`) — the same blind spot ship-10 fixed in
   `validate_draft`. Mirror that fix when the branches land.
