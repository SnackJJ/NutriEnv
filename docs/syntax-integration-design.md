# 语法接入 + serving 语义设计

> 承接 `reports/landing-report.md`（FNDDS 安全叠加落地）与 `docs/landing-review.md`（终审）的
> **验收 5 未做项**：新键写进 catalog 但没进 `resolve_portion` 语法、没进 `react.py` 手册、
> 没有 phrase→key→grams 测试。本文件是这一步的设计裁决，**只出设计，不改任何代码/数据**。
>
> 上游：`docs/llm-generated-exam-data.md` 第 7 节第 1/3 步、`docs/adjudication-report.md` 验收 5、
> `docs/review-fndds-ingestion.md` §4.2/4.3。

---

## 0. 三个关键决策（TL;DR）

| # | 问题 | 决策 | 一句话理由 |
|---|---|---|---|
| 1 | **qns 是否作 "a serving of X" 的默认？** | **是**。`_serving_default` 改为 `qns → piece → slice → cup`，同时作用于 serving 词与 dish-noun 两条路径 | qns（FNDDS modifier 90000）本来就是 USDA 对"受访者说了一份但没给量"的官方答案，正是 "a serving" 的语义；实测它在覆盖率和退化率上**三项全胜**当前回退，且 judge 灰区实验在唯一分歧最大的一例上也站 qns（见 §2.4） |
| 2 | **serving 键写不写进 catalog / 回退改不改 QNS？** | **不写键，只改回退**（二选一，不组合） | FNDDS 全表 22046 条 portion 行里没有通用 "1 serving" 行——502 条含 serving/bowl/order 字样的几乎全是包装规格（`1 large single serving bag`、`1 KFC Bowl`、`1 fast food order`）。写键只能覆盖 ~5 个食物，制造"5 个食物走 serving 键、5321 个走 qns"的双轨语义，一句话写不进手册 |
| 3 | **thick 怎么进语法？** | **作修饰词，不作单位词**：只绑定"食物本身即单位"的读法（`serving` 词 / dish-noun），且必须命中同名 catalog 键；**句中一旦出现显式量具（slice/cup/piece/…）就返回 `None`** | catalog 的 `thick`/`thin` 键**系统性地不是**"厚/薄切片"——FNDDS 的 `1 large or thick slice` 类行被 builder 的 household 早退丢弃、克数落进了 `slice` 键；实测 `thin/slice` 在 27 个共存食物上**恒 ≥ 1.75**（中位 4.0）。把 "two thin slices" 映到 `thin` 会系统性偏大 |

设计文档路径：`docs/syntax-integration-design.md`（本文件）。

---

## 1. 核实到的现状（全部为本轮实测，非引述）

### 1.1 catalog 键分布（`data/fdc/catalog.sqlite`，13224 个食物）

```
cup 6251 | qns 5326 | piece 2329 | tbsp 1015 | slice 955 | fl_oz 628 | regular 453
can 434 | cubic_inch 382 | oz_yield 304 | oz 242 | tsp 237 | thin 56 | thick 54
```

与 `reports/landing-report.md` 新键清单逐项一致（`fl_oz` 628 对 629 的 1 个差是 first-wins 后
`gram_weight<=0` 丢弃，不影响结论）。

### 1.2 `resolve_portion` 现状（`src/nutrienv/world/portions.py`）

- `UNIT_SYNONYMS` 只认 cup/tbsp/tsp/piece/slice/can/serving(+portion/bowl/plate/order)。
- 口语 `oz`/`ounce(s)` 在 `UNIT_SYNONYMS` **查表之前**分支到常量 `OUNCE_GRAMS = 28.35`，
  与 catalog 的 `oz` 键完全无关。
- `"a serving of X"` 无 `serving` 键时走 `_serving_default` = `piece → slice → cup`。
- `_dish_noun_grams` 让 `DISH_NOUNS` 里的名词在**食物自身名字包含该名词**时充当单位，
  同样落到 `_serving_default`。

### 1.3 本轮新发现的缺陷：修饰词在两条路径上**不对称**

| phrase | food | 现状 | 说明 |
|---|---|---|---|
| `"a regular serving"` | `2706880` Sandwich, NFS | **None** | unit 路径：`regular` 不是数量词 → `_parse_quantity` 返回 None → 整条拒绝（保守，正确） |
| `"a thick steak"` | `2705824` Beef, steak, NFS | **30.0** | dish 路径：`_leading_quantity` 在 `thick` 处 break，但 run=`["a"]` 非空 → 数量读成 1，**修饰词被静默丢弃** |
| `"a thin steak"` / `"a large steak"` / `"a steak"` | 同上 | 均 **30.0** | 三个语义完全不同的表达返回同一个数 |
| `"1 oz dry"` | `pasta` | **28.35** | unit 之后的 `dry` 被完全忽略；该食物 `oz_yield=80`（1 oz 干 → 80 g 熟） |

`30.0` 这个数本身也可疑：它来自 FNDDS 复合行 `1 piece/slice, any size`，而该食物的
`1 regular` = 160 g、`1 thick` = 240 g。**"一块牛排 = 30 g" 是当前 Oracle 的真实取值。**

这是"静默给错数"，比返回 `None` 严重——模块自己的 docstring 写着 *"it returns `None`
whenever it is not sure. `None` means 'ask for grams', not 'zero'."*

### 1.4 gold 240 与 serving/dish 路径的真实关系（**决定影响面的关键事实**）

- 240 条题的 `ledger_tail` / `last_plan` 里出现的 food_id **全部是 25 个 staple slug**；
  整个 `v0.5-gold.json` 里**不存在任何 6/7 位 fdc_id**（正则 `"(\d{6,7})"` 命中 0 次）。
- 因此 `realizations.py` 里 10 条 `fz-dish-*`（`source="v0.6-dish-sample"`，food_id 是裸 fdc_id）
  **一条都不在冻结的 240 里**。
- 枚举 `FUZZY / UNIT_CONVERT / NEAR_SYNONYM / MULTI_ITEM_LOG / EVALUATE` 全部 **207 条
  (food_id, phrase)**：除这 10 条 dish 外，其余 197 条全部使用显式量具
  （cup / tbsp / tsp / piece / slice / can / `N g` / `N oz`），**没有一条走 `_serving_default`**。
