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

| Rank | Model | Total Pass Rate | Solved / Total | Avg Steps | Avg Latency | Update (2) | Log (6) | Evaluate (8) | Recommend (11) | Composite (36) | text-json |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | **DeepSeek-v4-pro** | **84.1%** | **53 / 63** | 10.9 | 120.5s | 2/2 (100.0%) | 5/6 (83.3%) | 7/8 (87.5%) | 9/11 (81.8%) | 30/36 (83.3%) | 54 / 63 |
| 2 | **GLM-5.3-flash** | **81.0%** | **51 / 63** | 12.2 | 235.4s | 2/2 (100.0%) | 4/6 (66.7%) | 6/8 (75.0%) | 9/11 (81.8%) | 30/36 (83.3%) | 53 / 63 |
| 2 | **MiMo-v2.6-flash** | **81.0%** | **51 / 63** | 13.9 | 216.0s | 2/2 (100.0%) | 5/6 (83.3%) | 6/8 (75.0%) | 8/11 (72.7%) | 30/36 (83.3%) | 43 / 63 |
| 4 | **DeepSeek-v4-flash** | **68.3%** | **43 / 63** | 11.5 | 37.1s | 2/2 (100.0%) | 2/6 (33.3%) | 5/8 (62.5%) | 9/11 (81.8%) | 25/36 (69.4%) | 44 / 63 |
| 5 | **DeepSeek-v4.1-flash** | **58.7%** | **37 / 63** | 11.4 | 40.6s | 2/2 (100.0%) | 5/6 (83.3%) | 4/8 (50.0%) | 7/11 (63.6%) | 19/36 (52.8%) | 44 / 63 |

> **Protocol.** One run per model on `data/splits/nutrienv-v1.0.json` (63 tasks), native function
> calling (`--contract native-tools`, the default), temperature 0, all models through the
> Command Code provider plan. Every report records the ruler it was
> measured with: `scorer_version = s6-free-recommend-windows`, `loop_version =
> l2-refused-handin-continues`, `prompt_version = p5-fc-manual-lines`. The **text-json** column is
> the same models on the ReAct text contract, re-judged offline with the same Scorer
> (`scripts/rescore_report.py`). Full traces and token counts are in [`reports/`](./reports/)
> (`benchmark_commandcode_<model>_v1.0_{fc,text}.json`); the Pass / Rate columns can be regenerated from
> them with `scripts/render_leaderboard.py`.
>
> **Single runs are noisy.** A second FC run of DeepSeek-v4.1-flash under the identical
> configuration scored 49 / 63 (vs 37 above); differences of a few tasks between rows are not
> meaningful.
>
> **Not comparable with the previous table.** The earlier leaderboard (GLM-5.3 flagship,
> DeepSeek-v4-pro/flash and GLM-5.3-flash via the Volcano Engine ARK plan, since retired) was
> measured before the scorer and episode-loop revisions listed in [CHANGELOG](./CHANGELOG.md);
> it is kept in git history only. GLM-5.3 (flagship) is not offered on the current provider and
> is not re-measured.

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
   - Satisfaction of multi-dimensional nutrient windows:
     $$\text{Nutrient}_k = \sum \text{grams}_i \times \frac{\text{Nutrient}_{i,k}}{100} \in [\text{Lower}_k, \text{Upper}_k]$$
     Every floor, the energy ceiling and the sodium ceiling are exact. The protein, carb, fat and
     fiber ceilings are reference intakes (scaled FDA Daily Values), not limits, and are judged with
     15% slack (`TARGET_CEILING_SLACK`).
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
# Add your COMMANDCODE_API_KEY (DASHSCOPE_API_KEY / DEEPSEEK_API_KEY for the other routes)
```

### 3. Run Unit & Regression Tests

```bash
pytest
# smoke: Env, Pass scoring, published exam load
```

### 4. Run Benchmark Suite

```bash
# Evaluate DeepSeek-v4-pro on the official v1.0 benchmark (63 tasks, native function calling)
python scripts/eval_benchmark_suite.py \
  --split data/splits/nutrienv-v1.0.json \
  --model commandcode/deepseek/deepseek-v4-pro \
  --workers 6 \
  --out reports/benchmark_commandcode_deepseek-v4-pro_v1.0_fc.json
# add --contract text-json for the ReAct text loop
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
|-- reports/                   # Official leaderboard reports & charts
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
