# 收尾三项：互斥修饰词测试 / judge gate / "1 oz dry"

按 `docs/syntax-integration-design.md` §6 步骤 5a 与 §2.1.2，以及
`reports/gray-zone-probe.md` 的 gate 架构建议。catalog / gold / validator /
materialize_split / react / build_review_sheet 未改。

复跑：

```
.venv/bin/python -m pytest -q
.venv/bin/python scripts/landing_verify.py
```

## 1. 互斥修饰词回归测试

实现已按 §2.1.2 返回 `None`（`_refuses_modifiers` 在主循环前拒绝两个以上
`MODIFIER_KEYS`）。本项只补断言。

| 文件 | 改动 |
|---|---|
| `tests/test_portions.py` | `test_mutex_modifiers_return_none`：`a thick thin steak` / `a thick thin` / `a regular thin steak` → `None` |

测试数：**+3**。

## 2. judge gate 封装

按灰区报告：白名单表值不送 LLM；表外值才 judge；`max_tokens=512`；阈值不降。

| 文件 | 改动 |
|---|---|
| `src/nutrienv/bench/grams_gate.py` | **新建**。导出 `plausibility_gate(food_id, grams, catalog, *, judge=None, k=5, threshold=0.6) -> (bool, str)` |
| `tests/test_grams_gate.py` | **新建**。白名单 / 表外 / 阈值边界 / 空回复重试 |
| `scripts/gray_zone_probe.py` | `call_judge` / `parse_verdict` / `JUDGE_SYSTEM` 改从 `grams_gate` 引入；`run_case` 走共享 `judge_once`（`PARSE_RETRIES=2` 不变） |

白名单候选集复制自 `validator._matches_portion_table`（档位 × {0.5, 1, 1.5, 2} + 固定 2 oz = 56.7 g），源注记在函数 docstring。live catalog 里 steak `piece`/`slice` 也是 30 g，所以表外 30 的测试用迷你 catalog（只挂 `qns=160` / `piece=55`），与任务描述一致。

默认 judge：`deepseek-v4-flash`，temp 0.7，`max_tokens=512`，空回复重试一次，K 次采样，`ok` 比例 ≥ threshold 才接受。`judge` 可注入。

测试数：**+7**（steak 160 表值不调 judge、omelet 55 表值不调 judge、30 走 judge、5×ok、0.6 边界接受、0.4 拒绝、空串后 ok）。

## 3. "1 oz dry" 修复（设计 5a）

语法开始检查单位**之后**的 token。主循环命中单位、算出克数之前，
`_refuses_after_unit` 扫描剩余 token 是否含 `{dry, dried, drying, raw, uncooked, uncook}`。

| 文件 | 改动 |
|---|---|
| `src/nutrienv/world/portions.py` | `_REFUSED_AFTER_UNIT` + `_refuses_after_unit`；主循环在返回克数前调用 |
| `tests/test_portions.py` | `test_refuses_state_words_after_unit` |

| phrase | food | 现在 |
|---|---|---|
| `1 oz dry` | pasta | **None**（原 28.35） |
| `2 oz raw` | pasta | **None** |
| `a cup of uncooked oats` | oats | **None** |
| `2 oz` | pasta | 56.7 不变 |
| `150 g chicken` | pasta | 150 不变 |
| `a cup` | oats | 80.0 不变（ns-oatmeal 的 phrase；`uncooked` 在 query 不在 phrase） |

测试数：**+6**。

## 4. 验证结果

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **271 passed**（基线 255 + 16） |
| `.venv/bin/python scripts/landing_verify.py` | **PASS**：old-key drifts 0；phrase replay 178 equal / 0 differ；`validate_draft` 240/240；oz 拆分 42/42 |
| 207 条 realization phrase 重放 | **202 equal / 5 differ**，5 条与设计 §2.4.4 逐位相同；相对改 `portions.py` 前的快照 **0 条变化** |

5 条变化（均不在冻结 240 里的 `fz-dish-*`）：

| food | phrase | old | new |
|---|---|---:|---:|
| 2706880 | `a sandwich` | 175.0 | 115.0 |
| 2706885 | `a barbecue beef sandwich` | 270.0 | 180.0 |
| 2707196 | `a serving of shrimp egg foo yung` | 175.0 | 131.0 |
| 2707198 | `an omelet` | 55.0 | 110.0 |
| 2708750 | `a serving of lasagna` | 206.0 | 250.0 |

## 5. 测试数汇总

| 项 | 新增 |
|---|---:|
| 互斥修饰词 | 3 |
| judge gate | 7 |
| 单位后拒绝词 | 6 |
| 合计 | 16 |
| 全量 | **271** |
