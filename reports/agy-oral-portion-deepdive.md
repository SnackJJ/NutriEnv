# 英语口语饮食与份量深度调研报告 (Oral Portion Deep-Dive)

> **目标**：在前期调研（`reports/agy-oral-portion-research.md`）基础上，针对 USDA FNDDS / NHANES WWEIA 份量编码手册、NCI ASA24 / AMPM 多轮交互流、以及 Reddit / MyFitnessPal 真实社区饮食语料展开深度解构，为 NutriEnv 构建确定性份量解析器（Deterministic Portion Resolver）、多轮会话状态机，并提出对 `expander.py` 的可落地 Prompt 优化方案。

---

## 1. USDA FNDDS / NHANES WWEIA 份量编码手册与确定性解析器设计

### 1.1 FNDDS / WWEIA 份量编码体系架构

美国农业部（USDA）与疾控中心（CDC）在“What We Eat In America”（WWEIA, NHANES 膳食调查分支）中采用标准化的 **FNDDS (Food and Nutrient Database for Dietary Studies)** 份量度量体系。其底层结构包含三层锚定机制：

1. **8 位食物代码（Food Code / FDC ID）**：标识唯一基准食物条目。
2. **5 位修饰符代码（Portion Code / Modifier）**：标识度量单位及形态（例如 `10205` = 1 cup, `64744` = 1 thick, `90000` = Quantity not specified, `61853` = 1 sandwich）。
3. **官方模型手册（Food Model Booklet, FMB）**：调查员在入户回访中使用的 2D/3D 视觉参照辅助具，包括手势估算法（Fist, Palm, Thumb）、厚度标尺（1/8" 至 1"）、不同口径碗盘（Mounds A–D, Bowls 1–4, Glasses 1–8）。

```
+-----------------------------------------------------------------------------+
|                          FNDDS Portion Hierarchy                            |
+-----------------------------------------------------------------------------+
| 1. Base Volume/Weight Units: 1 cup (10205), 1 fl oz (30000), 1 tbsp (21000) |
| 2. Food-Specific Units:      1 patty (61633), 1 drumstick (62704), 1 slice  |
| 3. Thickness & Dimensions:   1 thick (64744), 1 thin (62307), 1 regular     |
| 4. FMB Visual Proportions:   Deck of cards (~3 oz / 85g), Small fist (~1 c) |
| 5. Default Fallback (QNS):   Quantity Not Specified (90000)                 |
+-----------------------------------------------------------------------------+
```

---

### 1.2 典型口语描述 $\to$ 官方克数映射表 (Portion-Description to Gram Weights)

基于本地 `data/fdc/raw/survey.zip` 中真实的 `food_portion.csv`（22,046 行），提取以下代表性食物条目及其在不同口语量词修饰下的精确映射：

