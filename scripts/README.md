# Scripts

Run from the repository root with `uv run python`. API evaluations spend provider quota;
builds and local verification do not invoke models implicitly.

| Script | Role | Example |
|:--|:--|:--|
| `eval_benchmark_suite.py` | Concurrent evaluation with protocol-aware resume | `uv run python scripts/eval_benchmark_suite.py --split data/splits/nutrienv-v1.1.json --model commandcode/inclusionai/ling-3.0-flash-sante:free --workers 5` |
| `build_split_v1_1.py` | Rebuild/check the exam and all three reductions | `uv run python scripts/build_split_v1_1.py --check` |
| `check_achievable.py` | Legal oracle/witness reachability | `uv run python scripts/check_achievable.py --split data/splits/nutrienv-v1.1.json` |
| `generate_one_cli.py` | Agent-authored draft and independent review admission | See [authoring contract](../docs/agent-authored-tasks.md) |
| `run_split.py`, `run_react.py` | Script replay and single-task debugging | `uv run python scripts/run_split.py --split data/splits/nutrienv-mini.json` |
| `run_ablation.py`, `compare_harness_modes.py` | Explicit scaffold/transport comparisons | Use paired runs with matching split and protocol identity |
| `download_fdc.py` | Download raw USDA input | `uv run python scripts/download_fdc.py --sets fndds` |
| `build_fdc_catalog.py` | Build the active FNDDS catalog | `uv run python scripts/build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v3.sqlite` |
| `render_v1_1.py` | Verify 189 recorded trajectories, render v1.1 charts/table and hash manifest | `uv run --extra plots python scripts/render_v1_1.py` |
| `rescore_report.py` | Re-judge compatible trajectories; refuses prompt/loop or action-acceptance drift | `uv run python scripts/rescore_report.py reports/run.json --out reports/run.rescored.json` |
| `render_benchmark_charts.py`, `render_radar.py`, `render_leaderboard.py` | Historical v1.0 visualization/table tools | They are not v1.1 chart generators; old asset filenames are preserved |
| `verify_counterfactual.py`, `scorer_robustness_probe.py` | Offline scorer controls | These checks do not measure model performance |

`archive/` contains explicit legacy tools used by compatibility tests and the legacy parser CLI.
Their presence is not a fallback from active agent-authored admission. Historical catalog
verification also dynamically loads `archive/fndds_dry_run.py`; keep it with the builder.
