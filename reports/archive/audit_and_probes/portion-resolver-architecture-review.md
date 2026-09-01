# Portion Resolver 架构优化调查报告

> 问题：`resolve_portion` 现在只认很小一组量词，但我们需要 `glass / mug / bottle / scoop / pat / handful / fist-sized / palm-sized / deck-of-cards / dollop / splash / drizzle` 这类母语者真实表达。
> 本报告回答三件事：这个部件能不能优化掉？它卡在哪？建议怎么改？

---

## 1. `resolve_portion` 不能被优化掉

它是 pipeline 的确定性锚点，作用不是“多认几个词”，而是保证一条铁律：

**Grams 从不穿过 LLM；题面量词必须能由代码映射回 FNDDS PortionFact。**

它被以下关键路径依赖：

| 调用方 | 用途 |
|---|---|
| `pipeline/resolver.py::resolve_candidate` | 把 expander 输出的 `(food, expression)` 变成 oracle grams |
| `pipeline/resolver.py::query_backresolves_oracle` / `spoken_grams_from_query` | 检查 query 里的口语短语是否解析回同一克数 |
| `bench/validator.py::validate_oracle_grams` | 校验已冻结 Task 的 oracle grams 是否可溯源 |
| `bench/realize.py::_require_portion` | 把 gold realization row 的 phrase 换算成 grams 来生成 oracle |
| `bench/realizations/checks.py` | 冻结 exam 行合法性检查 |
| `pipeline/generate_one.py` | synthetic 生成器的 amount_path / QNS / named-measure 路径 |

结论：**优化掉 = 把 gram 事实源交给 LLM，会让 frozen exam、validator、backresolve 全部失去确定性。** 所以不能删，只能把它的“词表”从手写小语法升级为数据驱动。

---

## 2. 真正的瓶颈：不是 parser，是 catalog 的 portion key 太粗

`catalog-v2.sqlite` 的 `portions` JSON 只有：

```text
cup, tbsp, tsp, slice, piece, can, fl_oz, oz, qns, serving, thick, thin, regular, cubic_inch
```

而 FNDDS `food_portion.csv` 里其实还有大量可直接落成 key 的母语单位：

| FNDDS portion_description | 频率 | 可落的新 key |
|---|---|---|
| `1 glass` | 12 | `glass` |
| `1 bottle` / `1 bottle (12 fl oz)` | 145 | `bottle` |
| `1 scoop` | 36 | `scoop` |
| `1 patty` / `1 pat` | 54+ | `patty` |
| `1 packet` / `1 pouch` / `1 bar` / `1 stick` | 多 | `packet` / `pouch` / `bar` / `stick` |
| `1 egg` / `1 muffin` / `1 pancake` / `1 waffle` / `1 cookie` | 多 | 食物名词本身（dish noun） |
| `1 sandwich` / `1 submarine` / `1 taco salad` | 多 | dish noun / 新 key |
| `Guideline amount per sandwich` / `per slice of bread` / `per piece of sushi` | 163 | 可支撑 `dollop / spread / topping` 类解析 |

社区侧还有 FNDDS 没有、但母语者高频使用的量词：`handful, fist-sized, palm-sized, deck-of-cards-sized, dollop, splash, drizzle`。这些不能靠 resolver 硬猜，必须作为**第二事实源**进入 catalog。

所以优化方向是：**把 `resolve_portion` 从“parser + 小词表”升级为“parser + 数据驱动词表 + catalog overlay”。**

---

## 3. 三个方案对比

### 方案 A：Catalog 升级 + 保留 resolver（推荐）

- 在 catalog 构建阶段从 `food_portion.csv` 多落一组新 key：`glass, bottle, scoop, patty, packet, pouch, bar, stick` 等，每条保留 `(source_description, modifier, gram_weight)` 来源。
- 新增一个 `colloquial_portion_overlay.json`，人工维护社区/FMB 单位的按食物类别克数（如 `fist` ≈ 1 cup for mashed/rice; `palm` ≈ 3 oz cooked meat; `deck_of_cards` ≈ 85g meat/fish; `dollop` ≈ 2 tbsp; `splash` ≈ 1–2 tbsp; `drizzle` ≈ 1 tsp–1 tbsp），每项带来源标注，且只在显式审核后进 catalog。
- `resolve_portion` 保持不变的外部签名，内部增加对新 key 的查找与同义词归一。

优点：不破坏既有合约；新单位都可溯源；自然表达丰富度直接由 catalog 驱动。
缺点：要动 catalog 构建 + 跑一次重建/dry-run；community overlay 需要人工 review。

### 方案 B：LLM 归一化 resolver（不推荐）

让 LLM 把 `a fist-sized sweet potato` 归一成 `a cup`，然后 resolver 再解析。

