# 口语份量话术 → oracle gate 审计（oral-gate-audit）

> 生成：2026-08-18（主 agent 直接跑，因侦察者 agy 卡死未产出）。来源语料：`reports/user-phrasings.md`（26 条真实用户话术，NutriBench / FoodDialogues / FNDDS）。
> 方法：每条话术的份量表达喂 `resolve_portion`（catalog-v1）+ `matches_portion_table` 判定。
> 归类：`T1`=能解析成克数但非 PortionFact 倍数（被 oracle gate 拦）；`T2`=resolve_portion 返回 None（语法覆盖不了）；`OK`=已可解析且过 gate；`not-in-catalog`=意图食物不在 catalog-v1。

## 1. 审计表

| # | FDC | 份量表达 | 类别 | 归类 | resolve_portion | 过 gate |
|---|---|---|---|---|---|---|
| 01 | 2705824 | a thick steak | 尺寸 | OK | 240.0 | ✓ |
| 02 | 2705824 | a thin slice of sirloin steak | 尺寸 | T2 | None | — |
| 03 | 2707639 | a medium slice of toasted multigrain bread | 尺寸 | T2 | None | — |
| 04 | 2709383 | a large baked potato | 尺寸 | T2 | None | — |
| 05 | 2707995 | a large slice of apple pie | 尺寸 | T2 | None | — |
| 06 | 2708295 | one pouch of pancakes from frozen | 包装 | T2 | None | — |
| 07 | 2710321 | a tablespoon of rich pancake syrup | 包装 | T2 | None | — |
| 08 | 2705424 | a 6 oz container of Greek yogurt | 包装 | **T1** | 170.1 | ✗ |
| 09 | 171986 | a can of light tuna in water | 包装 | OK | 165.0 | ✓ |
| 10 | 2705385 | an individual carton of whole milk | 包装 | T2 | None | — |
| 11 | 2708573 | a bowl of tomato soup | 餐具 | OK | 140.0 | ✓ |
| 12 | 2708616 | a piece of medium crust pepperoni pizza | 餐具 | T2 | None | — |
| 13 | 2708613 | a personal cheese pizza | 餐具 | OK | 266.0 | ✓ |
| 14 | 2707746 | a fresh regular bagel | 餐具 | T2 | None | — |
| 15 | 2709456 | a medium order of french fries | 餐具 | T2 | None | — |
| 16 | 2709224 | a medium ripe banana | 离散 | T2 | None | — |
| 17 | 2709223 | half an avocado | 离散 | T2 | None | — |
| 18 | 2707160 | two scrambled eggs | 离散 | OK | 110.0 | ✓ |
| 19 | 2709215 | a whole extra-large red apple | 离散 | T2 | None | — |
| 20 | 168592 | a handful of roasted unsalted almonds | 手估 | T2 | None | — |
| 21 | 2708413 | a fist-sized portion of steamed brown rice | 手估 | T2 | None | — |
| 22 | 2705953 | a palm-sized grilled chicken breast | 手估 | T2 | None | — |
| 23 | 2708408 | 一碗白米饭 | 中文 | T2 | None | — |
| 24 | 2707537 | two tablespoons of peanut butter | 中文 | OK | 32.0 | ✓ |
| 25 | 2705824 | 一块掌心大小的牛排 | 中文 | T2 | None | — |
| 26 | 2709614 | 吃了点混合沙拉 | 中文 | T2 | None | — |

**统计：OK 6/26（23%）、T1 1/26、T2 19/26（73%）。**

## 2. 关键结论（比 gate 更严重的发现）

1. **T2 才是主流缺口（73%）**：真实用户话术绝大多数**根本过不了 `resolve_portion`**，而不是被克数 gate 拦。具体原因分层：
   - **尺寸修饰词**（medium / large / thin+slice / extra-large）：`REFUSED_MODIFIERS` 设计性拒绝（"a thick slice" 也拒），FNDDS 多档位（medium banana=126 / large potato=400 / thin steak=120）没进语法
   - **包装/容器单位**（pouch / carton / container）：`UNIT_SYNONYMS` 没有这些词
   - **手部估算**（handful / fist-sized / palm-sized）：无单位词
   - **中文量词**（一碗 / 两勺 / 掌心 / 吃了点）：英语语法天然不覆盖（两勺=2 tbsp 恰好是 #24 的英文等价，中文词本身解析不了）
2. **T1 只有 1 条**（6 oz container → 170.1g，非 PortionFact 倍数）：ticket 01 的 query-traceable 克数通道只救这一条。"150 g of chicken" 这类口语克数在 NutriBench 语料里少见（用户更常说 household 单位），但它是 gym persona 的典型表达，仍值得放行。
3. **ticket 02（裸名词）在语料里几乎没有对应**：26 条里没有 "an apple" 这种裸名词话术（都有修饰词）。裸名词是"用户可能说"的合理假设，但不是本语料的高频缺口。
4. **推论**：v1.0 考试话术塌缩成 cup 的根因，除了 gate 绑死 PortionFact 倍数，更本质的是 **expander 的产出空间被"语法能解析的表达"限制**——语法覆盖窄 → LLM 只能写语法能过的话术 → cup 这类"语法覆盖最宽"的单位胜出。**要真正多样化，需要扩语法（size modifier / packaging / hand units）或显式扩 expander 词汇**，仅放宽克数 gate 不够。

## 3. 必须放行清单（建议）

- **T1 代表**：`a 6 oz container of Greek yogurt` → 170.1g（口语克数/盎司容器，query-traceable 锚点，ticket 01 覆盖）
- **T2 代表**（按频度/重要性）：
  - `a medium ripe banana`（天然离散单体 + 尺寸修饰，最常说的自然话术之一）→ FNDDS medium banana=126g
  - `a thin slice of sirloin steak`（thin 档位=120g；当前 "thin slice" 被组合拒绝）→ 需尺寸修饰词支持
  - `a handful of roasted unsalted almonds`（手部估算 ≈ 1 oz 28.35g，营养学等价）
- **中文量词**：明确 Out of Scope（英语语法），考试不做中文题（Phase 6 扩量不涉及）。

## 4. 对 ticket 的修正建议（供主 agent 裁决）

- ticket 01（克数 gate 放宽）：保留，但预期收益小（只救 T1 1 条 + gym 口语克数假设）；evaluate 收紧部分照做。
- ticket 02（裸名词）：保留（低成本、零风险），但应把验收期望下调——它不解决语料里的 T2 主流。
- **新增缺口（建议加 ticket 或并入 Phase 6）**：尺寸修饰词（medium/large/small/thin/thick + FNDDS 档位）与包装单位（carton/container/pouch）是 T2 的最大头；需先裁决"是否扩语法 + 是否扩 react.py 手册"，再决定 Phase 6 的量词多样化怎么做。
