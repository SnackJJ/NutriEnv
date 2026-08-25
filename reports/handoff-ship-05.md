# Handoff — ship-05：ADR 0017 mill 单题通道落地（2026-08-25）

一句话：**旧 v1.0 生成脚本全部归档；新生成管线只有一条单题入口 `generate_one`，
本 session 补上 live anchor seam、colloquial overlay、query-only log expander，
测试 1361 passed。**

`main` = `9479f79`（前一 commit `032fd1f` 是归档，再前 `39c8001` 是 catalog-v2 重建）。

---

## 1. 本轮落地

| commit | 内容 |
|---|---|
| `032fd1f` | 归档 `generate_batch.py` / `phase6_generate.py` / `run_pilot_20.py` / `smoke_expander_models.py` 及两个活测试；新增反转测试 `tests/archive/test_old_pipeline_archived.py`；`test_pilot_20.py` 改从 `scripts/archive/` 导入 |
| `9479f79` | 新单题 CLI + live anchor + colloquial overlay + query-only log expander + ADR 0018 |

### 1a. 归档（`032fd1f`）

- 4 个旧脚本移入 `scripts/archive/`（`git mv`，历史保留）。
- `tests/test_generate_batch.py` / `tests/test_phase6_generate.py` 移除；
  `tests/archive/test_old_pipeline_archived.py` 断言旧脚本不在 live `scripts/` 且
  新入口 `scripts/generate_one_cli.py` 存在（项目惯例：归档 ≠ 删除）。
- `tests/archive/` 按 `norecursedirs=["archive"]` 不参与日常 pytest（先例保持）。

### 1b. 新单题入口（`9479f79`）

`scripts/generate_one_cli.py`，ADR 0017 `{query, foods}` 契约：

```
.venv/bin/python scripts/generate_one_cli.py --synthetic --seed 0   # offline tracer
.venv/bin/python scripts/generate_one_cli.py --family log --seed 7   # live Qwen
.venv/bin/python scripts/generate_one_cli.py --family evaluate --tier single --seed 4
.venv/bin/python scripts/generate_one_cli.py --family log --seed 7 --anchor  # live anchor
```

- log seed 0 synthetic 接受（`one-log-0000`，oracle 120g = Burrito cup 表值）；
- evaluate seed 4 synthetic 接受（`one-eval-0004`）；
- 不支持 `--synthetic --anchor`（fail-closed 退出）。

### 1c. Live gram_anchor

- `generate_one` 新增 `gram_anchor` 参数，贯穿到 `_bind_log_foods`：
  `resolve_portion` 解析不了时 anchor 提议克数 → `matches_portion_table`
  白名单否决 → 拒绝 reason 仍是 `unresolvable`（fail-closed）。
- `gram_anchor.py`：`LlmGramAnchor` 提示词要求 JSON `{quantity, key}` 或
  `{grams}`，代码解析并对自己的 portion 表乘算；异常/坏形状回 None。
- 测试：表内提议 60g（2×qns 30）接受、表外 99g 拒绝、anchor 异常拒绝且
  自然 query 保留。

### 1d. Colloquial overlay

`data/portion/colloquial_portion_overlay.json`（versioned data，不内嵌克数）：

| 口语 | base key × multiplier | 效果 |
|---|---|---|
| handful | oz × 1 | 28.35g（坚果/莓类） |
| fist / fist-sized | cup × 1 | 食物自身 cup 值 |
| palm / palm-sized | oz × 3 | 85g 熟肉 |
| deck of cards | oz × 3 | 85g 肉/鱼 |
| dollop | tbsp × 2 | 30g 酱/乳 |
| splash | tbsp × 1 | 15g 液体 |
| drizzle | tsp × 1 | 5g 油/糖浆 |

base key 缺失 → `None`（不猜）。`_collapse_unit_bigrams` 处理
fist-sized / palm-sized / deck of cards（含三词）。

### 1e. Query-only log expander

- `generate_one` 的 `build_log_user_prompt` 现在逐食物列出可说话语的表档
  （`phrase = grams`），LLM 只能讲池内表档口语，克数仍全部代码绑定。
- `build_log_system_prompt` 增加自然餐语风格块 + 9 个食物专属单位 +
  7 个口语单位词表；保留 "unspecified 不教 serving-of""explicit 可写 150 g"
  两处已有不变式。
- `_speech_amount_path` 修复：新九单位 + 口语单位按 named_measure 分类，
  否则永远走不到 anchor。

### 1f. ADR 0018（补授权）

catalog-v2 裁决第六节记录的 `a chicken breast` None→105g 属于当时"记录
未批准"的范围；ADR 0018 正式授权：cut noun 只在"食物名带该 cut 且
portions.piece 存在"时按 piece 计数，否则 `None`。

---

## 2. 测试

```
1361 passed in ~49s
```

新增测试：`tests/test_generate_one_cli.py`（4）、
`tests/test_generate_one_gram_anchor.py`（3）、
`tests/test_portions.py` colloquial 段（1 段 10 断言）。

---

## 3. 留给下个 session（按优先级）

1. **Live probe 跑通真 LLM**（需要 API keys）：`generate_one_cli.py --family log`
   和 `--family evaluate` 各跑几题，确认 expander + anchor 的 live 行为；
   目前只验证了 synthetic tracer 和注入 fake complete 的 seam。
2. **Beverage 显式 id 清单**（Opus 裁决 Q2 backlog）：194 个带 fl_oz 但
   `_is_beverage_name=False` 的食物一次性分诊成显式饮料 id 清单，
   `_is_beverage_name` 退化为查表 + 名称启发式兜底。
3. **batch 编排**：单题 verify 后在这条新 CLI / `generate_one` 之上再谈
   batch，不动旧 `run_batch.py` 的旧契约面（旧 run_batch 仍被 live 测试钉住）。
4. **旧 expander 合同收尾**：`expander.LlmExpander`（`{items:[{expression}]}`）
   仍被 `run_batch.py` 和 `tests/test_expander.py`/`test_run_batch.py` 引用；
   等新通道生产稳定后决定是退役还是保留为历史 seam。