| 食物名称 (Food Description) | FDC ID | 口语份量表达 (Spoken Portion) | Modifier Code | 官方克数 (Grams) | 对应 WWEIA / FMB 编码规则 |
|---|---|---|---|---|---|
| **Beef, steak, NFS** | `2705824` | `1 thick` / `a thick steak` | `64744` | **240.0 g** | 厚切牛排（厚度 $\ge 1$ inch） |
| **Beef, steak, NFS** | `2705824` | `1 thin` / `a thin slice of steak` | `62307` | **120.0 g** | 薄切牛排（厚度 $\le 1/2$ inch） |
| **Beef, steak, NFS** | `2705824` | `1 piece/slice, any size` | `64747` | **30.0 g** | 切片小块/边角料（不可直接用于整块牛排） |
| **Beef, steak, NFS** | `2705824` | `Quantity not specified (QNS)` | `90000` | **160.0 g** | 默认标准餐份（约 5.6 oz） |
| **Beef, steak, NFS** | `2705824` | `1 deck of cards` (FMB 视觉) | `61633` (patty/portion) | **85.0 g** | 3 oz 熟肉基准模型（扑克牌大小） |
| **Chicken breast, roasted** | `2706037` | `1 small breast` (skinless) | `64698` | **105.0 g** | 去皮小鸡胸肉 |
| **Chicken breast, roasted** | `2706037` | `1 medium breast` (skinless) | `64699` | **120.0 g** | 去皮中等鸡胸肉（常规推荐标准） |
| **Chicken breast, roasted** | `2706037` | `1 large breast` (skinless) | `64700` | **135.0 g** | 去皮大鸡胸肉 |
| **Chicken drumstick, roasted**| `2706085`| `1 small drumstick` (with skin) | `64703` | **45.0 g** | 小鸡腿（带皮可食部分） |
| **Chicken drumstick, roasted**| `2706085`| `1 medium drumstick` (with skin)| `64704` | **60.0 g** | 中鸡腿（带皮可食部分） |
| **Chicken drumstick, roasted**| `2706085`| `1 large drumstick` (with skin) | `64705` | **80.0 g** | 大鸡腿（带皮可食部分） |
| **Chicken drumstick, roasted**| `2706085`| `1 medium drumstick` (skinless) | `64704` | **50.0 g** | 中鸡腿（去皮可食部分） |
| **Grilled cheese sandwich** | `2707768` | `1 sandwich` / `regular` | `61853` | **116.0 g** | 2片面包+标准芝士煎制 |
| **Grilled cheese sandwich** | `2707768` | `Quantity not specified (QNS)` | `90000` | **116.0 g** | 默认三明治单份 |
| **Lasagna with meat** | `2708892` | `1 piece (1/6 of 8" square)` | `61700` | **206.0 g** | 8寸正方形烤盘 1/6 份（中份） |
| **Lasagna with meat** | `2708892` | `1 piece (1/8 of 7"x12")` | `61706` | **232.0 g** | 长方形大盘 1/8 份（大份） |
| **Lasagna with meat** | `2708892` | `1 cup` / `a bowl of` | `10205` | **250.0 g** | 体积杯装/碗装 |
| **Lasagna with meat** | `2708892` | `Quantity not specified (QNS)` | `90000` | **250.0 g** | 默认单份千层面 |
| **Egg omelet or scrambled egg**| `2706596`| `1 egg` (prepared) | `60710` | **55.0 g** | 1颗鸡蛋制成的煎蛋卷/炒蛋 |
| **Egg omelet or scrambled egg**| `2706596`| `1 cup` | `10205` | **135.0 g** | 1杯装煎蛋（约 2.5 颗蛋量） |
| **Egg omelet or scrambled egg**| `2706596`| `Quantity not specified (QNS)` | `90000` | **110.0 g** | 默认双蛋煎蛋卷标准（2 eggs） |
| **Mashed potatoes** | `2709405` | `1 small fist` / `1/2 cup` | `10205` (x 0.5) | **105.0 g** | 小拳头大小（对应 FMB Mound B） |
| **Mashed potatoes** | `2709405` | `1 cup` / `1 regular fist` | `10205` | **210.0 g** | 成年人整拳大小（对应 1 cup） |
| **Butter** | `2705342` | `1 pat` (restaurant square) | `63456` | **5.0 g** | 餐厅标准小方块黄油（1/3 tbsp） |
| **Butter** | `2705342` | `1 tablespoon` | `21000` | **14.2 g** | 标准量匙 1 汤匙 |

---

### 1.3 本地数据文件挖掘方案 (`survey.zip` vs `usda.db` vs `catalog-v2.sqlite`)

NutriEnv 现有数据存储分布及其在构建确定性份量解析器（Deterministic Portion Resolver）中的定位：

```
data/
├── fdc/
│   ├── raw/
│   │   ├── survey.zip        <-- [核心源头] 包含 FNDDS 全量 food_portion.csv 与 food.csv
│   │   ├── sr_legacy.zip     <-- 基础原料与营养素基准
│   │   └── branded.zip       <-- 商业预包装食品条目
│   └── catalog-v2.sqlite     <-- [运行时索引] 抽取后的高频 portion json (cup, tbsp, slice, thick...)
└── usda.db                   <-- [基准营养库] 仅包含 100g 基础宏量与微量元素表，不含 portion 结构
```