优点：省人工。
缺点：LLM 进入 gram 路径，破坏“grams never pass through LLM”的铁律；frozen exam 不再可复现；validator/backresolve 会失守。**否决。**

### 方案 C：生成侧自然化 + 评分侧保守解析（可叠加，但不能替代 A）

- expander 可以自由生成 `a bowl of pasta`、`a glass of milk` 等 query。
- 但 `items[].expression` 必须写 resolver 能解析的 canonical 单位。
- 这只能让题面“看起来”丰富，不能让 resolver 真正认更多口语表达；只适合作为 A 之前的过渡，或作为 few-shot 生成策略。

---

## 4. 推荐目标架构

```
                 ┌─────────────────────────────────────────────┐
                 │           Portion Lexicon (versioned)        │
                 │  FNDDS explicit keys (glass/bottle/scoop/…)  │
                 │  + Colloquial overlay (fist/palm/deck/…)     │
                 │  + Provenance: source row / citation          │
                 └───────────────┬──────────────────────────────┘
                                 │ builds
                                 ▼
catalog-v3.sqlite  portions: {"cup":…, "glass":…, "scoop":…, "fist":…, …}
                 │
                 ▼
  spoken phrase: "a fist-sized sweet potato"
                 │
                 ▼
resolve_portion:
  1. tokenize / collapse bigrams ("fl oz", "deck of cards")
  2. unit-synonym normalize ("fist-sized" -> "fist", "glass" -> "glass")
  3. parse quantity (existing code, keep it)
  4. look up catalog key (existing code, keep it)
  5. fallback serving/dish-noun logic (existing code, keep it)
  6. else None (fail closed, keep it)
```

关键点：
- `resolve_portion` 的函数签名和“解析失败返回 None”的契约不变。
- 新单位一律先落 catalog，resolver 只查表，不内嵌克数。
- 社区 overlay 是 versioned data，不是代码。

---

## 5. 具体落地步骤

1. **Catalog 层**
   - 修改 `scripts/build_fdc_catalog.py`：
     - 增加 `_NEW_NATIVE_UNITS` 规则，从 `portion_description` 提取 `glass, bottle, scoop, patty, packet, pouch, bar, stick` 等新 key。
     - `collect_full_portion_wins` 已经能保存 `sources`；把 `sources` 写进 catalog（新增 `portion_sources` JSON 列），每条 gram 可溯源。
   - 新建 `data/portion/colloquial_portion_overlay.json`，第一版只放有把握的：
     - `deck_of_cards` = `oz`/`piece` 同值（85g 熟肉/鱼）
     - `palm` = 3 oz 熟肉/禽/鱼（85g）
     - `fist` = 1 cup 蔬菜/米/面/土豆泥（对应食物 cup 值）
     - `dollop` = 2 tbsp（30g 酱/酸奶/奶油类）
     - `splash` = 1 tbsp（15g 液体类）
     - `drizzle` = 1 tsp（5g 油/糖浆类）
     - `handful` = 1 oz（28g 坚果/零食/莓果类）
   - 跑 dry-run，审查覆盖率和冲突。

2. **Resolver 层**
   - `UNIT_SYNONYMS` 增加：`glass/glasses, mug/mugs, bottle/bottles, scoop/scoops, pat/patty/patties, packet, pouch, bar, stick` 等，指向新 catalog key。
   - 增加 bigram：`("deck","of") -> "deck_of_cards"`? 更稳妥是 `deck-of-cards` 作为一个词条；`("fist","sized") -> "fist"`；`("palm","sized") -> "palm"`。
   - 保持 fail-closed：新 key 在 catalog 不存在时返回 None，不 fallback 到 cup。

3. **Expander 层**
   - `portion_alternatives` 和 `_natural_portion_hints` 改为读同一 lexicon，避免 prompt 里的量词和 resolver 脱节。
   - 给 qwen 的 few-shot 示例补上 `a glass of milk`、`a scoop of protein`、`a pat of butter`。

4. **测试**
   - 单测覆盖每个新单位：正例解析、缺 key 返回 None、新旧行为不变。
   - 全量 pytest（当前 1356）必须仍通过。
   - `assert_fuzzy_resolves` 等 gold 行检查仍然通过。

---

## 6. 风险与护栏

- **不要内嵌克数进 resolver**：`dollop` 等克数进 data，不进代码。
- **不要静默 fallback**：`a glass of olive oil` 如果该食物没有 `glass` key，应返回 None，而不是猜 cup。
- **保持 frozen exam 兼容**：只新增 key 和 synonym；现有 `cup/slice/piece/serving/qns` 行为不变。
- **community overlay 必须可溯源**：每条记录带来源（FMB 页/社区语料/营养库），review 后才能进 catalog。

---

*调查时间：2026-08-23 | 状态：建议方案 A，待确认后实施*
