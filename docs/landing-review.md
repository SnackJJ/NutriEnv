# FNDDS 安全叠加落地终审

审查固定点：`HEAD b7dc8a2697c78464df48cdb2b79a23065ddf769f`。审查范围为当前工作树中的 `scripts/build_fdc_catalog.py`、`scripts/build_review_sheet.py` 和重建后的 `data/fdc/catalog.sqlite`；`materialize_split.py` 不在本次范围内。

## 结论

**当前 diff 不建议按原样落地。** 验收清单第 1、2、6 条 PASS，第 5 条 FAIL。存在两个阻断问题：`fl_oz` 把 3 个“整份容器/食品（N fl oz）”的总克数误存成每 `fl_oz` 克数；新写入的 `serving` 已被现有 `resolve_portion` 直接读取，却没有同步手册和 phrase 测试。此外，review sheet 将任意 catalog SHA 不一致降级为警告，会掩盖未经验证的真实漂移。

## Findings

### [高] `fl_oz` 匹配未限定为 `1 fl oz`，已有 3 个错误 winner 落库

`scripts/build_fdc_catalog.py:262-263` 使用 `_FL_OZ.search(desc_l)`，会匹配描述中任意位置的 `fl oz`，而不是报告声明的“`1 fl oz…` 行”。全量扫描 FNDDS 原行发现 180 条非 `1 fl oz` 开头的行也会产出 `fl_oz`；按 overlay 排序和 first-wins 后，有 3 个 live catalog winner 确定错误：

| fdc_id | 原描述 | 实际写入 |
|---|---|---:|
| `2705640` | `1 Snickers bar (2 fl oz)` | `fl_oz=50` |
| `2705656` | `1 soda (10 fl oz)` | `fl_oz=240` |
| `2705657` | `1 soda (10 fl oz)` | `fl_oz=240` |

这些 gram weight 是整根/整杯的总重，不是 1 fluid ounce 的克数。它与 `reports/landing-report.md:42`、`:58` 的来源声明不符，也使“新键数据层安全叠加”本身含有错误事实。应将匹配锚定为实际 `1 fl oz` 单位行，并重建 catalog 后重跑统计。

### [高] 验收 5 未满足：`serving` 不是“尚未进入语法”的死键

`scripts/build_fdc_catalog.py:274-275` 新增 `serving`，而 `src/nutrienv/world/portions.py:49-51,118-127` 已将 `serving/portion/bowl/plate/order` 映射并优先读取 `portions["serving"]`。因此这 5 个新值已经改变 query 解析，不是可延期处理的纯 catalog 键：

| fdc_id | 落地前 `1 serving` | 落地后 `1 serving` |
|---|---:|---:|
| `2706445` | `None` | `258` |
| `2706468` | `None` | `95` |
| `2707537` | `None` | `45` |
| `2707538` | `None` | `45` |
| `2710613` | `None` | `17` |

`reports/landing-report.md:53` 的“尚未接入 `UNIT_SYNONYMS`”和 `:81` 的“例外风险、以后单独立项”不能满足 `docs/adjudication-report.md:228-230` 的原子对称要求。必须在同一变更中补齐 react.py 手册和 phrase→key→grams 测试，或本轮不写 `serving`。

### [中] catalog SHA 无条件降级会掩盖真实漂移

`scripts/build_review_sheet.py:493-501` 对任何 SHA 不一致都只打印 stderr 警告，随后用 live catalog 生成 review sheet；代码没有证明差异仅为本次已验证的 safe overlay，输出还继续记录 split 中的旧 `catalog_sha256`。这会让任意损坏、错误重建或未来语义漂移绕过该脚本原有的完整性边界。当前 `load_split()` 自身也不校验 SHA，因此这里原本是 review sheet 唯一的 catalog 身份检查。

允许已知安全叠加 catalog 用于专项 review 是合理需求，但无条件放行不合理。应改为显式 opt-in，或校验受批准的新 digest/零漂移证明；默认仍应失败。

### [低] phrase 重放报告并非全部“按 query 精确匹配”