- 240 条题的 **query** 里含 serving 类词的只有 4 条，且都不进 `resolve_portion`
  （evaluate 家族用 `row.items` 的 `(food_id, phrase)` 对，不解析整句 query）：

  | id | query 片段 |
  |---|---|
  | `v03-eval-tri-yogurt-banana-apple` | "Check this snack **plate** for me: a cup of yogurt, …" |
  | `v03-eval-tri-cheddar-apple-yogurt` | "Check this snack **plate** for me: a slice of cheddar, …" |
  | `v04-rec-flex-lunch` | "lunch can be a bigger **plate** than usual" |
  | `v04-cond-tuna` | "Would a tuna **plate** work for lunch…" |

> ⚠️ 顺带发现的既有隐患（**不属本次改动，但要记录**）：`resolve_portion` 取
> **第一个**认识的单位词。若将来有人把整句 query 直接喂进去，
> `"Check this snack plate for me: a cup of yogurt"` 里 `plate` 排在 `cup` 之前，
> 会被读成 serving 而不是 cup。目前的调用约定（逐 `(food_id, phrase)`）挡住了它。

---

## 2. 表达 → 档位映射设计（逐新键）

### 2.1 `thick` / `thin` / `regular` —— 修饰词，不是单位词

#### 2.1.1 数据事实（决定性）

**来源分布**（复跑 `_overlay_keys` 得到每个键的获胜描述）：

| 键 | 获胜描述 | 食物数 |
|---|---|---|
| `thick` (54) | `1 thick` 26、`1 thick / belgian waffle` 18、`1-3 ring thick pretzel` 10 | |
| `thin` (56) | `1 thin` 26、`1 bagel thin` 14、`1-3 ring thin pretzel` 10、`1 pretzel chip/crisp/thin` 3、`1 sandwich thin` 1、`1 oreo thin` 1、`1 small or thin (…wafers)` 1 | |
| `regular` (453) | `1 regular` 153、`1 small/regular fillet` 84、`1 small/regular` 41、`1 regular sandwich` 32、`1 pouch/regular size` 31、`1 medium/regular` 23、`1 regular/large` 18、`1 medium/regular/sandwich size roll` 16、`1 regular cupcake` 12、`1 regular ear` 11、… | |

**关键事实 1 —— "厚/薄切片"根本不在这两个键里。**
FNDDS 原表里 `1 large or thick slice`（136 行）、`1 small or thin/very thin slice`（88 行）、
`1 small or thin slice`（57 行）因为含 household 单位词被 `_overlay_keys` 早退丢弃，
它们的克数由 legacy 扫描落进了 **`slice`** 键。

实例 `2707777 Bread, multigrain`：

```
seq 7  '1 small or thin/very thin slice'  = 24 g   → 落进 slice
seq 9  '1 large or thick slice'           = 43 g   → 丢弃
seq 11 '1 sandwich thin'                  = 42 g   → 落进 thin   ← 这是三明治薄面包（产品名）
```

即 catalog `thin = 42` 是「一个 Sandwich Thin 面包」，而该食物真正的**薄切片是 24 g、已经在
`slice` 键里**。若把 `"two thin slices"` 映到 `thin`，会给出 84 g 而正确答案是 48 g（**1.75×**）。

**关键事实 2 —— 全库统计证实这不是孤例：**

| 比值 | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| `thin / slice` | 27 | **1.750** | 3.000 | 4.000 | 6.000 | 7.500 |
| `thick / piece` | 41 | 0.200 | 1.080 | 3.375 | 8.000 | 15.000 |
| `thin / piece` | 49 | 0.032 | 0.194 | 0.667 | 4.000 | 7.500 |
| `thick / regular` | 26 | **1.500** | 1.500 | 1.500 | 1.500 | **1.500** |
| `thin / regular` | 40 | 0.438 | 0.438 | 0.750 | 0.750 | 0.750 |

`thin/slice` 的最小值就是 1.75 —— catalog 的 `thin` **恒大于**同一食物的 `slice`。
反过来 `thick/regular` 在 26 个共存食物上**恒为 1.5**（牛排 120/160/240、肋眼 180/240/360、
T 骨 225/300/450、猪排 90/120/180），说明 `1 thin / 1 regular / 1 thick` 是同一把尺子上的
三档，**而这把尺子量的是"一份这个食物"，不是"一片"**。

**关键事实 3 —— 被"污染"的那些恰好也符合这个读法。**
`1 Bagel Thin`（46 g，整个薄贝果）、`1 sandwich thin`（42 g，整个三明治薄面包）、
`1 oreo thin`（7 g，一整块 Oreo Thins）、`1 thick / belgian waffle`（135 g，一整个厚华夫饼）、
`1-3 ring thick pretzel`（17 g，一整个厚脆饼）——**全部都是"一整个（厚/薄款的）这个食物"**。

#### 2.1.2 设计规则

> **修饰词只绑定「食物本身即单位」的读法。一旦句中说出显式量具，拒绝。**

新增词类（**不进 `UNIT_SYNONYMS`**，这是关键——它们不是单位）：

```python
#: Size words that pick a different FNDDS row of the *same* food-as-unit
#: reading. Never a household measure: "a thick slice" is refused, because
#: the catalog's thick/thin keys are not slice sizes (see design doc 2.1).
MODIFIER_KEYS: dict[str, str] = {"thick": "thick", "thin": "thin", "regular": "regular"}

#: Size words FNDDS has no separate key for. Recognised only so the grammar
#: refuses instead of silently reading them as "one".
REFUSED_MODIFIERS = frozenset(
    {"large", "big", "huge", "jumbo", "giant", "small", "little", "medium",
     "mini", "miniature", "tiny"}
)
```

解析规则（在**数量跨度**——单位词/菜名之前的那段 token 里——扫描修饰词）：

