# Changelog

All notable changes to the NutriEnv project are documented in this file.

## [v1.1.0] - 2026-10-05

- Published `nutrienv-v1.1-mass-envelopes-20261005` and all three reductions with reviewed
  natural questions, QNS/explicit-unit evidence, complete ledger alternatives and inventory choices.
- Active catalog is `catalog-v3.sqlite`, with repaired edamame soy tags. Historical catalogs remain immutable.
- Scorer `s10-meal-mass-envelope`: goal-specific AMDR/muscle targets, exact macro ceilings,
  gold-ledger budgets, explicit high-protein requirements and immutable meal/snack/day mass envelopes.
- Prompt `p8-published-meal-mass-limits` exposes episode limits; invalid profile changes fail atomically.
- Active task admission requires agent-authored structured evidence, legal witnesses and independent
  exact-hash review. Parser/template generation is explicitly legacy.
- Three internal ARK single-run reports, separate charts and replay-verified artifact hashes are published.
  These results are not the official leaderboard and are not directly comparable with v1.0 or earlier v1.1.
- Preserved the published v1.0 table, report bytes and image assets. Search/p9 changes remain deferred.

## [v1.0 protocol refresh] - 2026-09-29

### Changed
- **Leaderboard re-measured (not comparable with the v1.0.0 table).** Five models, native
  function calling, temperature 0, through the Command Code provider plan; the table is the mean
  over each model's complete runs (1–3; runs voided part-way by the provider's usage limit are
  excluded). Reports are `reports/benchmark_commandcode_<model>_v1.0_fc_r<k>.json` plus one
  `…_text.json` per model. The Volcano Engine ARK plan behind the v1.0.0 table is retired and
  GLM-5.3 (flagship) was not re-measured; the old reports remain in git history.
- **Scorer** (`SCORER_VERSION = s6-free-recommend-windows`, recorded in every report): plan
  windows are derived from the gold ledger, a plan is matched by per-food gram totals, and the
  protein / carb / fat / fiber ceilings (reference intakes, not limits) are judged with 15% slack;
  floors, the energy ceiling and the sodium ceiling stay exact. The category-synonym rule shipped
  with v1.0.0 (a food outside a task's allowed set passed when it shared an FDC category and a
  head word with an allowed food) is removed: it was a name heuristic, not part of the task
  contract.
- **Episode loop** (`LOOP_VERSION = l2-refused-handin-continues`): a hand-in the Env refuses no
  longer ends the episode. Reports also record `prompt_version` / `prompt_fingerprint`; resume,
  rerun and reuse refuse a cache measured under another scorer, loop or prompt.
- `eval_benchmark_suite.py` defaults to `--contract native-tools`; `--contract text-json` runs the
  ReAct text loop. `--parse-error-policy` and `--temperature` are new.
- `load_catalog` raises on a missing snapshot instead of substituting the 15-food demo fixture
  (`demo=True` asks for it explicitly).

### Added
- `scripts/rescore_report.py` (re-judge a report's trajectories under the current Scorer),
  `scripts/render_leaderboard.py` (leaderboard table from report JSON).
- `scripts/run_ablation.py`, `scripts/verify_counterfactual.py` and
  `nutrienv.harness.buddy` (`BuddyHarness`, `build_scaffold`): harness-scaffold ablations,
  including the verify-then-revise gate and the submit preview with same-trajectory
  counterfactual scoring.

### Repository
- Dropped CHARTER, ADRs, mill design notes, and `tests/archive` from the public tree. Vocabulary is `docs/glossary.md`.
- Public tree no longer ships split/script/catalog archives or the mill test suite. Published catalog is `data/fdc/catalog.sqlite`.

## [v1.0.0] - 2026-09-05

### Added
- **NutriEnv v1.0 exam (63 tasks)**: Cut from the earlier 100-task line after a construct-validity audit; catalog-mismatch and defective items were removed.
- **Ledger amend (`amend_meal`)**: Correct or substitute a previously logged intake row.
- **Dietary-myth evaluate tasks**: Guideline / myth items in the frozen split.
- **Four-model leaderboard**: GLM-5.3, DeepSeek-v4-pro, DeepSeek-v4-flash, GLM-5.3-flash on the 63-task exam.

### Changed
- Published split is `data/splits/nutrienv-v1.0.json`. `data/splits/nutrienv-mini.json` is a 10-task subset for smoke runs.
- Historical v2.x freezes and candidate pools moved under `data/splits/archive/`.
- Default `EXAM_SPLIT_PATH` / `load_exam()` now resolve to v1.0.

### Verified
- Unit and integration tests (`pytest`).
