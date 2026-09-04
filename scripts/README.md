# NutriEnv Scripts

Public evaluation and catalog tools. Historical builders and probes live in [`archive/`](./archive/).

| Script | Role | Example |
|---|---|---|
| [`eval_benchmark_suite.py`](./eval_benchmark_suite.py) | Concurrent ReAct eval with resume / rerun | `python scripts/eval_benchmark_suite.py --split data/splits/nutrienv-v1.0.json --model ark/glm-5.3 --workers 5` |
| [`run_split.py`](./run_split.py) | ScriptHarness replay of a frozen split | `python scripts/run_split.py --split data/splits/nutrienv-mini.json` |
| [`run_react.py`](./run_react.py) | Single-task ReAct debug | `python scripts/run_react.py --id adr20-upd-5026` |
| [`check_achievable.py`](./check_achievable.py) | Oracle replay / reachability | `python scripts/check_achievable.py data/splits/nutrienv-v1.0.json` |
| [`download_fdc.py`](./download_fdc.py) | Download USDA FNDDS / SR Legacy / Branded | `python scripts/download_fdc.py --sets fndds` |
| [`build_fdc_catalog.py`](./build_fdc_catalog.py) | Compile FNDDS into the SQLite catalog | `python scripts/build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite` |
| [`generate_one_cli.py`](./generate_one_cli.py) | Single-task mill (offline `--synthetic` in tests) | `python scripts/generate_one_cli.py --synthetic --seed 0` |
| [`render_radar.py`](./render_radar.py) | Family radar from a benchmark JSON | `python scripts/render_radar.py` |
| [`render_benchmark_charts.py`](./render_benchmark_charts.py) | Leaderboard / Pareto charts from v1.0 reports | `python scripts/render_benchmark_charts.py` |
