# 语法接入实现终审

## 结论

**允许提交。** 限定 diff 与 `docs/syntax-integration-design.md` 的核心语义一致，未发现会产生错误克数、改动冻结 split 或让 `fl_oz` 抢占 review-sheet gloss 的阻断问题。

独立验收结果：`255 passed`，`landing_verify.py` 为 `RESULT: PASS`，指定的 8 个行为抽查全部符合预期；设计 §6 的 207 条 realization phrase 重放为 **202 条不变、5 条变化**，5 条逐项符合 §2.4.4。

## 审查范围

以当前 `HEAD` 为固定点，审查工作树中以下文件：

- `src/nutrienv/world/portions.py`
- `src/nutrienv/harness/react.py`
- `scripts/build_review_sheet.py`
- `tests/test_portions.py`
- `tests/test_review_sheet.py`

`git diff` 确认 catalog、gold、`realizations.py`、`validator.py` 和 `materialize_split.py` 均未改动。`git diff --check` 无报错。

## Spec 轴：对照 Opus 设计

### 1. 修饰词（§2.1.2）

| 设计要求 | 实现核对 | 结果 |
|---|---|---|
| `thick/thin/regular` 不是单位，只绑定 serving/dish-noun | 它们仅在 `MODIFIER_KEYS`，不在 `UNIT_SYNONYMS`；`resolve_portion` 仅对 `key == "serving"` 绑定，`_dish_noun_grams` 使用同名 portion 键 | 通过 |
| 显式量具 + 修饰词返回 `None` | gram/ounce 分支显式拒绝；其他单位在 `key != "serving"` 时拒绝 | 通过 |
| `REFUSED_MODIFIERS` 任何位置拒绝 | 进入单位扫描前由 `_refuses_modifiers(tokens)` 全句检查 | 通过 |
| 互斥修饰词同时出现拒绝 | `_refuses_modifiers` 对修饰键集合做 `len(...) > 1` 检查 | 通过 |
| 修饰键不存在返回 `None` | `portions.get(modifier)` 后的数值/有限/正数检查拒绝缺键 | 通过 |
| 数量解析前剔除修饰词 | serving 与 dish-noun 两条路径均调用 `_without_modifiers` | 通过 |
| `some sandwich` 的空跨度守卫保留 | `_leading_quantity` 仍有 `if not run: return None` | 通过 |

额外独立探针也确认：`a thick thin steak`、`a thick slice`、`two thin cups`、`150 regular g`、`a thick ounce`、缺 `thick` 键的 `a thick sandwich`、`a steak large`、`a thick` 均返回 `None`。

设计明确指定在单位/菜名之前的 quantity span 扫描可用修饰词，而且将“检查单位之后 token”列为 §6 步骤 5a 的后续项。因此，像 `a slice thick` 这类后置、非设计语序仍会在命中 `slice` 时提前返回，属于已记录的 suffix-blind 边界，不是本 diff 对 §2.1.2 的偏离。

### 2. `fl_oz`（§2.3.1）

- `_collapse_unit_bigrams(_tokenize(phrase))` 在主单位循环前执行，所以 `fl oz` / `fluid ounce(s)` 在 `OUNCE_UNITS` 分支之前已归一为 `fl_oz`。
- `UNIT_SYNONYMS` 只将归一后的 `fl_oz` 和连写 `floz` 映射到 catalog 键。
- 裸 `oz/ounce(s)` 的 `OUNCE_GRAMS = 28.35` 常量分支未改，`an ounce of oats` 仍为 28.35 g。

结论：实现顺序和不抢占 ounce 常量路径均与设计一致。

### 3. serving/qns（§2.4）

`_serving_default` 键序为 `qns → piece → slice → cup`，对非数值、bool、非有限值和非正数继续回退。serving 词路径和 dish-noun 路径都调用该函数；修饰词出现时才改读对应同名键。catalog 仍不写 `serving` 键。

全库独立复算得到：可解析 serving **8795** 个，`< 5 g` **50** 个，`> 1000 g` **8** 个，精确复现 §6 验收阈值。

### 4. ReAct 手册（§4.1）

`_SYSTEM_V1_TAIL` 与 §4.1 给出的替换文本逐行一致，正向说明：

- cup/tbsp/tsp/slice/piece/each/can/fl_oz；
- serving/portion/bowl/plate/order 和 dish-as-unit；
- qns 优先及 piece/slice/cup 回退；
- thick/thin/regular 及“不是 slice size”的拒绝语义；
- ounce 常量和 gram 直接量；
- `oz`/`oz_yield`/`cubic_inch` 只是参考数据，不按 catalog 键换算。

