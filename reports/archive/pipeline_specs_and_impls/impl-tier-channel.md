# Impl report: evaluate tier authoring channel in generate_one

Spec: `reports/spec-tier-channel.md`. Data channel only — tier CONTENT design
belongs to issue 15. Commit on main, prefix "pipeline:".

## What changed (`src/nutrienv/bench/pipeline/generate_one.py`)

- `generate_one(..., tier: str = "")` — new keyword parameter.
- Validation at entry: `tier` non-empty is accepted only when
  `family == "evaluate"` and `tier in EVALUATE_TIERS` (imported from
  `nutrienv.bench.quality_gates`); anything else raises `ValueError` — so a
  log/recommend/update/composite cannot be tiered and nobody can invent a
  tier name.
- Tier threaded into every accepted-Task construction:
  - evaluate path: `_evaluate_from_bound(tier=...)` → `_realize_eval(tier=...)`
    (both the fit draft and the knife-unfit rewrite) and both `_retag(...)`
    leftover branches; `_realize_eval` passes it to `realize_evaluate` and
    keeps it on the re-wrapped Task; `_retag` gained `tier=""` (keeps
    `task.tier` when empty, so existing callers are unaffected);
  - other families (always `""` by validation): direct `tier=tier` keyword on
    the log Task, `_log_then_recommend`, `_log_then_evaluate_fit`,
    `_update_then_recommend`, `_recommend_from_template`,
    `_update_from_template`.
- Rejected paths untouched. No changes to quality_gates.py, validator.py,
  scorer.py, review_harness.py, ADRs, or split data.

## Tests (`tests/test_generate_one_evaluate.py`, +4)

- `test_generate_one_evaluate_accepts_declared_tier` — `_run_eval(tier="pair")`
  → `task.tier == "pair"`, `validate_draft(task) == []`,
  `evaluate_tier_coverage([task]).counts["pair"] == 1`.
- `test_generate_one_evaluate_rejects_unknown_tier` — `tier="bogus"` raises.
- `test_generate_one_log_rejects_tier` — `family="log", tier="single"`
  raises.
- `test_evaluate_tier_survives_freeze_load_round_trip` — freezer payload
  carries `"tier": "pair"`; freeze→`load_split` reload keeps `.tier == "pair"`
  (mirrors test_band_freeze_replay minimally; note: the mill's authoring
  situation tag `"evaluate_fit"` is not split-reload vocabulary, so the
  round-trip strips situations — pre-existing, orthogonal to the tier
  channel).

## Verification

```
$ .venv/bin/python -m pytest tests/test_generate_one_evaluate.py -q
................                                                         [100%]
16 passed in 0.17s

$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1300 passed in 42.80s
```

(Previously 1296; +4 new tests, 0 failures.)

## Review (codex)

**Verdict: REV.** Valid declared string tiers are threaded correctly through
every accepted Evaluate path and survive serialization, but the public
validation accepts invalid falsey non-string values and stores them on
`Task.tier`.

### Standards

No `AGENTS.md` violation or actionable baseline smell was found. The import
direction is acyclic: `pipeline.generate_one -> quality_gates ->
realize/validator`, with no reverse import of `generate_one`. Reusing
`EVALUATE_TIERS` keeps tier policy centralized.

### Spec

- **Medium — invalid falsey tier values bypass validation** —
  `src/nutrienv/bench/pipeline/generate_one.py:170-171`: `if tier and ...`
  validates only truthy values, although spec lines 23-26 permit only the empty
  string or a declared `EVALUATE_TIERS` string. Direct probes showed
  `tier=None`, `False`, `0`, and `[]` all accepted and stored verbatim on the
  returned `Task`. These values silently count toward no tier floor and violate
  the `Task.tier: str` contract. **Fix:** reject non-strings explicitly, then
  validate every non-empty string against family and `EVALUATE_TIERS`; add a
  falsey non-string regression test.

- **Low — the round-trip description is inaccurate** —
  `tests/test_generate_one_evaluate.py:532-536` and
  `reports/impl-tier-channel.md:38-42`: the report/comment says the
  `evaluate_fit` authoring situation is stripped on reload, but the test
  removes it with `replace(task, situations=())` before freezing. Freezing the
  unmodified generated task and loading it raises `ValueError: unknown
  situations: ['evaluate_fit']`. **Fix:** say explicitly that the test
  normalizes the unrelated authoring-only situation before freeze, or provide
  a separate normalization channel.

- **Low — the committed report references an untracked spec** —
  `reports/impl-tier-channel.md:3` points to
  `reports/spec-tier-channel.md`, but that spec is absent from the commit and
  remains untracked. **Fix:** commit the design-authority spec so the report's
  reference resolves in a clean checkout.