`scripts/landing_verify.py:113-133` 在 query 未命中时还会按 item id 推导 seed。独立统计显示 178 次重放中 177 次来自 query 精确匹配，1 次来自 seed 回退。因此 `reports/landing-report.md:91` 的“按 query 匹配到 Row”不完全准确。该 1 次结果仍相等，不影响验收 6 的零漂移结论，但报告应说明匹配口径。

## `build_fdc_catalog.py` 核对

### 旧键冻结与陷阱 A

**PASS。** 原 `_collect_portions` / `_portion_key` 未改，仍按 ZIP 行序 first-wins。用原始 survey ZIP 重跑 legacy scan，并与 live catalog 全量比较：已有 `cup/tbsp/tsp/slice/piece/can` 值变化为 **0**；新增旧键共 **104** 个，全部是 `piece`，且每个都能对应到同 fdc_id、同 gram weight 的 FNDDS 原始复合 `piece/slice` 行。普通 overlay 行新增旧键为 **0**。

当前 `_overlay_keys()` 的控制流先识别原始 description 同时含 piece 与 slice，除此之外遇 household 单位即返回空；所以现实现满足严格版 (a)。`_apply_safe_overlay()` 的兜底对 `cup/tbsp/tsp/can` 会硬失败，但对 `piece/slice` 只按键名放行、没有再次断言来源确为复合行；因此它是部分兜底，当前正确性仍依赖 `_overlay_keys()` 不回归。

抽查结果：

- steak `2705824`：`slice=30`、`cup=135` 保持，补入 `piece=30`；
- cheddar `2705709`：`slice=21`、`cup=132` 保持；
- apple `2709215`：`piece=200` 保持。

### 复合 `piece/slice`

**PASS。** 双写条件只检查 FNDDS 原行的 `portion_description`，必须同时含 piece 与 slice；modifier 单独出现这些词不会触发。`_merge_portion()` 对已存在键 no-op，因此独立旧值不会被复合行覆盖。全量结果为 104 个 `piece` 补缺、0 个 `slice` 补缺、0 个非复合来源补缺。

### `oz` / `oz_yield` / `fl_oz`

`oz` 与 `oz_yield` 的拆分 **PASS**：只有 description 以 `1 oz` 开头才进入此分支，包含 `yield` 归 `oz_yield`，否则归 `oz`；包装/餐重中间出现的 `oz` 不会进入。原始 ZIP 中 42 个同时含物理 oz 与 yield oz 的食物，在 catalog 中全部同时带 `oz` 和 `oz_yield`，缺失为 0。`resolve_portion` 的口语 oz 仍固定为 28.35 g。

`fl_oz` 单独 **FAIL**，原因见 Findings：搜索未锚定，报告所称的 `1 fl oz` 限制没有实现。

### 新键与 catalog 统计

键集合与报告列出的 `qns/fl_oz/regular/cubic_inch/oz_yield/oz/thin/thick/serving` 一致，live catalog 的覆盖食物数也逐项复现：

| key | 食物数 |
|---|---:|
| `qns` | 5326 |
| `fl_oz` | 631 |
| `regular` | 453 |
| `cubic_inch` | 382 |
| `oz_yield` | 304 |
| `oz` | 242 |
| `thin` | 56 |
| `thick` | 54 |
| `serving` | 5 |

至少增加一个新键的 FNDDS 食物为 5393；总食物数 13224（FNDDS 5431 + SR 7793），alias 数 27，均与报告一致。计数一致不消除上述 3 个 `fl_oz` winner 的语义错误。

## `build_review_sheet.py` 核对

- SHA 降级：**不合理，可能掩盖真实漂移。** 详见中风险 finding。安全叠加这一特例不足以证明任意未来不一致都安全。
- `explain_grams` 白名单：**合理，未发现新增误导。** `_EXPLAIN_UNITS` 只保留 resolver 的表单位，并为固定 `g/oz` 补齐；候选 gloss 最后还调用 `resolve_portion()` 做相等性复核。`qns/oz_yield/fl_oz/thick/thin/regular/cubic_inch` 不会被展示成 resolver 实际无法解析的单位。`serving` 会被保留，因为 resolver 确实认识它；这也进一步证明验收 5 的问题是真实语法变化，而非展示假象。