| 情形 | 结果 |
|---|---|
| 修饰词 + `serving`/`portion`/`bowl`/`plate`/`order`，且 `portions[修饰词]` 存在 | `quantity × portions[修饰词]` |
| 修饰词 + dish-noun（食物名含该名词），且 `portions[修饰词]` 存在 | `quantity × portions[修饰词]` |
| 修饰词 + **显式量具**（cup/tbsp/tsp/slice/piece/can/g/oz/fl_oz） | **`None`** |
| 修饰词，但 `portions[修饰词]` **不存在** | **`None`** |
| `REFUSED_MODIFIERS` 里的词，任何位置 | **`None`** |
| 两个互斥修饰词同时出现（"thick thin"） | **`None`** |
| 修饰词单独出现、无单位无菜名（"a thick"） | **`None`**（无单位可绑） |

数量计算时把修饰词从跨度中剔除后再送 `_parse_quantity`（`"two thin steaks"` → 数量 2）。
`_leading_quantity` 的空跨度守卫必须保留（`if not run: return None`），
否则 `"some sandwich"` 会从 `None` 变成 1 份 —— 原型第一版就踩了这个坑。

#### 2.1.3 边界验证（原型实测，`now → new`）

| food | phrase | now | new | 说明 |
|---|---|---|---|---|
| `2705824` steak | `a thick steak` | 30.0 | **240.0** | 命中 `thick` |
| `2705824` | `two thin steaks` | 60.0 | **240.0** | 2 × `thin`(120) |
| `2705824` | `a regular steak` | 30.0 | **160.0** | 命中 `regular` |
| `2705824` | `a thick serving` | None | **240.0** | serving 词 + 修饰词 |
| `2705824` | `a thick slice` | None | **None** | 显式量具 → 拒绝 |
| `2705824` | `two thin slices` | None | **None** | 同上（**核心安全边界**） |
| `2705824` | `a slice` | 30.0 | 30.0 | 无修饰词，不变 |
| `2705824` | `a large steak` | 30.0 | **None** | 拒绝，不再静默读成 1 份 |
| `2707777` bread | `two thin slices` | None | **None** | 不会读成 2×42 |
| `2707777` | `two slices` | 48.0 | 48.0 | 不变 |
| `2708312` waffle | `a thick serving` | None | **135.0** | `thick`；`waffle` 不在 `DISH_NOUNS`，故 `a thick waffle` 仍 `None` |
| `2707684` bagel | `a thin serving` | None | **46.0** | Bagel Thin |
| `2706880` sandwich | `a regular serving` | None | **115.0** | 命中 `regular`（= qns） |

**覆盖面**：`thick` 54 个食物、`thin` 56、`regular` 453；其中名字含 `DISH_NOUNS` 的分别是
20 / 21 / 191（走 dish-noun 路径），其余只能通过 serving 词触达。
规则**只扩大解析能力、只把静默错答变成拒绝**，没有任何一条现有正确解析被改数（见 §2.1.3 表右列）。

#### 2.1.4 为什么不选另外两个方案

- **扩展 `UNIT_SYNONYMS`（`"thick": "thick"`）**：会让 `"a thick"` / `"two thicks"` 成为合法量具，
  也会让 `"a thick slice"` 里的 `thick` 抢在 `slice` 之前命中（`resolve_portion` 取第一个认识的
  单位词），直接产出 §2.1.1 证明的错数。**否决。**
- **按比例外推（`thick = 1.5 × regular`）**：只在 26 个食物上成立；其余 28 个 `thick` 食物
  （华夫饼、脆饼）没有 `regular`，比例外推会凭空造数，违反硬纪律 1（"克数锚点 = 表值"）。**否决。**

### 2.2 `oz` / `oz_yield`

#### 2.2.1 `oz`：**维持常量 28.35，永不读表**（决策：不改）

实测：catalog 里 242 个 `oz` 值**只有一个 distinct value —— 恰好 28.35**。

因此"改读表"的收益为零、代价为负：

- 对有 `oz` 键的 242 个食物：读表结果与常量**逐位相同**；
- 对其余 12982 个食物：读表会从 28.35 退化成 `None`（`"2 ounces"` 的 6 条现有 realization
  行——`fz-oats-oz`、`uc-*` 5 条、`ev-single-almond-oz`、`ev-pair-oats-oz-banana`
  ——会全部炸掉，因为 oats/almond/chicken/tuna/salmon 都没有 `oz` 键）。

`docs/adjudication-report.md` 2.4 陷阱 B 担心的"接入 `oz` 会踩到 42 个 oz/oz_yield 混装食物"
在落地后已不成立（42 个全部拆干净），但**接入本身没有理由**。
**这条建议在文档里定性为"已关闭"，不再作为待办。**

#### 2.2.2 `oz_yield`：**明确不进语法**（决策：catalog-only）

语义核实：`oz_yield` 是「**1 oz 生/干重烹调后得到的克数**」，不是可直接吃下的重量。
`pasta` 的 `oz_yield = 80`（1 oz 干意面 ≈ 28.35 g → 熟后 80 g），
全库范围 8.0–210.0，中位 20.0 —— 与 28.35 完全不同量纲。

不接入的三条理由：

1. **需要一个"生/干"形容词槽**，而形容词恰好是本设计正在收紧的东西。
   现状 `"1 oz dry"` 对 pasta 返回 28.35（`dry` 在单位之后被完全忽略）——同一个静默丢弃缺陷。
2. **会造出 2.8× 的语义悬崖**：`"an ounce of pasta"` = 28.35 vs `"an ounce of dry pasta"` = 80，
  差一个形容词差 2.8 倍。judge 灰区门（sandwich 1.5× / lasagna 1.2× / omelet 2.0×）
  连 2.0× 都还没过，不能先引入 2.8×。
3. **建模层次错了**：catalog 里的食物是**熟的**（`Pasta, cooked`，营养素按熟重 per 100 g）。
   "干意面"是另一个 food_id 的事，属于食物层，不属于份量语法层。
   304 个有 `oz_yield` 的食物里有 **262 个根本没有 `oz` 键**，说明这批行本来就是生/干态记录。

**重开条件**（写进文档，避免以后重新论证）：judge 灰区门过了 + 单独设计「生/干/熟」状态词 +
确认 catalog 的 raw/cooked 食物对能一一对上，三者齐备再议。