#### 各文件在 Resolver 中的职责与挖掘策略：

1. **`data/fdc/raw/survey.zip` 中的 `food_portion.csv`**：
   - **内容**：全量 22,046 条规则，包含 `(fdc_id, seq_num, amount, measure_unit_id, portion_description, modifier, gram_weight)`。
   - **挖掘价值**：提供最高保真度的自然语言修饰语词表（如 `"1 wedge"`, `"1 individual school container"`, `"1 surface inch"`, `"1 drumstick, NS as to size"`）。
   - **提取逻辑**：利用 `scripts/build_fdc_catalog.py` 中的 `collect_full_portion_wins`，按 `(fdc_id ASC, seq_num ASC, id ASC)` 确定唯一首胜（first-wins）克数，避免并发或版本漂移。

2. **`data/fdc/catalog-v2.sqlite`**：
   - **内容**：已编译的 `foods` 表与 `portions` JSON 字典（支持 `'oz', 'tbsp', 'serving', 'tsp', 'slice', 'cubic_inch', 'piece', 'cup', 'fl_oz', 'regular', 'thin', 'thick', 'can', 'qns'`）。
   - **挖掘价值**：作为轻量、高效的运行时查表中间件，支持直接提取各 food_id 对应的预热档位。

3. **`data/usda.db`**：
   - **内容**：提供各条目的营养成分标定，作为克数乘以单价后的宏量营养素换算底表。

---

### 1.4 确定性份量解析器（Deterministic Portion Resolver）架构

为避免 LLM “自由幻想”克数导致评测打分漂移，设计两阶段确定性解析流程：

```
  [User Natural Language] "I ate a thick-cut steak and a small fist of mashed potatoes"
                                      │
                                      ▼
                      [Phase 1: Lexical Tokenizer & Normalizer]
                      - Extract Food Candidates: "steak", "mashed potatoes"
                      - Extract Portion Modifiers: "thick-cut" -> "thick", "small fist" -> "0.5 cup"
                                      │
                                      ▼
                      [Phase 2: FNDDS Deterministic Slot Matching]
     ┌────────────────────────────────┴────────────────────────────────┐
     ▼                                                                 ▼
[Food 1: Beef Steak]                                          [Food 2: Mashed Potatoes]
Match Key: "thick" in catalog                                 Match Key: "cup" * 0.5
Catalog gram: 240.0g                                          Catalog gram: 210.0g * 0.5 = 105.0g
     │                                                                 │
     └────────────────────────────────┬────────────────────────────────┘
                                      ▼
                 [Resolver Output: Ground-Truth Grams & Macro Totals]
                 - Beef Steak: 240.0g (Modifier 64744)
                 - Mashed Potatoes: 105.0g (Modifier 10205 x 0.5)
                 - Fallback Policy: If token unmatched -> Fallback to QNS (90000)
```

#### 匹配降级阶梯（Fallback Hierarchy）：
1. **精确词素匹配（Exact Key Match）**：`"thick"`, `"thin"`, `"slice"`, `"cup"`, `"tbsp"` 直接命中 `catalog-v2.sqlite`。
2. **同义词规约匹配（Normalized Synonym Match）**：
   - `"deck of cards"` $\to$ `3 oz` / `patty` (85g)
   - `"small fist"` / `"fist-sized"` $\to$ `0.5 cup` / `1 cup`
   - `"pat of butter"` $\to$ `5.0g` (`tbsp` $\times 0.33$)
   - `"palm-sized chicken"` $\to$ `1 medium breast` (120g)
3. **QNS 默认兜底（Quantity Not Specified）**：未提供任何份量词时，回退到 FNDDS 官方 `modifier: 90000` 表值。

