# v2 造题流水线：各 family 通道收尾 + 首批 sample 验收

日期：2026-08-27。目标顺序：先把各 family 的生成 pipeline 写完 → 跑通并产出各 family sample → 验收质量 → 再谈 batch → 最后冻结 v2-gold。

本报告只覆盖前两步（写完 + 跑出 sample + 机械验收）。**未冻结任何 split，未切 `EXAM_SPLIT_PATH`。**

## 1. 本轮补齐的 pipeline 缺口

`generate_one`（ADR 0017 单题入口）原本五条 family 代码路径都在，但有两个"能写但无法驱动"的缺口：

1. **Evaluate 只能依赖 LLM 恰好组出一顿 fit 的菜**（实测 live fit 命中极低）。本轮新增：
   - `search_fit_plate(pool, profile, catalog, occasion, ...)`：代码在池内搜索 1–3 个食物、数量=1.0 PortionFact 组合，要求 `bind_evaluate_reasons == ()`（六窗口 + 过敏原全过）。克数全部来自餐桌，LLM 不参与。
   - `generate_one(..., items=...)`：evaluate-only 的"作者指定盘子"通道。给定 code-chosen plate，走 rewriter 写 query；给定 `knife` 则从 fit 盘应用 `allergy/over_slot/under_slot/swap` 产出 unfit 盘。
2. **单题 CLI 无法表达 template/场景/knife/复合步骤**。`scripts/generate_one_cli.py` 新增：
   - `--shell` `--slots` `--scene` `--steps` `--knife` `--last-meal`
   - `--knife` 时自动接 live rewriter（synthetic 下明确报错，fail-closed）。

3. **Log expander 提示词加固**（live 侧）：
   - named_measure 明确"不要在量具旁再写克数"；
   - 新增 binding rules：逐食物 verbatim 使用池内 speakable portions、不得改菜名（禁止 "with gravy"/"on a pancake"）、不得同时写两种量。

## 2. 新增 sample 入口（不是 batch）

`scripts/generate_samples.py`：每个 family 循环跑 `generate_one`，达到 N 个 accepted 即停，并对每个 accepted Task 跑两道机械验收：

- `validate_draft(task)`（漏题/可达/过敏原/composite 等）
- `validate_oracle_grams(task)`（每个克数都有餐桌锚点）

任一 gate 非空 → 该 draft 记 rejection（`validation:` 前缀），不计入 accepted。输出写 `.scratch/v2-samples/samples.json`（synthetic）和 `.scratch/v2-samples/live-log.json`（live）。

## 3. 跑通结果

### 3.1 synthetic（确定，全 family 覆盖）

```
$ .venv/bin/python scripts/generate_samples.py --count 3 --max-attempts 60
log:        3 accepted / 4 attempts
evaluate:   3 accepted / 18 attempts
recommend:  3 accepted / 4 attempts
update:     3 accepted / 3 attempts
composite:  3 accepted / 4 attempts
# 15 accepted, 每个 validation: {draft: [], grams: []}
```

样本要点（完整清单见 `.scratch/v2-samples/samples.json`）：

| family | sample 形态 | 验收 |
|---|---|---|
| log | explicit grams / QNS bowl / mixed；`Burrito 120g`、`Beef 60g`、`Egg sandwich 270g` | draft+grams 全过 |
| evaluate | fit（accept）＋ under_slot（reject `sodium_mg_hi`）＋ allergy（reject `allergy,kcal_hi`） | draft+grams 全过 |
| recommend | lunch/dinner shell（S0 承担难度，query 普通） | draft+grams 全过 |
| update | add-allergy / weight / phase-cut | draft+grams 全过 |
| composite | log→recommend 双 oracle 复合 | draft+grams 全过 |

### 3.2 live（真实 LLM 冒烟，Qwen / kimi 轮换）

```
$ ... scripts/generate_samples.py --family log --count 2 --max-attempts 6 --live ...
log: 1 accepted / 6 attempts
```

- 唯一 accepted 样本：`"For dinner I had two pieces of Pizza with a cup of Brussels sprouts."`，克数锚定 `Pizza piece×2=298g`、`Brussels sprouts cup=160g`，draft+grams 全过。
- 5 个 rejected 全是 pipeline 正确 fail-closed：4×`amount_path`（LLM 混写量具与克数/写 serving）、1×`unresolvable`（`"a serving = 180g"`）。

**结论：确定性通道已完整跑通；live 通道管道正确，但 LLM 是否遵守"verbatim 餐桌措辞"是当前最大波动源（这正是 gate 该干的活——把坏候选挡掉）。**

## 4. 质量验收

- `pytest -q`：**1374 passed**（含新增 `tests/test_generate_one_items.py` 5 例）。
- 每个 accepted sample 的 `validate_draft` + `validate_oracle_grams` 均空；后者保证所有 Oracle 克数都有餐桌锚点（Pass ⇔ end state == Oracle 的零克数漂移前提）。
- 全 family `scripts/family_probe.py` 无回归：log 10/12、evaluate 1/12（本通道现在用 items/search 补强）、recommend 12/12、composite 10/12、update 6/6+6/6。

## 5. 下一步（按用户顺序继续）

1. **live 对齐**：把 log/evaluate 的 live expander 接受率提上来（更硬的 few-shot/回退校验），或接受目前"低接受率 + 过采样"模式直接进 batch。
2. **batch**：在 `generate_samples.py` 的 recipe 之上做配额编排（48/72/48/36 + 36 composite admission），不动旧 `run_batch.py`。
3. **review harness** 两阶段 committee 接上 batch 产物。
4. **冻结**：产出集齐 → 人审 → freeze 为 `data/splits/v2-gold.json` → 改 `EXAM_SPLIT_PATH`（届时 split.py 的 fail-closed 白名单也要补版本）。

## 6. 未做 / 刻意不做

- 未切 `EXAM_SPLIT_PATH`，未建 `v2-gold.json`。
- swap knife：代码在，但 catalog-v2 池子里 iso-caloric 替换几乎打不出 `fat_g_hi/fiber_g_lo`（0/抽样命中），留到 batch 阶段用更多池解决；samples 集不含 swap unfit。
- beverage 显式 id 清单（handoff backlog）仍未做，属 batch 前的 catalog 工作，不影响 sample 通道。
