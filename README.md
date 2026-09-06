# NutriEnv: An Interactive Nutrition Benchmark & Environment for LLM Agents

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://github.com/SnackJJ/NutriEnv"><img src="https://img.shields.io/badge/benchmark-NutriEnv--v1.0%20(63%20tasks)-orange.svg" alt="NutriEnv v1.0"></a>
</p>

NutriEnv is an interactive, steppable environment and benchmark suite designed to evaluate the multi-turn tool interaction, dietary state tracking, high-dimensional inequality planning, and nutrition grounding capabilities of Large Language Models (LLMs) and Agentic AI.

Unlike traditional static QA datasets, NutriEnv evaluates agents in a stateful, interactive environment grounded in the USDA Food and Nutrient Database for Dietary Studies (FNDDS).

---

## Evaluation Leaderboard (NutriEnv v1.0)

The official NutriEnv v1.0 benchmark consists of 63 curated tasks with audited construct validity.

<p align="center">
  <img src="reports/assets/eval_leaderboard_bars.png" width="760" alt="NutriEnv v1.0 Leaderboard Pass@1" />
</p>

<p align="center">
  <img src="reports/assets/eval_pareto_efficiency.png" width="760" alt="NutriEnv v1.0 Pareto Frontier" />
</p>

### Main Results

| Rank | Model | Total Pass Rate | Solved / Total | Avg Turns | Avg Latency | Update (2) | Log (6) | Evaluate (8) | Recommend (11) | Composite (36) |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | **DeepSeek-v4-pro** | **84.1%** | **53 / 63** | 12.9 | 167.5s | 2/2 (100%) | 5/6 (83.3%) | 6/8 (75.0%) | **10/11 (90.9%)** | **30/36 (83.3%)** |
| 2 | **GLM-5.3 (Flagship)** | **82.5%** | **52 / 63** | 14.6 | 112.2s | 2/2 (100%) | 5/6 (83.3%) | 6/8 (75.0%) | **10/11 (90.9%)** | 29/36 (80.6%) |
| 3 | **DeepSeek-v4-flash** | **71.4%** | **45 / 63** | 11.0 | 248.9s | 2/2 (100%) | **6/6 (100.0%)** | **7/8 (87.5%)** | 8/11 (72.7%) | 22/36 (61.1%) |
| 4 | **GLM-5.3-flash** | **68.2%** | **43 / 63** | **10.9** | **59.5s** | 2/2 (100%) | 4/6 (66.7%) | 4/8 (50.0%) | 7/11 (63.6%) | 26/36 (72.2%) |

> Evaluated on standardized API endpoints across reasoning and lightweight models (all models were invoked via Volcano Engine / 火山引擎 Agent Plan). Full execution traces, logs, and token metrics are preserved in [`reports/`](./reports/).

---

## Environment Architecture & Tool Protocol

NutriEnv models an interactive dialogue between a user and an AI dietary assistant. The world state mutates deterministically based on agent actions:

```
                  +-----------------------------------------+
                  |          NutriEnv WorldState            |
                  |  |- User Profile (allergies, DRI bands) |
                  |  |- Meal Ledger  (history & timestamps) |
                  |  +- Food Catalog (USDA FNDDS SQLite)    |
                  +--------------------+--------------------+
                                       |
                Actions (JSON)         | Observations (Dict)
                      |                |
                      v                v
             +-----------------------------------+
             |       LLM Agent (ReAct Loop)      |
             +-----------------------------------+
```

### Action Space

| Action | Parameters | Description |
|:---|:---|:---|
| `search_foods` | `q: str` | BM25 full-text search against the USDA FNDDS catalog |
| `get_food` | `food_id: str` | Inspect food portions, measures, calories, and micronutrients |
| `log_meal` | `food_id, grams, eaten_at` | Record an intake item to the user's meal ledger |
| `amend_meal`| `index, grams?, food_id?` | Modify or substitute an existing ledger entry |
| `update_profile` | `patch: dict` | Update dietary targets, DRI windows, or allergies |
| `submit_plan`| `items: list[dict]` | Propose a planned meal satisfying target nutrition windows |
| `evaluate_diet`| `verdict, reasons` | Accept/reject candidate foods based on clinical guidelines & myths |
| `finish` | `message: str` | Finalize task turn |

---

## Evaluation Philosophy: Ground-Truth Oracle Matching

NutriEnv abides by an objective axiomatic evaluation rule:
$$\text{Pass} \iff \text{End State} == \text{Oracle}$$

1. **Deterministic Verification over LLM-as-a-Judge**: Scoring inspects deterministic environment state mutations rather than subjective LLM judges:
   - Profile equality (allergies, health targets).
   - Ledger set equality with $\pm 15\%$ physical measure tolerance.
   - Exact mathematical satisfaction of multi-dimensional nutrient windows:
     $$\text{Nutrient}_k = \sum \text{grams}_i \times \frac{\text{Nutrient}_{i,k}}{100} \in [\text{Lower}_k, \text{Upper}_k]$$
2. **Zero Cheat-Sheets**: Handbooks provide tool specs and action schemas. Agents must reason and ground colloquial portions autonomously via `search_foods` + `get_food`.
3. **Safety Redlines**: Proposing or logging foods containing user allergens triggers an immediate `allergy_violation` failure.

---

## Quick Start

### 1. Installation

```bash
git clone https://github.com/SnackJJ/NutriEnv.git
cd NutriEnv

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure API Keys

```bash
cp .env.example .env.local
# Add your ARK_API_KEY / DASHSCOPE_API_KEY / DEEPSEEK_API_KEY
```

### 3. Run Unit & Regression Tests

```bash
pytest
# smoke: Env, Pass scoring, published exam load
```

### 4. Run Benchmark Suite

```bash
# Evaluate GLM-5.3 on the official v1.0 benchmark (63 tasks)
python scripts/eval_benchmark_suite.py \
  --split data/splits/nutrienv-v1.0.json \
  --model ark/glm-5.3 \
  --workers 5 \
  --out reports/benchmark_ark_glm-5.3_v1.0.json
```

---

## Repository Structure

NutriEnv maintains a clean, industry-standard layout:

```text
nutri-env/
|-- src/nutrienv/              # Core environment package
|   |-- env/                   # Interactive Gym-style step/reset loop
|   |-- world/                 # Food catalog (SQLite), Profile, Ledger state
|   |-- actions/               # Action schemas, validators, and execution dispatch
|   |-- bench/                 # Task generator, Oracle, Scorer, mill pipeline
|   |-- harness/               # Agent harnesses (ReAct, Script, Telemetry)
|   +-- io/                    # Network clients & environment loaders
|-- data/
|   |-- fdc/                   # USDA FNDDS catalog (`catalog.sqlite`)
|   |-- portion/               # Colloquial portion overlay
|   +-- splits/
|       |-- nutrienv-v1.0.json # Official v1.0 exam (63 tasks)
|       +-- nutrienv-mini.json # Smoke subset (10 tasks from v1.0)
|-- reports/                   # Official four-model results & charts
|-- docs/                      # Glossary
|-- scripts/                   # Evaluation runner and visualization tools
+-- tests/                     # Unit and integration tests
```

---

## Citation & License

This project is licensed under the [MIT License](LICENSE).

```bibtex
@misc{snackjj2026nutrienv,
  author = {Zeqing Jiang},
  title = {NutriEnv: An Interactive Nutrition Benchmark & Environment for LLM Agents},
  year = {2026},
  publisher = {GitHub},
  howpublished = {\url{https://github.com/SnackJJ/NutriEnv}}
}
```