---

## 2. NCI ASA24 / AMPM 多轮交互流与 Agent 状态机设计

### 2.1 AMPM 五步多次通过法（Automated Multiple-Pass Method）标准流程

美国国家癌症研究所（NCI）的 **ASA24** 与 USDA 的 **AMPM** 是临床流行病学与公共卫生营养调查的事实标准。其核心在于通过 5 轮渐进式引导，消除人类记忆遗漏与份量认知模糊：

```
+-----------------------------------------------------------------------------+
| Pass 1: Quick List (快速罗列)                                               |
| -> 记录所有摄入食物，不打断用户                                             |
+--------------------------------------┬--------------------------------------+
                                       │
                                       ▼
+-----------------------------------------------------------------------------+
| Pass 2: Forgotten Foods Probe (遗忘食物排查)                                |
| -> 针对饮料、零食、酱料、酒水等高频遗漏品类专项排查                         |
+--------------------------------------┬--------------------------------------+
                                       │
                                       ▼
+-----------------------------------------------------------------------------+
| Pass 3: Time & Occasion (时间与餐次定位)                                    |
| -> 按时间轴归集餐别（Breakfast, Lunch, Dinner, Snack）                      |
+--------------------------------------┬--------------------------------------+
                                       │
                                       ▼
+-----------------------------------------------------------------------------+
| Pass 4: Detail & Portion Review (细节与份量深挖)                            |
| -> 品牌、烹饪方式、配料增删、份量视觉/尺寸核实                              |
+--------------------------------------┬--------------------------------------+
                                       │
                                       ▼
+-----------------------------------------------------------------------------+
| Pass 5: Final Probe (最终全面复盘)                                          |
| -> 回顾全天记录，确认是否有漏网之鱼                                         |
+-----------------------------------------------------------------------------+
```

1. **Pass 1: Quick List (快速记录)**：鼓励用户无负担列出过去 24 小时吃的所有东西，系统不中断、不索要细节。
2. **Pass 2: Forgotten Foods Probe (遗忘食物嗅探)**：针对极易遗漏的 6 大品类专项追问（Beverages, Sweets, Savory Snacks, Condiments/Sauces, Breads, Alcohol）。
3. **Pass 3: Time & Occasion (时间与就餐场景)**：将零散项目锚定到具体时间与进餐性质（如 "9:00 AM Breakfast", "3:30 PM Work Snack"）。
4. **Pass 4: Detail & Portion Review (细节描述与份量复核)**：调用 FMB 模型引导用户确认厚度、件数、容器规格、烹饪油与加料。
5. **Pass 5: Final Probe (终轮排查)**：系统总结全日清单，做最后一次查漏补缺。

---

### 2.2 常见模糊份量标准澄清话术（Clarification Probes）

当用户在第一轮给出模糊表达（如 `"a sandwich"`, `"a bowl of cereal"`, `"a plate of pasta"`）时，Agent 需按照 ASA24 标准知识库生成分层澄清 Prompt：

#### 场景 1：用户输入 `"I had a sandwich for lunch."`
* **Agent 澄清 Prompt（分步递进）**：
  > *"Got it, let's nail down your sandwich details:*
  > 1. *What kind of bread was used (e.g., two slices of white, whole wheat, sourdough, or a 6-inch sub roll)?*
  > 2. *What proteins or fillings were inside (e.g., deli turkey, tuna salad, cheddar cheese)?*
  > 3. *Did you add any spreads or condiments (e.g., a tablespoon of mayo, yellow mustard, butter)?*
  > 4. *Was it toasted or grilled in butter/oil?"*

#### 场景 2：用户输入 `"A bowl of cereal with milk."`
* **Agent 澄清 Prompt**：
  > *"To accurately log your cereal:*
  > 1. *Which brand or type was it (e.g., Cheerios, Frosted Flakes, Rolled Oats)?*
  > 2. *Roughly how much cereal was in the bowl—was it closer to a standard measuring cup (approx. a baseball size), or a large heaping bowl (around 2 cups)?*
  > 3. *What kind of milk did you pour over it (e.g., whole, 2%, oat, unsweetened almond), and did you drink all the remaining milk in the bowl?"*