**残留已知缺陷（本轮不修，记录在案）**：`"1 oz dry"` 仍会静默返回 28.35。
修法是把 `dry|raw|uncooked` 纳入 §2.1 的拒绝词类，但那要求语法开始关心**单位之后**的
token（现在的循环命中单位就返回），改动面比本次大。列为 §6 步骤 5 的可选项。

### 2.3 `fl_oz` / `cubic_inch`

#### 2.3.1 `fl_oz`：**接入**（决策：进语法）

理由：

1. **真实口语**。`"8 fl oz"` / `"a 12 fluid ounce glass"` 是饮品最常见的说法，628 个食物有该键。
2. **表值干净**。`cup / fl_oz` 在 289 个共存食物上 p25 = median = p75 = **8.000**
   （即标准美制定义），min 2.0 是个别异常，不影响以表值为准的语义。
3. **纯增量、零改数**。现状 `"8 fl oz"` 返回 `None`（`fl` 毒化了数量解析），
  `"12 fluid ounces"` 同样 `None`。接入只把 `None` 变成数，**不会改任何已有数字**。
   另有 339 个食物只有 `fl_oz` 没有 `cup`，接入后才有液体量具。

实现要点（**bigram，不是新同义词**）：`_tokenize` 按非字母数字切分，`"fl oz"` 是两个 token。
需要在 `_tokenize` 之后加一个**归一化 pass**：

```python
#: Multi-word spoken units, collapsed before the unit scan so "fl oz" cannot
#: be eaten by the bare-ounce branch.
UNIT_BIGRAMS: dict[tuple[str, str], str] = {
    ("fl", "oz"): "fl_oz", ("fl", "ozs"): "fl_oz",
    ("fluid", "ounce"): "fl_oz", ("fluid", "ounces"): "fl_oz",
}
UNIT_SYNONYMS["fl_oz"] = "fl_oz"   # 归一化后的单 token
UNIT_SYNONYMS["floz"] = "fl_oz"    # 连写
```

**必须在 `OUNCE_UNITS` 分支之前完成归一化**，否则 `oz` 会先命中常量 28.35。

⚠️ **实测副作用（必须同一变更处理）**：`scripts/build_review_sheet.py:72`
`_EXPLAIN_UNITS = frozenset(UNIT_SYNONYMS.values()) | {"g", "oz"}` 是**自动派生**的。
加入 `fl_oz` 后实测：

```
milk_whole 122 g   现在: "0.5 x cup (244.0 g) = 122.0 g"
                   之后: "4 x fl_oz (30.5 g) = 122.0 g"      ← 人工评审可读性倒退
soy_milk   122 g   同上
```

因为排序键 `(abs(ratio - round(ratio)), -gpu, …)` 先比"是否整数倍"，`4.0` 赢过 `0.5`。
`test_grams_explained_round_trips` 仍会绿（round-trip 成立），但 review sheet 的人读体验变差。
**处理办法**：把 `_EXPLAIN_UNITS` 从"派生自 `UNIT_SYNONYMS`"改成**显式白名单**
（`{"cup","tbsp","tsp","slice","piece","can","serving","g","oz"}`），并在注释里写明
"新语法单位默认不进 gloss，除非确认它比 cup 更贴近用户说法"。

#### 2.3.2 `cubic_inch`：**不接入**（决策：catalog-only）

- 来源极干净（`1 cubic inch` 374 / 382，中位 17 g），**不是数据质量问题**。
- 但没人这么说话。`"a cubic inch of cheddar"` 不是自然口语，是问卷量具。
- 手册对称性是双向约束：**手册里不该出现没人说的表达**。接入它意味着要在 `react.py` 手册里
  写一行 agent 永远用不上的说明，纯增负担。
- 遵守 CLAUDE.md 第 2 条（"No features beyond what was asked. Nothing speculative."）。

**重开条件**：某个 persona / query family 真的产出了 cubic inch 表达（例如奶酪/肉块的
"一小块方糖大小"改写），届时按 §2.3.1 的 bigram 机制接入（`("cubic","inch") → "cubic_inch"`），
成本很低。

### 2.4 `qns`：作 `"a serving of X"` 的默认 —— **是**

#### 2.4.1 决策

```python
def _serving_default(portions):
    """The default portion of a food, in grams: FNDDS QNS, else piece/slice/cup."""
    for key in ("qns", "piece", "slice", "cup"):
        ...
```

**只改这一个函数的键顺序**，同时作用于 `"a serving of X"` 与 dish-noun 两条路径
（两者本来就共用它，保持一致是设计要求，不是副作用）。

#### 2.4.2 理由

**(a) 语义上 qns 就是这个问题的官方答案。**
FNDDS modifier `90000` = `Quantity not specified`：受访者报了这个食物但没说量，
USDA 给出的代表克数。这**字面上就是** `"a serving of X"`。
当前的 `piece → slice → cup` 按 `portions.py` 自己的 docstring 是本地发明的顺序。
硬纪律 1 说"克数锚点 = FNDDS 表值 / QNS"——qns 是被点名的那个。

**(b) 全库质量指标三项全胜**（实测，13224 个食物）：

| 回退顺序 | 能解析出 serving | < 5 g（退化偏小） | > 1000 g（退化偏大） |
|---|---|---|---|
| 现状 `piece→slice→cup` | 7819 | **80** | **40** |
| 提案 `qns→piece→slice→cup` | **8795**（+976） | **50** | **8** |

现状最差样本：`Cereal, O's, plain` 0.1 g、`Currants, dried` 0.5 g、`Watermelon, raw` **6000 g**、
`Pie, NFS` 2000 g。
提案最差样本：`Sugar substitute, stevia` 0.6 g、`Chives, freeze-dried` 0.8 g、
`Beef, brisket, flat half` 1967 g —— 都是本来就极端的食物，不是解析错误。

**(c) judge 灰区实验独立印证**（`reports/gray-zone-probe.md`，本设计撰写期间并行产出）。
该实验把六个合法 FNDDS 档位值送给 judge（K=5，temp 0.7，问"是否 plausible 的真实份量"）：

| 用例 | 克数 | 来源档位 | ok 比例 | 判定 |
|---|---|---|---|---|
| sandwich | 175 / 115 | piece / **qns** | 1.00 / 1.00 | 都接受 |
| lasagna | 206 / 250 | piece / **qns** | 1.00 / 1.00 | 都接受 |
| omelet | 55 / 110 | piece / **qns** | **0.40** / 1.00 | piece 被拒，**qns 接受** |

