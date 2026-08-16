# 语法接入落地报告

按 `docs/syntax-integration-design.md` 实施（用户任务：步骤 1 + 步骤 3 + 手册 + §5 测试 + 本报告）。
catalog / gold / `realizations.py` / `validator.py` / `materialize_split.py` 未改。

复跑：

```
.venv/bin/python -m pytest -q
.venv/bin/python scripts/landing_verify.py
```

## 1. 改了哪些函数

| 文件 | 符号 | 改动 |
|---|---|---|
| `src/nutrienv/world/portions.py` | 模块 docstring | serving 默认改为 QNS；补修饰词说明 |
| 同上 | `UNIT_SYNONYMS` | 增 `fl_oz` / `floz`；注明 catalog 不写 `serving` 键 |
| 同上 | `UNIT_BIGRAMS` | **新增**。`fl oz` / `fluid ounce(s)` 塌缩 |
| 同上 | `MODIFIER_KEYS` / `REFUSED_MODIFIERS` | **新增**。按 §2.1.2 原文 |
| 同上 | `resolve_portion` | tokenize 后 bigram 归一化；拒绝词 / 互斥修饰词；serving 路径绑修饰词；显式量具 + 修饰词返回 `None` |
| 同上 | `_serving_default` | 键序 `qns → piece → slice → cup`；docstring 同步 |
| 同上 | `_dish_noun_grams` | 数量跨度扫修饰词，命中同名 catalog 键 |
| 同上 | `_collapse_unit_bigrams` / `_refuses_modifiers` / `_span_modifier` / `_without_modifiers` | **新增** 辅助 |
| `src/nutrienv/harness/react.py` | `_SYSTEM_V1_TAIL` | 整段替换为设计 §4.1 文案 |
| `scripts/build_review_sheet.py` | `_EXPLAIN_UNITS` | 派生自 `UNIT_SYNONYMS` → 显式白名单（§2.3.1 要求与 `fl_oz` 同变更；见 §6） |
| `tests/test_portions.py` | 若干 `test_*` | §5.1–5.5 + omelet 55 白名单回归 |
| `tests/test_review_sheet.py` | `test_explain_grams_is_not_stolen_by_fl_oz` | §6 步骤 1 验收 4 |

`_leading_quantity` **未改**。空跨度守卫仍是 `if not run: return None`；修饰词在送入前被剔除。

## 2. 新语法规则（与设计逐条对应）

### 2.1 修饰词 thick / thin / regular — §2.1.2

不进 `UNIT_SYNONYMS`。只绑定「食物本身即单位」：

- 修饰词 + serving/portion/bowl/plate/order，且 `portions[修饰词]` 存在 → `quantity ×` 该键
- 修饰词 + dish-noun（食物名含该名词），且键存在 → 同上
- 修饰词 + 显式量具（cup/tbsp/tsp/slice/piece/can/g/oz/fl_oz）→ `None`
- 键不存在 / 修饰词单独出现 / 两个互斥修饰词 → `None`
- `REFUSED_MODIFIERS`（large/big/small/medium/…）任何位置 → `None`

§1.3 缺陷已修：`"a thick steak"` 不再静默返回 30.0，现为 240.0；`"a large steak"` 从 30.0 变为 `None`。

### 2.2 fl_oz — §2.3.1

`_tokenize` 之后 bigram 归一化，必须在 `OUNCE_UNITS` 分支之前。`"an ounce"` 仍走常量 28.35，不被 `fl_oz` 抢走。

`oz` / `oz_yield` / `cubic_inch` 不进语法（§2.2、§2.3.2）。

### 2.3 qns 作 serving 默认 — §2.4 / §3

`_serving_default` 键序改为 `qns → piece → slice → cup`，serving 词与 dish-noun 共用。不写 `serving` 键。无 qns 的 fixture（`tests/test_portions.py` 的 `_dish_catalog`）自动落到 piece/slice/cup，原 10 条断言仍成立。

点名抽查（设计 §6 步骤 3 第 6 条）：

| 食物 | 新 serving | 说明 |
|---|---|---|
| `oats` | 10.0 | 已知退化，断言现状 |
| `spinach` | 13.0 | 同上 |
| `orange` | 154.0 | 原 15.0（一瓣） |
| `broccoli` | 45.0 | 原 10.0 |
| `peanut_butter` | 32.0 | 原 `None` |
| `2706880` sandwich | 115.0 | 原 175.0（大号 piece） |

抽查结论：`oats`/`spinach` 型退化按设计保留，不回滚、不特判。

### 2.4 手册 — §3 / §4.1 / §4.2

`_SYSTEM_V1_TAIL` 使用设计 §4.1 原文。列出 thick/thin/regular、fl_oz、`a serving of X` 读 `portions.qns`。`oz_yield` / `cubic_inch` 只作为 "do not convert" 反例。

## 3. 测试

基线 213。新增 42，合计 **255 passed**。

| 组 | 条数 | 来源 |
|---|---:|---|
| 修饰词 M1–M15 | 15 | §5.1 |
| fl_oz F1–F6 | 6 | §5.2 |
| serving/qns Q1–Q14 | 14 | §5.3 |
| 负向 N1–N4 | 4 | §5.4 |
| 手册对称 | 1 | §5.5 |
| omelet piece=55 白名单 | 1 | 灰区回归：55 是表值，不送 judge |
| gloss 不被 fl_oz 抢走 | 1 | §6 步骤 1 验收 4 |

## 4. 验证结果

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **255 passed** |
| `.venv/bin/python scripts/landing_verify.py` | **PASS**：old-key drifts 0；phrase replay 178 equal / 0 differ；`validate_draft` 240/240；oz 拆分 42/42 |
| `gray_zone_probe.confirm_catalog()` | 三对表值未变（sandwich 175/115、lasagna 206/250、omelet 55/110）。脚本未改。未重跑 55 次 live judge（与本次语法正交；catalog 门已确认） |

旧键零漂移保持。gold 240 的 phrase 都不走 `_serving_default`，故 qns 改序对冻结 split 零影响。

## 5. 与设计文档的偏差（必须记录）

1. **步骤 2 未做**（review sheet / 差距审计复跑）— 用户任务未列入。
2. **步骤 4 的 ADR / `llm-generated-exam-data.md` / `landing-report.md` 未改** — 用户指定只产出本报告。
3. **`scripts/build_review_sheet.py::_EXPLAIN_UNITS`** — 用户文件白名单未列此文件，但设计 §2.3.1 / §6 步骤 1 写明必须与 `fl_oz` 同变更。不加白名单时 `fl_oz` 会经 `UNIT_SYNONYMS.values()` 进入 gloss，`milk_whole` 122 g 变成 `4 x fl_oz`，`test_grams_explained_is_derived_when_unit_unspoken` 变红。已按设计改成显式白名单 `cup/tbsp/tsp/slice/piece/can/serving/g/oz`。
4. **全库退化指标**（`<5 g` ≤ 50、`>1000 g` ≤ 8、可解析 serving = 8795）本轮未复跑 — 只改解析器回退顺序，不改 catalog。
5. **步骤 5 全部不做**（dry/raw、cubic_inch、oz_yield、validator 锚点收窄）。

## 6. 函数一行清单（回报用）

`resolve_portion`，`_serving_default`，`_dish_noun_grams`，`_collapse_unit_bigrams`（新），`_refuses_modifiers`（新），`_span_modifier`（新），`_without_modifiers`（新），`_SYSTEM_V1_TAIL`，`_EXPLAIN_UNITS`。