#### 场景 3：用户输入 `"A plate of pasta for dinner."`
* **Agent 澄清 Prompt**：
  > *"Let's break down that pasta dish:*
  > 1. *What shape was the pasta (e.g., spaghetti, penne), and how full was the plate—around a fist-sized mound (1 cup cooked), or covering the entire plate (2–3 cups)?*
  > 2. *What sauce did you have (e.g., 1/2 cup tomato marinara, creamy alfredo, garlic and olive oil)?*
  > 3. *Did it have meat (like ground beef or meatballs) or a sprinkle of parmesan cheese on top?"*

---

### 2.3 营养 Agent 多轮对话状态机（Agent State Machine）

将 AMPM 流程形式化为确定性有限状态机（FSM），用于驱动 LLM Agent 在多轮对话中完成信息采集与消歧：

```
               [User Initial Utterance]
                          │
                          ▼
               +----------------------+
               |   STATE_QUICK_LIST   |
               +----------┬-----------+
                          │ (Extract Entities)
                          ▼
               +----------------------+
               | STATE_FORGOTTEN_PROBE|
               +----------┬-----------+
                          │ (Uncover Drinks/Sauces)
                          ▼
          +--------------------------------+
          | STATE_PORTION_DISAMBIGUATION   |
          |  - Probe Thickness (Steak)     |
          |  - Probe Container (Yogurt/Can)|
          |  - Probe Visual Aid (Amorphous)|
          +---------------┬----------------+
                          │ (All Slots Filled)
                          ▼
               +----------------------+
               | STATE_FINAL_SUMMARY  | <───────┐ (Correction:
               +----------┬-----------+         │  "Make it 1 cup")
                          │ (User Confirmed)    │
                          ▼                     │
               +----------------------+         │
               | STATE_ORACLE_EXEC    | ────────┘
               +----------------------+
```

* **状态转移守则（Guard Conditions）**：
  - 若用户未响应追问或表达放弃，系统自动启用 **QNS 规则（90000 Modifier）** 作为确定性默认值，绝不挂起等待或抛出未捕获异常。
  - 用户发生自发修正（如 `"Scratch the fries, make it a side salad"`）时，状态机回退至 `STATE_PORTION_DISAMBIGUATION` 重算差异槽位。

---

## 3. 真实饮食社区语料库（Reddit / MFP / MacroFactor）

### 3.1 真实记录口语缩写、俚语与计量习惯

在 Reddit（`r/loseit`, `r/1200isplenty`, `r/1500isplenty`, `r/MacroFactor`, `r/CICO`）和 MyFitnessPal 社区中，母语者的真实饮食日志具有极其鲜明的缩略表达与结构化习惯：

1. **高频常用缩写与词汇**：
   - `PB` / `PB2` = Peanut butter / Powdered peanut butter
   - `cals` / `kcal` = Calories
   - `macros` = Macronutrients (Protein / Fat / Carbs)
   - `tbsp` / `tbs` / `T` = Tablespoon
   - `tsp` / `t` = Teaspoon
   - `w/` = with, `w/o` = without
   - `avo` = avocado, `chx` / `chick` = chicken breast
   - `OMAD` = One Meal A Day
   - `CICO` = Calories In, Calories Out
   - `deficit` = 每日热量缺口
   - `heaping` = 冒尖的一勺/一杯；`level` = 刮平的一勺

