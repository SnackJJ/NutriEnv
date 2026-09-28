# NutriEnv Evaluation Reports

This directory contains the official evaluation trajectories, metrics, and visualization assets for **NutriEnv v1.0**.

## Directory Structure

```text
reports/
|-- assets/
|   |-- eval_leaderboard_bars.png               # Official Pass@1 leaderboard horizontal bar chart
|   |-- eval_pareto_efficiency.png              # Official Token-Efficiency vs Pass Rate Pareto Frontier
|   +-- radar_v1.0_family.png                   # Official 5-axis capability radar chart
|-- benchmark_commandcode_<model>_v1.0_fc_r<k>.json # Leaderboard runs (one file per complete run): native function calling
+-- benchmark_commandcode_<model>_v1.0_text.json    # Same models, one run on the ReAct text loop
```

Models: `deepseek-v4-pro`, `glm-5.3-flash`, `mimo-v2.6-flash`, `deepseek-v4-flash`,
`deepseek-v4.1-flash`.

## Summary of Results (v1.0, 63 Tasks, native function calling, mean over complete runs)

| Rank | Model | Mean Pass Rate | Mean Solved / 63 | Runs | Avg Steps | Avg Latency | Update (2) | Log (6) | Evaluate (8) | Recommend (11) | Composite (36) | text-json (1 run) |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | **MiMo-v2.6-flash** | **84.1%** | **53.0** | 51 / 55 | 13.9 | 329.6s | 100.0% | 75.0% | 87.5% | 81.8% | 84.7% | 43 / 63 |
| 2 | **DeepSeek-v4-pro** | **81.7%** | **51.5** | 53 / 50 | 10.8 | 100.6s | 100.0% | 66.7% | 75.0% | 81.8% | 84.7% | 54 / 63 |
| 3 | **GLM-5.3-flash** | **81.0%** | **51.0** | 51 | 12.2 | 235.4s | 100.0% | 66.7% | 75.0% | 81.8% | 83.3% | 53 / 63 |
| 4 | **DeepSeek-v4-flash** | **74.6%** | **47.0** | 43 / 51 / 47 | 11.8 | 36.8s | 100.0% | 72.2% | 66.7% | 84.8% | 72.2% | 44 / 63 |
| 5 | **DeepSeek-v4.1-flash** | **68.3%** | **43.0** | 37 / 49 / 43 | 11.7 | 42.6s | 100.0% | 77.8% | 70.8% | 75.8% | 62.0% | 44 / 63 |

> **Note**: temperature 0, through the **Command Code** provider plan. Family columns pool each
> model's complete runs. Each report records the ruler it was measured with (`contract`,
> `scorer_version`, `loop_version`, `prompt_version`, `prompt_fingerprint`); compare two reports
> only when those agree. The text reports were re-judged offline with the same Scorer
> (`scripts/rescore_report.py`). Runs are noisy (DeepSeek-v4.1-flash: 37 / 49 / 43), and run counts
> differ: further runs that hit the provider's usage limit part-way (HTTP 429 voids) are excluded.
> The previous table (Volcano Engine ARK plan, earlier scorer and loop) is kept in git history
> only; GLM-5.3 (flagship) was not re-measured.

Each benchmark JSON includes complete step-by-step tool actions, observations, latency, token usage, and final state validation tags.
