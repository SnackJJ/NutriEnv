# NutriEnv Evaluation Reports

This directory contains the official evaluation trajectories, metrics, and visualization assets for **NutriEnv v1.0**.

## Directory Structure

```text
reports/
|-- assets/
|   |-- eval_leaderboard_bars.png               # Official Pass@1 leaderboard horizontal bar chart
|   |-- eval_pareto_efficiency.png              # Official Token-Efficiency vs Pass Rate Pareto Frontier
|   +-- radar_v1.0_family.png                   # Official 5-axis capability radar chart
|-- benchmark_ark_deepseek-v4-pro_v1.0.json     # DeepSeek-v4-pro evaluation trajectories & metrics
|-- benchmark_ark_glm-5.3_v1.0.json             # GLM-5.3 (Flagship) evaluation trajectories & metrics
|-- benchmark_ark_deepseek-v4-flash_v1.0.json   # DeepSeek-v4-flash evaluation trajectories & metrics
+-- benchmark_ark_glm-5.3-flash_v1.0.json       # GLM-5.3-flash evaluation trajectories & metrics
```

## Summary of Results (v1.0, 63 Tasks)

| Model | Total Pass Rate | Solved / Total | Avg Steps | Avg Latency | Update (2) | Log (6) | Evaluate (8) | Recommend (11) | Composite (36) |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **DeepSeek-v4-pro** | **77.8%** | **49 / 63** | 12.9 | 167.5s | 2/2 (100%) | 5/6 (83.3%) | 6/8 (75.0%) | 9/11 (81.8%) | 27/36 (75.0%) |
| **GLM-5.3 (Flagship)** | **76.2%** | **48 / 63** | 14.6 | 112.2s | 2/2 (100%) | 5/6 (83.3%) | 6/8 (75.0%) | 9/11 (81.8%) | 26/36 (72.2%) |
| **DeepSeek-v4-flash** | **69.8%** | **44 / 63** | 11.0 | 248.9s | 2/2 (100%) | 6/6 (100.0%) | 7/8 (87.5%) | 8/11 (72.7%) | 21/36 (58.3%) |
| **GLM-5.3-flash** | **65.1%** | **41 / 63** | 10.9 | 59.5s | 2/2 (100%) | 4/6 (66.7%) | 4/8 (50.0%) | 7/11 (63.6%) | 24/36 (66.7%) |

> **Note**: All models in this benchmark suite were evaluated by invoking model endpoints provided by **Volcano Engine (火山引擎) Agent Plan**.
Each benchmark JSON includes complete step-by-step tool actions, observations, latency, token usage, and final state validation tags.
