# Changelog

All notable changes to the NutriEnv project are documented in this file.

## [Unreleased]

### Changed
- Moved remaining process probes (`landing_verify`, `materialize_split`, `gray_zone_probe`, and related builders) into `scripts/archive/`.
- Documented why `data/fdc/archive/*.sqlite` remain in the clone: mill tests pin SR Legacy portion keys that catalog-v2 drops.
- Dropped CHARTER, ADRs, mill design notes, and `tests/archive` from the public tree. Vocabulary is `docs/glossary.md`.

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