judge 的拒绝理由："55 g of omelet is a very small piece, more like a bite than a real meal portion."
—— **在两个锚点分歧最大（2.0×）的唯一一例上，独立的常识检查站在 qns 一边。**
1.2× / 1.5× 两例两侧都接受，说明 judge 不在两个合法键之间做选择，只挡明显荒谬值。

⚠️ 边界：这是 LLM 常识判断，不是 ground truth；且该报告自己的结论是
"gate 不能按 0.6 原样封，应先白名单 FNDDS 表值"——白名单一旦落地，55 和 110 都会被接受，
**gate 不会替解析器做选择**。因此这条只作**佐证**，不作充分理由；充分理由是 (a)(b)(d)。

**(d) 修掉 25 个 gold 食物里的真实退化**：

| slug | 现状 serving | 来源 | qns | 说明 |
|---|---|---|---|---|
| `orange` | 15.0 | `slice` | **154.0** | 现状 = 一瓣橘子 |
| `broccoli` | 10.0 | `piece` | **45.0** | 现状 = 一朵小花球 |
| `avocado` | 15.0 | `slice` | **30.0** | |
| `greek_yogurt` | 245.0 | `cup` | **150.0** | 一小杯酸奶 |
| `potato` | 230.0 | `piece` | **285.0** | |
| `peanut_butter` | **None** | — | **32.0** | 新增可解析（无 piece/slice/cup） |
| `white_rice` | 158.0 | `cup` | **118.0** | |

**(e) 也修掉 dish 侧的"默认取大号"缺陷。**
`2706880 Sandwich, NFS` 原始行：`1 regular = 115`、`1 large = 175`、`QNS = 115`。
legacy `_portion_key` 的最后一条模式 `banana|egg|medium|large|small → piece`
把 **`1 large` 的 175 g 写进了 `piece`**。所以今天 `"a sandwich"`（无修饰）= 175 g，
**默认给的是大号三明治**。改用 qns 后 = 115 g（= `1 regular`），语义正确。

#### 2.4.3 反面 / 风险（如实列出）

- **3430 个食物的 serving 值会变**（920 个恰好相等，976 个从 `None` 变成有值，4429 个两者皆无）。
  变化比中位 **0.727**（qns 普遍偏小）：2200 个变小、1230 个变大。
- **仍有退化，只是换了一批**：`oats` qns = **10.0**（现状 cup 80.0）—— 一份生燕麦 10 g 显然不对，
  这是 FNDDS 对"生燕麦被当配料撒"的记录；`spinach` qns = 13.0（现状 cup 25.0）。
  这两个是提案下最刺眼的样本，需要在 §6 步骤 3 的抽查里点名复核。
- **`_matches_portion_table`（`validator.py:165`）扫描 portions 全部值**，包含 qns/oz/thick 等
  catalog-only 键。安全叠加落地时它就已经被动放宽了（锚点候选集从 6 个键扩到 14 个）。
  这不是本次语法改动引入的，但**建议顺手加一条限制**：只用"语法可达"的键当锚点。
  列为 §6 步骤 5 可选项。

#### 2.4.4 对 gold 240 的影响分析 —— **零**

三重实测：

1. **240 条 `validate_draft` 逐条对比**：现状 `0 failures`，qns-first `0 failures`，全量提案原型
   （qns + 修饰词 + fl_oz）也是 `0 failures`。
2. **`validate_oracle_grams`**：现状 33 条 flag，提案后**同样 33 条、逐条字符串相同**
   （都是 `"150 g"` 这类整克表达本来就没有表锚点，属 ADR 0009 "Flag, do not drop" 的已知项）。
   **净变化 0。**
3. **207 条 realization phrase 重放**：只有 5 条变，且**全部是不在 240 里的 `fz-dish-*`**：

| seed | food | phrase | now | new | ratio |
|---|---|---|---|---|---|
| `fz-dish-sandwich` | 2706880 | `a sandwich` | 175.0 | 115.0 | 0.657（**1.52×**） |
| `fz-dish-bbq-beef-sandwich` | 2706885 | `a barbecue beef sandwich` | 270.0 | 180.0 | 0.667（**1.50×**） |
| `fz-dish-egg-foo-yung` | 2707196 | `a serving of shrimp egg foo yung` | 175.0 | 131.0 | 0.749 |
| `fz-dish-omelet` | 2707198 | `an omelet` | 55.0 | 110.0 | **2.00×** |
| `fz-dish-lasagna` | 2708750 | `a serving of lasagna` | 206.0 | 250.0 | **1.21×** |

其余 5 条 dish（burrito 220、soup 245、curry 240、chili 255、fried rice 137）**不变**
（前四者 qns 与旧默认同值；`167668` 是 sr_legacy，无 qns，自动落回 cup）。

> 🔴 **注意这三个比值**：`sandwich 1.5×` / `lasagna 1.2×` / `omelet 2.0×` ——
> 与 `CLAUDE.md` 硬纪律 3 点名的 judge 灰区三对**完全重合**。
> 这不是巧合：灰区用例的两个候选答案，正是「旧回退」与「qns」。
> 因此 **§6 步骤 3 必须在 judge 灰区门之前或同时跑**，两者是同一个决策的两面。

4. **`realizations.py` 的 7 个 `assert_*_rows` 在全量提案原型下全部通过**
   （所有 phrase 仍可解析，没有出现 `None`）。
5. **`tests/test_portions.py` 的 dish/serving 断言全部原样成立**——其 in-memory fixture 没有
   `qns` 键，回退自动落到 `piece/slice/cup`，10 条断言逐条 OK。

---

## 3. serving 语义决策

### 3.1 决策：**不写 `serving` 键；只改 `_serving_default` 回退**（二选一，非组合）

### 3.2 为什么不写键

实测 FNDDS `food_portion.csv`（survey.zip，22046 行）：含 `serving/bowl/plate/order/portion`
字样的共 **502 行**，词频前几名：

