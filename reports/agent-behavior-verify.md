# 08 — agent 考试行为验证（catalog-v2 + 手册对称）

日期：2026-08-18
范围：测试 + 本报告。未改 `src/`、`data/fdc/*.sqlite`、`data/splits/*.json`。
未跑 live LLM。ReAct 考试路径用确定性 handbook harness 走
`search_foods` → `get_food` → 从 observation 换算 → `log_meal` / `finish`，
再经 `runner._run_episode` 用 Scorer 判 `end state == Oracle`。

复跑：

```
.venv/bin/python -m pytest -q tests/test_agent_behavior_verify.py
.venv/bin/python -m pytest -q
```

## 1. 改了哪些文件

| 文件 | 改动 |
|---|---|
| `tests/test_agent_behavior_verify.py` | **新增**。catalog-v2 工具观察、runner 口语题、手册对称、灰区三对、旧 SR 缺席、QNS 交叉核对 |
| `reports/agent-behavior-verify.md` | 本报告 |

## 2. 验收

| 项 | 结果 |
|---|---|
| 1 `search_foods "chicken"` / `get_food` 返回 catalog-v2，portions 含口语档 | **分项**。search 命中全是 `survey_fndds_food`，无旧 SR。`get_food 2705956` piece=105；`get_food 2706311` can=75；slug `chicken_breast` → 2705956。`q="chicken"` 的 BM25 top 25 **不含** 2705956，见 §4 |
| 2 典型 query 经 runner，end state == Oracle | **通过（确定性 handbook harness，非 live LLM）**。从 query 去掉 log 祈使后，用 get_food observation 换算：`a piece of chicken`→105；`150 g of chicken`→150；`one apple`→165；`half a cup of milk`→122（表值 cup=244/2）。裸 `a chicken breast` 不写 ledger（ticket 02） |
| 3 手册对称 + 灰区重跑 | **通过（表值 + resolve_portion，未跑 live judge）**。v1 手册含 `one apple` / `a chicken breast` / `portions.piece` / `portions.qns`；`resolve_portion` 与上表字面量一致。sandwich 175/115、lasagna 206/250、omelet 55/110 在 catalog-v2 仍成立 |
| 4 旧 SR id 不出现 | **通过**。10 个旧 staple SR id（171477 等）不在 catalog-v2；`get_food` 为 `unknown_food`；chicken/tuna/tofu/salmon/shrimp/beef 的 search 命中不含这些 id |
| 5 QNS 交叉核对 | **记录如下**（06 Opus 观察落实） |
| 6 pytest | 见第 5 节 |

ticket 写 `"half a cup of milk"→QNS`：catalog-v2 `milk_whole` 的 `qns=244` 与 `cup=244` 是同一档。半杯走 cup 键，oracle 字面量是 **122.0**，不是把 QNS 整档（244）当成半杯。

## 3. QNS vs first-wins（供 11a）

first-wins 口语锚点是 FNDDS `food_portion` 最小档（small→large seq）。QNS 是 modifier 90000，给 `"a serving"`，不给 `"a piece"` / `"a can"`。

| staple | FNDDS id | first-wins 口语键 | QNS | 差 | 口语短语 |
|---|---|---|---|---|---|
| chicken_breast | 2705956 | piece=**105**（1 small breast） | **120** | QNS 高 15 g（1.14×） | `a piece`→105；`a serving`→120 |
| tuna | 2706311 | can=**75**（1 small can） | **85** | QNS 高 10 g（1.13×） | `a can`→75；`a serving`→85 |
| beef | 2705855 | piece=**65**（1 small patty） | **85** | QNS 高 20 g（1.31×） | `a piece`→65；`a serving`→85 |

Phase 6 若把 serving/QNS 当成 piece/can 的 oracle，会系统偏高；若只采 first-wins 最小档，会系统偏低。两边都是表值，不是 LLM 数。11a 选题时必须先定短语再定键，不能混用。

tuna 相对旧 SR can=165 仍是 2.2× 下降（75 vs 165），与 06 dry-run 一致。本票未改 catalog。

## 4. 非阻塞观察：`search_foods "chicken"` 不把 staple 排进 top 25

BM25 `q="chicken"` 在 catalog-v2 / catalog-v1 / catalog.sqlite 上都是 410 条量级命中，top 25 是 chicken roll / back / tail / skin / feet 等短名，**不含** 2705956（也不含旧 171477）。`_promote_alias_hits` 只重排已返回的 25 条，补不进 staple。

`q="chicken breast"` 或 `get_food("chicken_breast")` 才落到 2705956。runner 用例里 handbook harness 在 search 之后对 staple slug 做 `get_food`（手册允许 staple slug），换算仍只读 observation。这不是 catalog-v2 回归；11 若要裸 "chicken" 搜到胸肉，需另开 search 票。

## 5. 验证

| 检查 | 结果 |
|---|---|
| `tests/test_agent_behavior_verify.py` | **11 passed** |
| 全量 pytest | **1019 passed**（ticket 06 基线 1008 + 本票 11） |
| 生产代码 | 无 |
| live ReAct / judge LLM | 未跑（确定性考试路径；灰区只重跑表值 + resolve_portion） |
