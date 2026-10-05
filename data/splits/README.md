# Splits

Two kinds of file live here, and confusing them is the easiest way to publish a wrong number.

## The exam

`nutrienv-v1.1.json` is the published 63-task ruler, version
`nutrienv-v1.1-mass-envelopes-20261005`. It uses goal-specific daily ranges, explicit high-protein
meal scoring, naturally clarified questions, reviewed inventory choices and complete ledger
variants. Its catalog binding is `data/fdc/catalog-v3.sqlite`, with repaired edamame soy tags.
The 12 named basket foods have 28 reviewed catalog IDs, not 12 unique IDs.

`scripts/build_split_v1_1.py` applies
[`v1.1-content-revisions.json`](./v1.1-content-revisions.json) and rebuilds the formal exam and
all three reductions with unchanged task IDs. `--check` verifies all four files. The older
`v1.1-query-clarifications.json` is a historical proposal, no longer build input.
The [current contract](../../docs/review-v1.1-query-contracts.md) documents portions, nutrient
windows, prompt visibility, scoring and remaining limitations.

Gold portions, windows, inventory options, catalog and scoring have changed. Current results
use scorer `s10-meal-mass-envelope` and prompt `p8-published-meal-mass-limits`;
they are not directly comparable with v1.0 or earlier v1.1 results. Published historical
leaderboards remain unchanged. A report must identify the split hash, catalog checksum,
scorer and prompt fingerprint, not just this filename.

Meal scope and total-mass limits are public episode context: main meal 1500 g, snack 500 g,
whole day 4000 g, including drinks. The [agent authoring pipeline](../../docs/agent-authored-tasks.md)
uses structured catalog evidence and independent review, not natural-language back-resolution.

`nutrienv-v1.0.json` — the previous ruler (FDA DV windows), kept for the reports that name it. Revised 2026-09-17 (13 tasks
re-specified, four of them with changed grading); the revision is tagged
`nutrienv-v1.0-gold-20260917`. Nothing before that tag is comparable with anything after it.

`archive/` holds the frozen earlier generations (`v0.x`–`v2.x`). They are still loadable because
active tests exercise several of them; see `archive/README.md`.

## Reductions

A reduction exists to make one specific question cheap to ask. Its Pass rate is **not** the
exam's Pass rate, and it does not inherit the exam's authority.

| file | n | for | not for |
|---|---|---|---|
| `nutrienv-mini.json` | 10 | smoke tests, cost of a wiring change | anything with a number attached |
| `mini-fast.json` | 9 | screening a scaffold for catastrophe (does it crash, does it tank) | measuring whether a scaffold helps |
| `mini-harness.json` | 23 | paired, same-model harness comparison | comparing models |

### Why `mini-fast.json` cannot measure a harness

Its 9 tasks almost all pass on the baseline, so it has no headroom to improve. Measured: the
baseline (`react`, GLM-5.3) passes 8 of the 9, and — more to the point — none of the three
tasks whose failure tags are what the buddy layers target (`window`, `allergy`,
`inventory_miss`) is in it. A screening run on `mini-fast` reported `react` and `buddy-gate`
at the same 88.9%; that is a statement about the subset, not about the gate.

### Why a failure-selected reduction cannot rank models

`mini-harness.json` is the union of every task that fails on the current exam (10), every task
the 2026-09-17 revision touched (13), and both `update` tasks (a regression sentinel for `pin`,
which disturbs the profile windows). That makes it a good **paired** instrument: the scaffolds differ
by one flag and run on the same tasks, so task-specific difficulty cancels out.

Its task ids were chosen on v1.0 results and kept for v1.1, so "fails on the current exam" means
v1.0's exam.

It is a bad **unpaired** instrument, because failure is model-specific — a task GLM-5.3 misses
can be easy for a different model. Measured against the four released 63-task reports, this
subset does not merely blur the leaderboard, it inverts it:

| model | full 63 | `mini-harness` 23 |
|---|---|---|
| GLM-5.3 | 71.4% (1st) | 47.8% (2nd=) |
| DeepSeek-v4-pro | 69.8% (2nd) | **43.5% (4th)** |
| DeepSeek-v4-flash | 66.7% (3rd) | **65.2% (1st)** |
| GLM-5.3-flash | 60.3% (4th) | 47.8% (2nd=) |

Its spread looks *better* (21.7pt vs 11.1pt) while being wrong, which is the trap: a subset that
separates models more can separate them in the wrong order.

## Ranking these models needs repeats, not a bigger subset

Simulated over the four released reports (per-task outcomes treated as ground truth, plus the
measured run-to-run flip rate: temperature-0 repeats disagree on ~10% of tasks):

| tasks | repeats | top-1 model correct | full 4-way order correct |
|---|---|---|---|
| 63 | 1 | 69% | 51% |
| 63 | 3 | 76% | 68% |
| 63 | 5 | 82% | 78% |
| 63 | 8 | 87% | 86% |
| 30 | 3 | 54% | — |
| 50 | 3 | 62% | — |

Two things follow. Shrinking the subset makes the ranking **worse**, not cheaper: 30–50 tasks
with 3 repeats lands at 54–62% on the top-1 question. And even 63 tasks with 8 repeats only
reaches 87%, because the models are genuinely close — GLM-5.3 leads DeepSeek-v4-pro by 1.6pt,
which is well inside this exam's noise floor. The honest presentation is a grouping
(`GLM-5.3 ≈ DeepSeek-v4-pro`, then `DeepSeek-v4-flash`, then `GLM-5.3-flash`) with an explicit
"not distinguishable" note on the first pair, not a ranked list.

If a sharper separation is wanted, the lever is a harder or larger exam, not a smaller one.