```
1 large single serving bag   112     1 large microwavable bowl    32
1 small single serving bag    87     1 single serving container   16
1 medium single serving bag   87     1 fast food order             9
1 prepackaged single serving  43     1 order                       8
```

**全部是包装规格 / 快餐份量，不是通用"一份"。** 真正形如 `1 serving (…)` 的只有极少数，
且各自带着独特括号说明：

```
2706445 Chicken kiev                     '1 serving (1 whole breast)'   258 g
2706468 Meat loaf, Puerto Rican style    '1 serving (3" x 1" x 2")'      95 g
2706518 Pig's feet …                     '1 serving (2 pig's feet, …)'  206 g
```

写键的四条否决理由：

1. **覆盖率荒谬**：13224 个食物里只有个位数能拿到 `serving` 键，其余 5321 个有 qns 的食物
   仍要走回退 → **双轨语义**，手册写不出一句话说清 agent 该看哪个。
2. **`resolve_portion` 会优先读键**（`if key not in portions` 才走回退），
   所以写键 = 让 5 个食物的行为与其余全库**不同**，正是 `docs/landing-review.md` 判 FAIL 的那件事。
3. **qns 就是通用版**，5326 个食物覆盖，语义更正、来源更统一。
4. **不变式已由构造保证**：`_NEW_PORTION_KEYS` 不含 `serving`，`_overlay_keys` 永不返回
   `"serving"`，legacy `_portion_key` 也没有 serving 模式，且 `_apply_safe_overlay` 对未知键
   直接 `RuntimeError`。**"catalog 永远不含 serving 键" 是被代码强制的，不只是文档约定。**
   → 因此 `resolve_portion` 里 `portions["serving"]` 那条查表分支**保留但恒不命中**，
   作为将来手写 serving 的逃生口；在 docstring 里注明"catalog 按构造不写此键"。

### 3.3 实施范围

**改**（1 处，4 行）：
```python
# src/nutrienv/world/portions.py::_serving_default
for key in ("qns", "piece", "slice", "cup"):
```
外加 docstring 从 *"piece, else slice, else cup"* 改为
*"FNDDS QNS (modifier 90000), else piece, else slice, else cup"*，
以及模块头 docstring 里 `"a serving of X"` 那段的同步说明。

**不改**：`UNIT_SYNONYMS` 的 serving/portion/bowl/plate/order 映射、
`_dish_noun_grams` 的结构、`DISH_NOUNS` 集合、catalog、gold JSON、`build_fdc_catalog.py`。

### 3.4 风险

| 风险 | 评级 | 缓解 |
|---|---|---|
| 冻结 240 破 Oracle | **无**（三重实测为 0，见 §2.4.4） | landing_verify 式重放列入验收 |
| 5 条 `fz-dish-*` 改数 → 未来生成的题克数变 | 中 | 这 5 条正是 judge 灰区三对；灰区实验已跑完（`reports/gray-zone-probe.md`），结论支持 qns 侧 |
| `oats` 10 g / `spinach` 13 g 型退化 | 中 | 步骤 3 抽查点名复核；若判定不可接受，退路是**只对 dish-noun 路径用 qns**、`"a serving of <staple>"` 保持旧回退（但会重新引入双轨语义，不推荐） |
| `explain_grams` gloss 变化 | 低 | 与 §2.3.1 的 `_EXPLAIN_UNITS` 白名单一起处理 |

### 3.5 对 240 的 phrase 级实证（复述关键数字）

- 含 serving 类词的 query：**4 条**，全部是 `plate` 的比喻用法，**均不进 `resolve_portion`**。
- 走 `_serving_default` 的 phrase：**0 条**（197/207 用显式量具，另 10 条 dish 不在 240 里）。
- `validate_draft` 240/240 绿（改前改后一致）；`validate_oracle_grams` 33 条 flag（改前改后逐条相同）。

---

## 4. `react.py` 手册更新文案

### 4.1 `_SYSTEM_V1_TAIL` 替换文本

替换 `src/nutrienv/harness/react.py:69-71`：

```python
_SYSTEM_V1_TAIL = """
- Spoken household measures appear on get_food as portions: each key is one measure, the value is grams for one of that measure of that food. Convert the spoken quantity from that table. Do not invent grams from prior knowledge.
- Keys you may be asked for by name: cup, tbsp (tablespoon), tsp (teaspoon), slice, piece (also "each"), can, fl_oz (fluid ounce).
- "a serving / a portion / a bowl / a plate / an order of X", and a dish named as its own unit ("a sandwich", "two burritos"), all mean one default serving: read portions.qns; if the food has no qns, fall back to piece, then slice, then cup.
- "thick", "thin" and "regular" pick a different default serving of the same food: read portions.thick / portions.thin / portions.regular. They are not slice sizes -- "a thick slice" is not portions.thick, and a food without that key has no thick/thin/regular serving.
- An ounce is always 28.35 g, whatever the table says. Grams ("150 g") are already grams.
- Other portion keys you may see (oz, oz_yield, cubic_inch) are reference data, not measures a user speaks. Do not convert with them.
"""
```

### 4.2 手册 ↔ `resolve_portion` 对称检查

硬纪律 4 要求：**手册里出现的每个表达，`resolve_portion` 必须能解析**。逐条核验（原型实测）：

| 手册提到的表达 | `resolve_portion` 支持？ | 实测 |
|---|---|---|
| `cup` / `tbsp` / `tablespoon` / `tsp` / `teaspoon` | ✅ 既有 | `milk_whole "half a cup"` = 122.0 |
| `slice` / `piece` / `each` / `can` | ✅ 既有 | `cheddar "a slice"` = 21.0 |
| `fl_oz` / `fluid ounce` | ✅ **本次新增** | `milk_whole "8 fl oz"` = 244.0 |
| `serving` / `portion` / `bowl` / `plate` / `order` | ✅ 既有，语义本次改 | `orange "a serving"` = 154.0 |
| dish-noun（`a sandwich` / `two burritos`） | ✅ 既有，语义本次改 | `2706880 "a sandwich"` = 115.0 |
| `thick` / `thin` / `regular` | ✅ **本次新增** | `2705824 "a thick steak"` = 240.0 |
| `28.35 g` 的 ounce | ✅ 既有 | `cheddar "2 oz"` = 56.7 |
| `150 g` | ✅ 既有 | `shrimp "150 g"` = 150.0 |