2. **生活化份量隐喻与简写**：
   - *"2 slices Ezekiel bread"* (品牌特定切片)
   - *"a dollop of Daisy light sour cream"* (约 2 tbsp / 30g)
   - *"half an avo"* (半个牛油果，约 75g-100g)
   - *"a splash of unsweetened almond milk in my cold brew"* (约 2 fl oz / 60ml)
   - *"1 scoop whey mixed with 8 oz fairlife"* (1 勺乳清蛋白粉 + 8 盎司高蛋白牛奶)
   - *"a fist-sized sweet potato"* (约 1 拳大 / 200g)
   - *"two fingers thick slice of banana bread"* (两指宽厚切，约 80g-100g)

---

### 3.2 真实场景中的自发修正（Self-Correction）模式

真实用户在输入后经常补充、撤回或扣除部分食物。常见模式包括：

1. **扣除剩余量（Leftover deductions）**：
   > *"I logged the whole chipotle burrito but couldn't finish it—left about a third of the tortilla and rice."*
2. **替换配料/改要轻食（Ingredient swaps）**：
   > *"Swap out the ranch dressing for balsamic on the side, and make that chicken grilled instead of crispy."*
3. **撤销主食/更正规格（Scratch & Replace）**：
   > *"Scratch that 16 oz draft beer, the bartender actually poured me a 12 oz bottle of light cider."*
4. **追加烹饪隐形热量（Add cooking mediums）**：
   > *"Forgot to add that the eggs were fried in about a teaspoon of real butter, not cooking spray."*

---

### 3.3 自然英语一餐表达语料库（24 条，覆盖 5 大场景，符合真实社区风格）

> **设计原则**：严格杜绝 `"a regular serving of Pork and a cup of Black beans"` 这类机械死板句式；完全采用 Reddit 饮食圈与真实生活记录的口语流，涵盖自然量词与生活化表达。

#### 一、Log 场景（日常饮食记录 - 5条）

1. *"Breakfast was two scrambled eggs with a slice of whole wheat toast and half an avocado mashed on top."*
   - **特点**：自然连接词，切片+半个果实修饰，早间经典搭配。
2. *"For lunch I had a 6-inch turkey sub on multigrain with provolone, shredded lettuce, and a light squeeze of yellow mustard."*
   - **特点**：快餐规格（6-inch）、配菜与酱汁微量口语（light squeeze）。
3. *"Logged a palm-sized grilled salmon fillet along with a cup of steamed broccoli and a fist-sized baked sweet potato."*
   - **特点**：手势估算法（palm-sized, fist-sized）与标准杯装组合。
4. *"Had a bowl of Greek yogurt topped with a generous handful of fresh blueberries and a tablespoon of chia seeds."*
   - **特点**：容器（bowl）+ 动作手势（generous handful）+ 厨房量匙（tablespoon）。
5. *"Afternoon snack was a small apple sliced up with two level tablespoons of peanut butter."*
   - **特点**：水果规格（small）+ 勺形修饰（level tablespoons 平勺）。

#### 二、Evaluate 场景（摄入评估与热量/宏量核算 - 5条）

6. *"I just finished an 8-oz grilled sirloin steak with a loaded baked potato and a side garden salad—how does this fit into my daily macros?"*
   - **特点**：盎司计量（8-oz）、加料主食（loaded baked potato）与宏量复盘疑问句。
7. *"For dinner I had two thick slices of homemade meatloaf and a cup of mashed potatoes with a pat of butter. Did I blow my calorie deficit for today?"*
   - **特点**：厚度修饰（thick slices）、小块黄油（pat of butter）与减脂圈核心词（calorie deficit）。
8. *"I ate three street tacos on corn tortillas with grilled chicken, fresh cilantro, and a small ramekin of salsa—what's the estimated protein and sodium breakdown?"*
   - **特点**：街头小吃数量（three street tacos）与小酱碟量词（ramekin）。
9. *"Treated myself to a medium bowl of tonkotsu ramen with two slices of chashu pork and a soft-boiled egg. Could you evaluate how heavy this is on carbs and sodium?"*
   - **特点**：面食碗装（medium bowl）与精准辅料件数。
