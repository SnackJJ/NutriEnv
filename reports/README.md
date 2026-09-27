# NutriEnv Evaluation Reports

This directory contains the official evaluation trajectories, metrics, and visualization assets for **NutriEnv v1.0**.

## Directory Structure

```text
reports/
|-- assets/
|   |-- eval_leaderboard_bars.png               # Official Pass@1 leaderboard horizontal bar chart
|   |-- eval_pareto_efficiency.png              # Official Token-Efficiency vs Pass Rate Pareto Frontier
|   +-- radar_v1.0_family.png                   # Official 5-axis capability radar chart
|-- benchmark_commandcode_<model>_v1.0_fc.json   # Leaderboard runs: native function calling
+-- benchmark_commandcode_<model>_v1.0_text.json # Same models, ReAct text loop
```

Models: `deepseek-v4-pro`, `glm-5.3-flash`, `mimo-v2.6-flash`, `deepseek-v4-flash`,
`deepseek-v4.1-flash`.

## Summary of Results (v1.0, 63 Tasks, native function calling)

| Model | Total Pass Rate | Solved / Total | Avg Steps | Avg Latency | Update (2) | Log (6) | Evaluate (8) | Recommend (11) | Composite (36) |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **DeepSeek-v4-pro** | **84.1%** | **53 / 63** | 10.9 | 120.5s | 2/2 (100.0%) | 5/6 (83.3%) | 7/8 (87.5%) | 9/11 (81.8%) | 30/36 (83.3%) |
| **GLM-5.3-flash** | **81.0%** | **51 / 63** | 12.2 | 235.4s | 2/2 (100.0%) | 4/6 (66.7%) | 6/8 (75.0%) | 9/11 (81.8%) | 30/36 (83.3%) |
| **MiMo-v2.6-flash** | **81.0%** | **51 / 63** | 13.9 | 216.0s | 2/2 (100.0%) | 5/6 (83.3%) | 6/8 (75.0%) | 8/11 (72.7%) | 30/36 (83.3%) |
| **DeepSeek-v4-flash** | **68.3%** | **43 / 63** | 11.5 | 37.1s | 2/2 (100.0%) | 2/6 (33.3%) | 5/8 (62.5%) | 9/11 (81.8%) | 25/36 (69.4%) |
| **DeepSeek-v4.1-flash** | **58.7%** | **37 / 63** | 11.4 | 40.6s | 2/2 (100.0%) | 5/6 (83.3%) | 4/8 (50.0%) | 7/11 (63.6%) | 19/36 (52.8%) |

> **Note**: One run per model, temperature 0, through the **Command Code** provider plan. Each
> report records the ruler it was measured with (`contract`, `scorer_version`, `loop_version`,
> `prompt_version`, `prompt_fingerprint`); compare two reports only when those agree. The text
> reports were re-judged offline with the same Scorer (`scripts/rescore_report.py`). Single runs
> are noisy: a repeat FC run of DeepSeek-v4.1-flash under the same configuration scored 49 / 63.
> The previous table (Volcano Engine ARK plan, earlier scorer and loop) is kept in git history only;
> GLM-5.3 (flagship) is not offered on the current provider and is not re-measured.

Each benchmark JSON includes complete step-by-step tool actions, observations, latency, token usage, and final state validation tags.