**反向对称**（手册里**没有**、语法也**不该**认的）：`oz_yield`、`cubic_inch` —— 两者都不在
`UNIT_SYNONYMS`，`"a cubic inch"` 实测返回 `None`。✅

**手册明确写出的拒绝语义**："a thick slice" is not portions.thick、
"a food without that key has no thick/thin/regular serving" —— 对应 §2.1.2 的两条 `None` 规则，
让 agent 知道该回去问克数而不是硬猜。

---

## 5. phrase → key → grams 测试清单

新增 `tests/test_portions.py::test_*`（沿用该文件既有的 in-memory fixture 风格 +
少量真实 catalog 用例）。下表**全部数值来自原型实测**，可直接抄成断言。

### 5.1 修饰词（thick / thin / regular）

| # | food_id | phrase | 期望 key | 期望 grams |
|---|---|---|---|---|
| M1 | `2705824` Beef, steak, NFS | `a thick steak` | `thick` | **240.0** |
| M2 | `2705824` | `two thin steaks` | `thin` ×2 | **240.0** |
| M3 | `2705824` | `a regular steak` | `regular` | **160.0** |
| M4 | `2705824` | `a thick serving` | `thick` | **240.0** |
| M5 | `2706880` Sandwich, NFS | `a regular serving` | `regular` | **115.0** |
| M6 | `2707684` Bagel | `a thin serving` | `thin` | **46.0** |
| M7 | `2708312` Waffle, NFS | `a thick serving` | `thick` | **135.0** |
| M8 | `2705824` | `a thick slice` | —（显式量具 + 修饰词） | **None** |
| M9 | `2705824` | `two thin slices` | — | **None** |
| M10 | `2707777` Bread, multigrain | `two thin slices` | — | **None**（**回归护栏**：不得变成 84.0） |
| M11 | `2707777` | `two slices` | `slice` ×2 | **48.0**（不变） |
| M12 | `2705824` | `a large steak` | —（`REFUSED_MODIFIERS`） | **None** |
| M13 | `2705866` Pork, chop | `a thick pork chop` | —（`chop` 不在 `DISH_NOUNS`） | **None** |
| M14 | `2705824` | `a thick` | —（无单位可绑） | **None** |
| M15 | fixture（无 thick 键） | `a thick sandwich` | —（键不存在） | **None** |

### 5.2 `fl_oz`

| # | food_id | phrase | 期望 key | 期望 grams |
|---|---|---|---|---|
| F1 | `milk_whole` | `8 fl oz` | `fl_oz` ×8 | **244.0** |
| F2 | `milk_whole` | `a fluid ounce` | `fl_oz` | **30.5** |
| F3 | `milk_whole` | `12 fluid ounces` | `fl_oz` ×12 | **366.0** |
| F4 | `soy_milk` | `8 fl oz` | `fl_oz` ×8 | **244.0** |
| F5 | `milk_whole` | `an ounce` | 常量 `OUNCE_GRAMS` | **28.35**（**不得**被 `fl_oz` 抢走） |
| F6 | `oats`（无 fl_oz 键） | `8 fl oz` | — | **None** |

### 5.3 `serving` 默认改用 qns

| # | food_id | phrase | 期望 key | 期望 grams | 现状 |
|---|---|---|---|---|---|
| Q1 | `orange` | `a serving` | `qns` | **154.0** | 15.0 |
| Q2 | `broccoli` | `a serving` | `qns` | **45.0** | 10.0 |
| Q3 | `avocado` | `a serving` | `qns` | **30.0** | 15.0 |
| Q4 | `peanut_butter` | `a serving` | `qns` | **32.0** | None |
| Q5 | `potato` | `a serving` | `qns` | **285.0** | 230.0 |
| Q6 | `cheddar` | `a serving` | `qns`(=slice) | **21.0** | 21.0（不变） |
| Q7 | `167668` fried rice（sr_legacy，无 qns） | `a serving of fried rice` | `cup` 回退 | **137.0** | 137.0（不变） |
| Q8 | `salmon`（无任何份量键） | `a serving` | — | **None** | None（不变） |
| Q9 | `2706880` | `a sandwich` | `qns` | **115.0** | 175.0 |
| Q10 | `2706880` | `two sandwiches` | `qns` ×2 | **230.0** | 350.0 |
| Q11 | `2707198` omelet | `an omelet` | `qns` | **110.0** | 55.0 |
| Q12 | `2708750` lasagna | `a serving of lasagna` | `qns` | **250.0** | 206.0 |
| Q13 | `2706880` | `some sandwich` | —（无数量） | **None** | None（**回归护栏**：空跨度守卫） |
| Q14 | `oats` | `a serving` | `qns` | **10.0** | 80.0（**已知退化，断言现状而非期望**，见 §3.4） |

### 5.4 不进语法的键（负向测试，防止将来手滑接入）

| # | food_id | phrase | 期望 |
|---|---|---|---|
| N1 | `cheddar`（有 `cubic_inch=17`） | `a cubic inch` | **None** |
| N2 | `pasta`（有 `oz_yield=80`） | `an ounce` | **28.35**（走常量，**不得**读成 80） |
| N3 | `pasta` | `2 ounces` | **56.7** |
| N4 | 任意有 `oz=28.35` 的食物 | `an ounce` | **28.35**（读表与常量同值，不能改成读表） |

### 5.5 手册对称性测试（新增，机械化硬纪律 4）

```python
def test_manual_expressions_all_resolve():
    """Every measure word the v1 manual names must parse (AGENTS.md rule 4)."""
    manual = react_manual("v1")
    for word in ("cup", "tbsp", "tsp", "slice", "piece", "can", "fl_oz",
                 "serving", "thick", "thin", "regular"):
        assert word in manual
    # …并对每个词跑一条 phrase→grams 断言（复用 5.1–5.3 的用例）
```

反向：断言 `"oz_yield"` / `"cubic_inch"` 出现在手册里时**只作为 "do not convert" 的反例**，
且 `UNIT_SYNONYMS` 里没有它们。

---