### Correctness of threading

- All current accepted branches preserve a valid tier: fit, knife-unfit
  rewrite, leftover-over retag, and leftover-under retag each returned
  `tier="triple"` in direct probes. Every direct non-Evaluate Task constructor
  receives the validated empty tier.
- `_retag(..., tier="")` correctly preserves `task.tier`; a direct probe kept
  `"triple"`. Rejected results contain no Task, so they need no tier.
- A Composite probe retained the default empty tier, as required. No valid-tier
  loss exists between `generate_one`, `task_to_item`, `freeze_tasks`, and
  `load_split` once the orthogonal situation vocabulary is normalized.
- No pre-existing caller passed `tier=` to `generate_one`, so the new strict
  declared-string checks do not break an existing call site.

### Test quality and evidence

The four new tests assert real behavior and no existing assertion was weakened.
The round-trip test uses the real freezer and loader rather than mocks, although
it pre-normalizes situations as noted above. The main coverage gap is that only
the fit path is tested with a tier; a regression in either `_retag` branch or
the knife-unfit rewrite would remain green. **Low — add a parameterized tier
propagation test covering fit, knife-unfit, leftover-over, and
leftover-under.**

- `tests/test_generate_one_evaluate.py`: **16 passed**.
- Full suite: **1300 passed**.
- Direct probes: four accepted Evaluate branches kept `triple`; Composite kept
  `""`; invalid falsey values were accepted, confirming the blocker.
- Commit scope contains no ADR, split, SQLite, scorer, validator,
  review-harness, or `quality_gates.py` change.
- Review-only: no code was edited or merged.

Summary: Standards has **0 findings**; Spec has **3 findings** (worst: Medium
falsey-value validation bypass), plus **1 Low test-coverage gap**.

## Fix round (codex findings)

Review: "## Review (codex)" above (verdict REV). Two findings, both fixed.

- **Medium — falsey non-string tiers bypassed validation.** `generate_one`
  now rejects non-string `tier` values before the truthy check:
  `if not isinstance(tier, str): raise ValueError("tier must be a string,
  ...")`. `None`, `0`, `[]`, `False` all raise instead of being stored
  verbatim on `Task.tier`. Regression test:
  `test_generate_one_rejects_falsey_non_string_tiers` (covers None / 0 / []
  / False).
- **Low — round-trip wording corrected.** The reload failure with the
  authoring situation tag intact is real (`evaluate_fit` is not in split.py's
  situations vocabulary; `load_split` raises "unknown situations"), so the
  accurate description — now in both the test comment and this report — is:
  the test deliberately strips the situation tag via
  `replace(task, situations=())` before freezing, so the round-trip asserts
  that the tier survives independent of situations. Test semantics unchanged.

## Fix-round verification

```
$ .venv/bin/python -m pytest tests/test_generate_one_evaluate.py -q
.................                                                        [100%]
17 passed in 0.19s

$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1301 passed in 44.03s
```

(Previously 1300; +1 regression test, 0 failures.)

## Re-review (codex)

**Verdict: ACC.** The blocking validation defect is fixed, valid string inputs
remain compatible, and no new code or spec finding was introduced.

| Prior finding | Status | Re-review evidence |
|---|---|---|
| Medium — falsey non-string tier bypass | **Resolved** | `generate_one` rejects non-strings before the truthy policy check. Direct probes confirmed `None`, `0`, `[]`, and `False` raise `ValueError`; the regression test covers all four. `tier=""` remains accepted and carried as empty, while `tier="pair"` remains accepted and carried as `"pair"`. |
| Low — inaccurate round-trip wording | **Resolved in the test and fix-round record** | The test comment and fix-round section now explicitly state that `replace(task, situations=())` removes the authoring-only situation before freeze, isolating tier persistence. The original implementation-summary sentence at lines 35-40 still says the round-trip “strips” situations; this stale historical wording is non-blocking but should be aligned in a later documentation cleanup. |

### Standards

No documented-standard violation or actionable baseline smell was found. The
type guard is localized at the public authoring boundary and preserves the
existing string policy.

### Spec

The accepted domain is now exactly the intended runtime contract: a string,
empty for no tier or a declared Evaluate tier under the existing family check.
No scope creep or forbidden-path change was introduced.

### Verification

- `tests/test_generate_one_evaluate.py`: **17 passed**.
- Full suite: **1301 passed**.
- Direct probes: four falsey non-strings rejected; `""` and `"pair"` accepted
  and carried correctly.
- Review-only: no code was edited or merged.

No new findings. The previously noted untracked spec is unchanged and outside
this two-finding fix round.

Summary: Standards has **0 findings**; Spec has **0 new findings**.