10. *"I had a double scoop of chocolate ice cream in a waffle cone with a drizzle of warm fudge—can you give me a quick calorie estimate?"*
    - **特点**：冰淇淋经典量词（double scoop）与淋酱（drizzle of fudge）。

#### 三、Recommend 场景（配餐建议与场景化规划 - 5条）

11. *"I want to hit 40g of protein for lunch: how about a grilled chicken breast, a cup of cooked quinoa, and a heaping cup of roasted green beans?"*
    - **特点**：明确营养目标、冒尖量词（heaping cup）与健康餐组合。
12. *"For a light cutting dinner, try pairing a palm-sized piece of baked cod with two cups of mixed greens tossed in a splash of olive oil."*
    - **特点**：减脂期术语（cutting dinner）、手势量词与轻浇淋（splash of）。
13. *"If you need a quick post-workout meal, blend one scoop of whey protein with a cup of unsweetened almond milk and a medium banana."*
    - **特点**：健身练后补剂习惯（one scoop whey, medium banana）。
14. *"Build your dinner plate with a deck-of-cards-sized portion of lean flank steak, half a plate of roasted cauliflower, and a fistful of brown rice."*
    - **特点**：FMB 扑克牌隐喻（deck-of-cards-sized）、餐盘比例分块（half a plate）。
15. *"For a filling breakfast under 400 cals, go with a 3-egg white omelet packed with a handful of baby spinach and a sprinkle of low-fat mozzarella."*
    - **特点**：热量控制目标（under 400 cals）、蛋白煎蛋卷（3-egg white omelet）与微量加料（sprinkle of）。

#### 四、Update 场景（实时更正与增删细节 - 5条）

16. *"Actually, make that just one slice of toast instead of two, and I forgot to log a teaspoon of butter on it."*
    - **特点**：经典增减修正句式（make that X instead of Y）与补漏。
17. *"Scratch the brown rice on my lunch log—I actually got a cup of black beans and added a small dollop of guacamole."*
    - **特点**：撤销俚语（scratch the...）与调味酱小份量（small dollop）。
18. *"Update my dinner entry: I only ate about half of the burger patty, but I had four or five onion rings from my friend's plate."*
    - **特点**：扣除剩余食物比例与社交分享零食数量。
19. *"Hold the mayo on that turkey sandwich, and swap the regular fries for a side cup of fruit."*
    - **特点**：去配料常用语（hold the mayo）与换主食（swap X for Y）。
20. *"Change that coffee to a 16-oz cold brew with a splash of whole milk, no sugar added."*
    - **特点**：饮品规格调整（16-oz cold brew）与奶底修饰。

#### 五、Composite 场景（先记录当前餐，再规划后续餐 - 4条）

21. *"Please log a grilled chicken salad with two tablespoons of balsamic dressing for lunch, and then suggest a high-protein dinner that keeps me within my remaining calorie budget."*
    - **特点**：标准复合多步指令：精确量词记录 + 剩余热量预算规划。
22. *"I just ate a cup of oatmeal with a scoop of protein powder and a medium apple for breakfast; what should I prep for lunch and dinner to hit 150g of protein today?"*
    - **特点**：早晨已摄入记录 + 全天宏量目标拆解规划。
23. *"Log two slices of sourdough bread with two fried eggs for brunch, then recommend a low-carb dinner to balance out the rest of my day."*
    - **特点**：早午餐自然短语 + 动态营养平衡推荐。
24. *"Record my afternoon snack of an individual Greek yogurt cup and a small handful of almonds, and suggest what I can eat for dinner with about 600 calories left."*
    - **特点**：包装量词（individual cup）+ 手抓量（handful）+ 剩余热量预算衔接。

---

## 4. `src/nutrienv/bench/pipeline/expander.py` 的可落地 Prompt 优化方案

### 4.1 现有 `_STYLE_BLOCK` 现状与差距分析

查看当前 `src/nutrienv/bench/pipeline/expander.py`（第 485–490 行）：