## 6. 实施顺序与验收

每一步都是可独立回滚的冻结边界。步骤 3 是唯一会改数的一步，单独一个 commit。

### 步骤 1 —— 修饰词 + `fl_oz`（纯增量，不改任何已有数字）

**改**：`portions.py`（`MODIFIER_KEYS` / `REFUSED_MODIFIERS` / `UNIT_BIGRAMS` / 主循环与
`_dish_noun_grams` 的修饰词分支 / `_leading_quantity` 空跨度守卫保留）、
`react.py::_SYSTEM_V1_TAIL`、`build_review_sheet.py::_EXPLAIN_UNITS` 改显式白名单。

**验收**：
1. `pytest -q` 全绿（基线 **213 passed**，加上 §5.1/§5.2/§5.5 新测试后应为 213 + N）。
2. 240 条 `validate_draft(task) == []` —— **240/240**。
3. **改数为零证明**：跑一遍 207 条 realization phrase 的 old-vs-new 重放，
   要求 **0 条数值变化**（本步只允许 `None → 数` 和 `数 → None`，
   且 `数 → None` 只能出现在 `REFUSED_MODIFIERS` 用例上，realization 里没有）。
4. `explain_grams("milk_whole", 122.0, catalog) == "0.5 x cup (244.0 g) = 122.0 g"`
   —— 显式断言 gloss 未被 `fl_oz` 抢走。
5. §5.5 手册对称性测试通过。

### 步骤 2 —— review sheet / 差距审计复跑（观测，不改行为）

**做**：`scripts/build_review_sheet.py`（默认 SHA 校验，不加 `--allow-catalog-sha-mismatch`）
+ `scripts/qns_gap_audit.py` 复跑，产出步骤 3 决策所需的最新数字。

**验收**：sheet 生成成功且 240 条 gloss 与步骤 1 之前逐条相同（diff 为空）。

### 步骤 3 —— qns 作 serving 默认（**唯一会改数的一步**）

**前置：已满足。** judge 灰区三对（sandwich 1.5× / lasagna 1.2× / omelet 2.0×）已由
`scripts/gray_zone_probe.py` 跑完，结果见 `reports/gray-zone-probe.md`——
这三对的两个候选值正是本步的 before/after（§2.4.4），实验结论支持 qns 侧（§2.4.2 (c)）。

灰区报告自身的待办（"封 gate 前先白名单 FNDDS 表值，不要把阈值降到 0.4"）
属 **judge 侧**，与本步正交：白名单落地后 55 和 110 都会被 gate 接受，
不影响解析器该选哪个。**本步不再被灰区门阻塞。**

**改**：`portions.py::_serving_default` 的键顺序 + 两处 docstring。**仅此。**

**验收**：
1. 240 条 `validate_draft(task) == []` —— **240/240**。
2. `validate_oracle_grams` 在 240 条上的 flag 集合与落地前**逐条字符串相同**
   （当前基线：**33 条**）。
3. 207 条 realization phrase 重放：**恰好 5 条变化**，且逐条等于 §2.4.4 表
   （175→115、270→180、175→131、55→110、206→250）；**其余 202 条必须逐位相等**。
4. `realizations.py` 的 7 个 `assert_*_rows(catalog)` 全过（无 phrase 变成 `None`）。
5. `pytest -q` 全绿。
6. **人工抽查 20 个食物**的新 serving 值，必须包含点名项：
   `oats`(10.0)、`spinach`(13.0)、`orange`(154.0)、`broccoli`(45.0)、`peanut_butter`(32.0)、
   `2706880`(115.0)。抽查结论写进落地报告；若 `oats` 型退化被判定不可接受，
   **本步整体回滚**，不做局部特判。
7. 全库退化指标复核：`<5 g` ≤ 50、`>1000 g` ≤ 8、可解析 serving 数 = 8795。

### 步骤 4 —— 文档与 ADR 收口

**做**：更新 `docs/llm-generated-exam-data.md` 第 7 节（第 1/3 步标记完成、
`oz` 接入建议标记"已关闭：242 个值全等于 28.35，读表无收益"）；
`reports/landing-report.md` 的"未接入语法"一节改为指向本文件；
新增 `docs/adr/0011-portion-grammar-modifiers-and-qns-serving.md` 记录三个决策。

**验收**：文档里出现的每个数字都能被 §1/§2 的复跑脚本重现。

### 步骤 5 —— 可选后续（本轮明确不做，登记在案）

| 项 | 内容 | 触发条件 |
|---|---|---|
| 5a | `dry / raw / uncooked` 纳入拒绝词类，修掉 `"1 oz dry"` 静默返回 28.35 | 语法开始关心单位**之后**的 token 时 |
| 5b | `_matches_portion_table` 只用"语法可达"的键当锚点 | 有人抱怨 `validate_oracle_grams` 太松 |
| 5c | `cubic_inch` bigram 接入 | 真的出现 cubic inch 口语题 |
| 5d | `oz_yield` 生/干态设计 | judge 灰区门过 + 食物层 raw/cooked 配对确认 |

---

## 7. 附：复跑本文所有数字

```bash
# catalog 键分布、oz 全等 28.35、thin/slice 比值、regular vs qns
.venv/bin/python -c "..."     # 见 §1.1 / §2.1.1 / §2.2.1（sqlite 直读 foods.portions）

# 两种回退的覆盖率与退化数
.venv/bin/python -c "..."     # 见 §2.4.2 (b)

# 207 条 realization phrase 的 old-vs-new 重放 + 240 条 validate_draft
.venv/bin/python scripts/landing_verify.py

# FNDDS 原始行来源分布（thick/thin/regular/fl_oz/oz/oz_yield 各自的获胜描述）
.venv/bin/python -c "..."     # 复用 build_fdc_catalog._overlay_keys + _row_sort_key
```

> 本设计的原型实现（一次性验证用，**不入库**）位于本次会话的 scratchpad
> `.../scratchpad/proto.py`，实现了 §2.1.2 / §2.3.1 / §2.4.1 的全部规则，
> 并已用它跑出上文所有 `now → new` 数值、240 条 `validate_draft`（0 failures）
> 与 7 个 `assert_*_rows`（全过）。