## 独立复算

执行：

```text
.venv/bin/python scripts/landing_verify.py
gold foods: 25
old-key drifts: 0
phrase replay: 178 equal, 0 differ, 145 items unmatched/no phrase
validate_draft: 240 items, 0 failing
oz/oz_yield conflicts in FNDDS: 42; unsplitting: 0
RESULT: PASS

.venv/bin/python -m pytest -q
213 passed in 130.77s
```

三项验收结果可复现；pytest 数量与报告的 213 一致。专项 SQL/ZIP 复算也确认 42/42 冲突食物同时带两键，以及上述 steak/cheddar/apple 值。

## 验收清单 1 / 2 / 5 / 6

| 条目 | 结论 | 理由 |
|---|---|---|
| 1. 旧键类目写入路径收口 | **PASS** | 全量已有旧键 0 变化；104 个旧键新增全为复合原行补 `piece`；普通行新增旧键 0。断言对 piece/slice 的来源约束不是独立兜底，但当前组合控制流有效。 |
| 2. `oz` / `oz_yield` 语义拆分 | **PASS** | 42 个冲突食物全部同时带两键，0 个未拆；物理 oz 与 yield oz 的分支互斥。`fl_oz` 错误是额外阻断问题，不改变本条对重量 oz 两类拆分的结论。 |
| 5. resolver / 手册 / schema 对称 | **FAIL** | `serving` 已在 resolver 语法中，本次写入 5 个值并实际改变解析，却未同步 react.py 手册及 phrase 测试。其他新键未进语法不要求本轮同步。 |
| 6. 三项交叉检查 | **PASS** | 240/240 validate 全绿；25 个 gold 食物旧键 0 漂移且 178/178 重放相等；全量 213 passed。重放中有 1 次 seed 回退，报告口径需修正。 |

## Standards

未发现违反 `AGENTS.md` 明确规则的 hard violation；`pyproject.toml` 没有人类编码约定。判断性 smell 两项：

- `scripts/build_fdc_catalog.py:209-227,287-307`：possible **Duplicated Code**。legacy scan 与 overlay 再次遍历同一 CSV、解析 gram weight 并 first-win merge，可考虑共享规范化 row iterator。
- `scripts/build_review_sheet.py:72-97,487-502`：possible **Divergent Change**。同一文件同时改变展示单位白名单与 catalog 完整性策略；后者更适合留在明确的加载/校验边界。

## Spec

规格轴共 3 个实质 finding：验收 5 的 `serving` 对称性缺失（高）、`fl_oz` 与报告/数据语义不符（高）、review sheet SHA 无条件放行属于会掩盖漂移的 scope creep（中）。另有 phrase 重放口径不精确（低）。验收 1、2 的目标实现正确，`explain_grams` 未发现新误导。

汇总：Standards 轴 0 个 hard violation、2 个判断性 smell（最突出为重复扫描）；Spec 轴 3 个实质 finding、1 个报告口径问题（最严重为错误 `fl_oz` 数据与未满足的 `serving` 对称性）。

## 与 `landing-report.md` 不符之处

1. `:42,58` 声称 `fl_oz` 仅来自 `1 fl oz…`，实际有 3 个 catalog winner 来自 `1 ... (N fl oz)`，值也是整份总重。
2. `:53,72-81` 将新键概括为“尚未进入语法”，但 `serving` 已在 `UNIT_SYNONYMS` 且 5 个新值立即改变解析；仅披露为“例外风险、以后处理”不满足验收 5。
3. `:91` 声称 178 次均按 query 匹配；实际为 177 次 query 精确匹配 + 1 次 seed 回退。

其余受审数字和声明均复现，包括旧键 0 漂移、104 个复合 `piece` 补缺、新键覆盖计数、42/42 oz 拆分、240/240 validate、178/178 重放相等和 213 tests 全绿。