按 §4.2/§5.5 的“语义表达”粒度，手册与解析器双向对称。解析器额外接受 `floz`、`fl oz`和复数等词形，手册用 `fl_oz (fluid ounce)` 作同一语义类的总说明，与手册不枚举 `cups/tbsps/servings` 等所有既有词形的做法一致。

### 5. Review-sheet 白名单

`_EXPLAIN_UNITS` 已从 `UNIT_SYNONYMS.values()` 自动派生改为设计指定的显式白名单：

```text
cup, tbsp, tsp, slice, piece, can, serving, g, oz
```

该改动是必要的：否则新增 `fl_oz` 会被自动带入 gloss 候选，使 122 g milk 从可读性更好的 `0.5 x cup` 变成 `4 x fl_oz`。实测 `explain_grams("milk_whole", 122.0, catalog)` 仍返回：

```text
0.5 x cup (244.0 g) = 122.0 g
```

## Standards 轴

- 未发现限定 diff 违反仓库已文档化的编码规范或 AGENTS.md 的克数锚点、零漂移、手册对称、判分不变纪律。
- 词形粒度的手册对称有一项非阻断风险：手册没有逐字枚举 `floz` 和空格形 `fl oz`。但设计 §4.1 本身也以 `fl_oz (fluid ounce)` 表达这一类，故不判为本次偏离。
- Fowler smell 判断项：`resolve_portion` 与 `_dish_noun_grams` 存在一小段重复的“数值类型 → finite/positive → round”校验流程（possible Duplicated Code）。这是小型、局部的审查判断项，不影响本次提交。

## 独立验收记录

### 指定行为抽查

| phrase | 结果 |
|---|---:|
| `a thick steak` | 240.0 |
| `a large steak` | `None` |
| `a thin steak` | 120.0 |
| `8 fl oz` | 244.0 |
| `8 fluid ounces` | 244.0 |
| `an ounce of oats` | 28.35 |
| `a serving of oats` | 10.0 |
| `a serving of orange` | 154.0 |

### 命令验收

```text
.venv/bin/python -m pytest -q
255 passed in 146.67s
```

```text
.venv/bin/python scripts/landing_verify.py
gold foods: 25
old-key drifts: 0
phrase replay: 178 equal, 0 differ, 145 items unmatched/no phrase
validate_draft: 240 items, 0 failing
oz/oz_yield conflicts in FNDDS: 42; unsplitting: 0
RESULT: PASS
```

`landing_verify.py` 的 phrase replay 只遍历冻结 split 中能匹配到 realization row 的项，因而它的 `178 equal / 0 differ` 不能单独作为 §6 “207 条全体重放”的证据。本终审按设计限定的 `FUZZY / UNIT_CONVERT / NEAR_SYNONYM / MULTI_ITEM_LOG / EVALUATE` 五类独立重放：

```text
total=207 equal=202 differ=5
2706880  'a sandwich'                         175.0 -> 115.0
2706885  'a barbecue beef sandwich'           270.0 -> 180.0
2707196  'a serving of shrimp egg foo yung'   175.0 -> 131.0
2707198  'an omelet'                           55.0 -> 110.0
2708750  'a serving of lasagna'               206.0 -> 250.0
```

5 条变化与 §2.4.4/§6 完全一致，其余 202 条逐值相等。`validate_oracle_grams` 当前为 **33 个 task 被 flag，共41 条 issue string**；设计中的“33 条 flag”指 flagged task 数。相关 validator、catalog 和 gold 均不在本 diff 中。

## 非阻断后续项

1. §2.1.2 的互斥修饰词行为已实现且独立探针通过，但 `tests/test_portions.py` 没有一条直接的 `a thick thin steak -> None` 回归断言。设计 §5 的 M1–M15 也未列此用例，因此不阻断本次提交；建议后续补上以防手滑回归。
2. `test_omelet_piece_55_is_legal_table_value` 保护了 55 g 是 catalog 表值，但测试本身没有调用 validator/judge gate，因而其“不送 judge”的注释比断言能证明的范围更大。这是测试命名/评论精度问题，不影响语法实现。

汇总：Standards 轴 0 项阻断、2 项 judgement call；Spec 轴 0 项行为偏离、2 项非阻断测试/评论精度后续项。
