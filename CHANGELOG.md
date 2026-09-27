# Changelog

All notable changes to the NutriEnv project are documented in this file.

## [Unreleased]

### Changed
- **Leaderboard re-measured (not comparable with the v1.0.0 table).** Five models, one run each,
  native function calling, temperature 0, through the Command Code provider plan; reports are
  `reports/benchmark_commandcode_<model>_v1.0_{fc,text}.json`. The Volcano Engine ARK plan behind
  the v1.0.0 table is retired, so GLM-5.3 (flagship) is not re-measured; the old reports remain
  in git history.
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
