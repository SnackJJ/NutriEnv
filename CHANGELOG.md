# Changelog

All notable changes to the NutriEnv project are documented in this file.

## [v1.0.0] - 2026-09-04 (Lite Gold Release)

### Added
- **NutriEnv v1.0 Gold Split (63 tasks)**: Refined from exploratory sets to achieve strict construct validity with **0 hard false-negatives** and **0 false-positives**.
- **CRUD Ledger Protocol (`amend_meal`)**: Complete ledger lifecycle support for modifying previously logged foods and portion corrections.
- **Dietary Myths & Guideline Matrix**: 6 real-world dietary myth evaluation tasks (fat vs carb balance, extreme restriction traps).
- **Multi-Model Benchmark Reports**: Complete trajectory evaluations across 4 flagship & flash models (`GLM-5.3`, `DeepSeek-v4-pro`, `DeepSeek-v4-flash`, `GLM-5.3-flash`).
- **High-Resolution Capability Radar**: Multi-dimensional breakdown asset (`reports/assets/radar_v1.0_family.png`).

### Changed
- **Task Pruning**: Archived 7 defective catalog-mismatch queries into `data/splits/archive/v2.8-pruned-defective.json` to ensure 100% solver soundness ahead of v3.0 IR engine upgrade.
- **Evaluation Hardening**: Raised single-step timeout to 90s with automated turn retries to withstand transient gateway latency.

### Verified
- **1,408 / 1,408 Unit & Integration Tests Passing** (`pytest`).
