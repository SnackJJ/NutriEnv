# NutriEnv Scripts

本目录包含 **NutriEnv** 评测体系的核心 CLI 工具与维护脚本。

---

## 🚀 常用运行脚本

| 脚本 | 用途 | 常用调用示例 |
|---|---|---|
| [`eval_benchmark_suite.py`](./eval_benchmark_suite.py) | **全量 Benchmark 跑测引擎**：支持多 Worker 并发、断点续跑 (`--resume`)、失败重跑 (`--rerun-failed`) | `python scripts/eval_benchmark_suite.py --model glm-5.3 --workers 5` |
| [`run_split.py`](./run_split.py) | **基准 Split 评测器**：对冻结测试集进行端到端推理评测 | `python scripts/run_split.py data/splits/v2.2-mini.json` |
| [`run_react.py`](./run_react.py) | **单任务 ReAct 推演**：针对单一题目进行交互式 ReAct 轨迹调试 | `python scripts/run_react.py --id adr20-log-5000` |
| [`download_fdc.py`](./download_fdc.py) | **USDA FDC 官方数据下载**：拉取 FNDDS / SR Legacy / Branded 数据集 | `python scripts/download_fdc.py --sets fndds` |
| [`build_fdc_catalog.py`](./build_fdc_catalog.py) | **食物世界数据库构建**：将原始 USDA CSV 编译为可检索的 SQLite 知识库 | `python scripts/build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite` |
| [`materialize_split.py`](./materialize_split.py) | **候选集编译与冻结**：将 Candidate JSON 转化为正式 Frozen Split | `python scripts/materialize_split.py --in data/candidates/v2.2-candidates.json --out data/splits/v2.2-gold.json` |
| [`generate_one_cli.py`](./generate_one_cli.py) | **单题生成与 Oracle 求解验证** | `python scripts/generate_one_cli.py --family log --persona cut` |
| [`check_achievable.py`](./check_achievable.py) | **题库健康度验证**：验证所有题目的 Oracle 可达性与 100% Round-Trip Pass | `python scripts/check_achievable.py data/splits/v2.2-gold.json` |

---

## 📦 历史归档区 (`scripts/archive/`)

早期研发阶段的原型探针、过渡性生成脚本及中间验证工具已完整归档至 [`scripts/archive/`](./archive/) 目录，保持根目录清晰整洁。