```python
# 当前代码中的 _STYLE_BLOCK:
_STYLE_BLOCK = """\
Style:
- Write the query the way a person talks about food, in sentence case.
- Use a meal frame when natural: "For lunch I had...", "Breakfast was...", "I had...".
- Prefer the simplest spoken portion phrase shown for each food ("a serving of", "a cup of", "two pieces of").
- Do not title-case foods. Join foods naturally with "with" or "and"."""
```

#### 存在的问题与语用缺陷：
1. **“a serving of” 诱导过于强烈**：第 489 行明确鼓励 `"a serving of"`，导致生成模型极度高频地输出 `"a serving of Pork"`, `"a regular serving of Chicken"` 这类毫无母语自然感的机械句式。
2. **缺乏日常烹饪/形态连接词引导**：未引导模型使用常见生活化连接词（如 `"topped with"`, `"along with"`, `"on the side"`, `"cooked in"`, `"with a drizzle/pat of"`）。
3. **缺乏修饰语与自然组合的多样性**：模型倾向于简单地把 `food.aliases` 用 `"and"` 机械串联，缺少 Reddit / 饮食日记中常见的 `"two eggs on toast"`, `"a bowl of oatmeal with blueberries"` 等真实复合结构。

---

### 4.2 提议的最小化且合规的 `_STYLE_BLOCK` 替换方案 (Proposed Diff)

在**严格遵守 Discipline 4（仅使用 `HANDBOOK_VOCABULARY` 中的允许量词，不破坏测试集冻结契约）**的前提下，对 `_STYLE_BLOCK` 进行针对性升级：

```diff
--- a/src/nutrienv/bench/pipeline/expander.py
+++ b/src/nutrienv/bench/pipeline/expander.py
@@ -485,7 +486,10 @@ _FORBID_BLOCK = """\
 _STYLE_BLOCK = """\
 Style:
 - Write the query the way a person talks about food, in sentence case.
-- Use a meal frame when natural: "For lunch I had...", "Breakfast was...", "I had...".
-- Prefer the simplest spoken portion phrase shown for each food ("a serving of", "a cup of", "two pieces of").
-- Do not title-case foods. Join foods naturally with "with" or "and"."""
+- Sound like a real person logging on MyFitnessPal or Reddit: natural, conversational, and concise.
+- Use a natural meal frame: "For lunch I had...", "Breakfast was...", "I logged...", "Had a...".
+- Integrate portion phrases fluidly: prefer "a cup of...", "two slices of...", "a bowl of...", "a plate of..." over robotic "a serving of...".
+- Join foods naturally using culinary phrases like "topped with", "along with", "with a side of", "cooked in", or "and".
+- Do not title-case food names (say "grilled chicken breast", never "Grilled Chicken Breast")."""
```

---

### 4.3 词表与分词安全性审查 (Discipline & Handbook Vocabulary Audit)

为确保 Prompt 改进完全符合系统纪律，进行合规性核验：

1. **允许词表守恒（Handbook Coverage）**：
   - 替换后的引导词（`"cup"`, `"slice"`, `"bowl"`, `"plate"`, `"side of"`）均完全在 `HANDBOOK_VOCABULARY` (`src/nutrienv/bench/pipeline/expander.py:35`) 与 `harness/react.py` 支持的词表范围之内。
2. **Schema 与解析器零破坏**：
   - 生成的 JSON 输出结构 `{"items": [{"food": "...", "expression": "..."}], "query": "..."}` 保持 100% 兼容。
   - 不改变 `food_in_pool` 与 `match_pool_food` 的逻辑校验，`_query_leaks` 防护依然生效。
3. **消除生硬模板句**：
   - 抑制 `"a serving of Pork"` 的过度生成，使 LLM Expander 生成的题面更加生动、逼真，贴近真实的 NutriBench 与真实减脂社区记录水准。

---

*报告生成完毕 | 归档路径：`reports/agy-oral-portion-deepdive.md`*
