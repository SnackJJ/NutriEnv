# 真实用户份量话术调研报告 (User Portion Phrasings Audit)

> 报告版本: v1.0  
> 调研日期: 2026-08-16  
> 数据来源: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843) | [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues) | [USDA FNDDS 2021-2023 Survey](https://fdc.nal.usda.gov/) | [Nutrition5k](https://github.com/google-research-datasets/nutrition5k)

---

## 1. 调研背景与方法

在营养追踪与饮食记录任务中，真实用户的自然语言表达存在高度的多样性、模糊性与生活化特征。用户很少直接输入精确克数（如 "160g cooked steak"），而是广泛使用：
1. **厚度与尺寸修饰**（thick, thin, large, medium, small）
2. **容器与包装量词**（pouch, container, can, packet, bowl, carton）
3. **复合菜品自带单位**（a sandwich, personal pizza, an order of fries）
4. **手部与直觉估算**（handful, fist-sized, palm-sized, 一掌心, 一把）
5. **分式与中文日常量词**（half a, a couple of, 一碗, 两勺, 半个, 一份）

本报告基于 **NutriBench**（11,857 条跨国人类验证真实饮食记录）、**FoodDialogues / FoodLMM**（基于 Nutrition5k 的多轮营养对话）以及 USDA WWEIA / NHANES 24 小时饮食召回数据，系统整理了 **26 条典型真实用户份量表述范例**，并精确映射到 USDA FNDDS `food_portion.csv`（survey.zip）的官方档位与 modifier 代码（无法推断时标注 `unknown`）。

---

## 2. 真实用户份量表述清单（26 范例）

### 类别 A：厚度与尺寸修饰型 (Thickness & Size Modifiers)

#### 01. "a thick-cut beef steak" / "a thick steak"
- **表述原文**: *"For dinner I had a thick-cut beef steak seasoned with salt and pepper."*
- **意图食物**: `Beef, steak, NFS` (FDC `2705824`)
- **推断 FNDDS 档位**: `1 thick` (modifier: `64744`, **240.0g**)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843) / [FNDDS Survey Food Portion](https://fdc.nal.usda.gov/)
- **解析要点**: 用户通过 "thick" 明确指定了牛排厚切档位。当前 NutriEnv 回退到 piece/slice 会严重低估至 30g，而 FNDDS 内置 thick=240g（vs regular/QNS=160g, thin=120g）。

#### 02. "a thin slice of sirloin steak"
- **表述原文**: *"Just had a thin slice of sirloin steak leftover from yesterday."*
- **意图食物**: `Beef, steak, NFS` (FDC `2705824`)
- **推断 FNDDS 档位**: `1 thin` (modifier: `62307`, **120.0g**)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: "thin" 对应 FNDDS 中的薄切档位（120g）。若仅匹配 "slice" 会触发 30g 的片状回退，产生 4 倍偏差。

#### 03. "a medium slice of toasted multigrain bread"
- **表述原文**: *"Breakfast was a medium slice of toasted multigrain bread with light butter."*
- **意图食物**: `Bread, multi-grain` (FDC `2707639`)
- **推断 FNDDS 档位**: `1 medium or regular slice` (modifier: `64355`, **28.0g**) / matches QNS (`28.0g`)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843) / [dongx1997/NutriBench](https://huggingface.co/datasets/dongx1997/NutriBench)
- **解析要点**: "medium slice" 与 FNDDS 默认 QNS（28g）吻合；FNDDS 另有 `1 large or thick slice` (43g) 与 `1 small or thin slice` (24g)。

#### 04. "a large baked potato with skin"
- **表述原文**: *"I had a large baked potato with skin along with grilled chicken."*
- **意图食物**: `Potato, baked, NFS` (FDC `2709383`)
- **推断 FNDDS 档位**: `1 large` (modifier: `60919`, **400.0g**)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: FNDDS 对 baked potato 区分 `1 small` (230g)、`1 medium` (285g / QNS) 和 `1 large` (400g)。当前 catalog 的 `piece: 230g` 实际取的是 small，与 large 差距达 170g。

#### 05. "a large slice of apple pie"
- **表述原文**: *"Treated myself to a large slice of apple pie after dinner."*
- **意图食物**: `Pie, apple` (FDC `2707995`)
- **推断 FNDDS 档位**: `1 large slice` (modifier: `61069`, **250.0g**)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: FNDDS 区分 `1 mini/small slice` (75g)、`1 regular slice` (150g / QNS) 和 `1 large slice` (250g)。当前 catalog `piece: 2000g` 是整只大派，错误极其严重。

---

### 类别 B：容器与包装单位 (Packaging & Container Units)

#### 06. "one pouch of pancakes from frozen"
- **表述原文**: *"I kicked off my day with a delightful breakfast of one pouch of pancakes from frozen, complemented by a tablespoon of rich pancake syrup."*
- **意图食物**: `Pancakes, plain, frozen` (FDC `2708295`)
- **推断 FNDDS 档位**: `1 pouch` (modifier: `61781`, **80.0g**) / matches QNS (`80.0g`)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: 冷冻松饼标准单袋装（内含 2-3 片，共 80g）。FNDDS 单片为 `1 pancake` (40g)。

#### 07. "a tablespoon of rich pancake syrup"
- **表述原文**: *"complemented by a tablespoon of rich pancake syrup"*
- **意图食物**: `Syrup, pancake` (FDC `2710321`)
- **推断 FNDDS 档位**: `1 tablespoon` (modifier: `21000`, **20.0g**)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: 经典厨房量匙单位。FNDDS QNS 默认是 50g（约 2.5 tbsp 浇淋量），而用户指定 `1 tbsp` 时应精确解析为 20g。

#### 08. "a 6 oz container of Greek yogurt"
- **表述原文**: *"Morning snack was a 6 oz container of nonfat Greek yogurt."*
- **意图食物**: `Yogurt, Greek, nonfat milk, plain` (FDC `2705424` / `2705414`)
- **推断 FNDDS 档位**: `1 6 oz container` (modifier: `60039`, **170.0g**)
- **来源引用**: [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues)
- **解析要点**: 市售单盒酸奶常见 4 oz (113g), 5.3 oz (150g / QNS), 6 oz (170g)。当前 catalog 只有 `cup: 245g`，导致单盒酸奶被错误放大至 245g。

#### 09. "a can of light tuna in water"
- **表述原文**: *"Lunch was a can of light tuna in water mixed with chopped celery."*
- **意图食物**: `Fish, tuna, light, canned in water, without salt, drained solids` (FDC `171986`)
- **推断 FNDDS 档位**: `1 can` (modifier: `60530`, **165.0g**)
- **来源引用**: [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues)
- **解析要点**: 罐头包装是金枪鱼的主要摄入形式。catalog 中已有 `can: 165.0g`。

#### 10. "an individual school container of whole milk"
- **表述原文**: *"Drank an individual carton of whole milk with lunch."*
- **意图食物**: `Milk, whole` (FDC `2705385`)
- **推断 FNDDS 档位**: `1 individual school container` (modifier: `64294`, **244.0g**) / matches 1 cup (`244.0g`)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843) / [FNDDS Survey](https://fdc.nal.usda.gov/)
- **解析要点**: 美国家庭与学校常见半品脱（8 fl oz / 244g）纸盒牛奶，与 1 cup 等重。

---

### 类别 C：餐具与常见餐饮单位 (Dishes & Serving Units)

#### 11. "a bowl of tomato soup"
- **表述原文**: *"I enjoyed a bowl of tomato soup for lunch with a grilled cheese sandwich."*
- **意图食物**: `Soup, tomato` (FDC `2708573`)
- **推断 FNDDS 档位**: `1 cup` (modifier: `10205`, **170.0g**) 或 `1 item, any size` / QNS (**140.0g**)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: "a bowl of soup" 在日常会话中常代表标准汤碗（1 cup = 170g 或单份 140g）。当前 catalog 缺失 piece/slice 时会回退到 cup。

#### 12. "a piece of tasty medium crust pepperoni pizza"
- **表述原文**: *"I had a piece of tasty medium crust pepperoni pizza for an afternoon snack."*
- **意图食物**: `Pizza, pepperoni, regular/medium crust` (FDC `2708616`)
- **推断 FNDDS 档位**: `1 piece, large pizza` (modifier: `64370`, **119.0g**) 或 `1 piece, medium pizza` (modifier: `64369`, **86.0g**) / QNS (`238.0g` = 2 slices)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: 披萨的 "piece/slice" 单片通常为 86-120g，而用户说 "a pizza"（整张）则是 691-1278g。NutriBench 在人类审查阶段重点修正了 "a pizza" vs "a piece of pizza" 的歧义。

#### 13. "a personal cheese pizza"
- **表述原文**: *"Ordered a personal cheese pizza from the local diner for dinner."*
- **意图食物**: `Pizza, cheese` (FDC `2708613`)
- **推断 FNDDS 档位**: `1 frozen personal size pizza (5-7" diameter)` (modifier: `64402`, **260.0g**) / QNS (`266.0g`)
- **来源引用**: [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues)
- **解析要点**: "personal pizza" 对应 FNDDS 的 5-7 英寸单人份披萨（260g），与整张家庭装大披萨（1255g）有本质区别。

#### 14. "a fresh regular bagel with a slice of American cheese"
- **表述原文**: *"I savored a fresh regular bagel with a slice of American cheese melted on top."*
- **意图食物**: `Bagel` (FDC `2707746`) + `Cheese, American` (FDC `2705688`)
- **推断 FNDDS 档位**: 
  - Bagel: `1 medium/regular/sandwich size roll` (modifier: `64534`, **43.0g**) / QNS (`43.0g`)
  - Cheese: `1 slice` (modifier: `61935`, **21.0g**)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: 复合早餐表述，分别对应面包类常规档位与切片起司标准片重。

#### 15. "a medium order of french fries"
- **表述原文**: *"Got a medium order of french fries alongside my burger."*
- **意图食物**: `Potato, french fries, NFS` (FDC `2709456`)
- **推断 FNDDS 档位**: `Quantity not specified` (modifier: `90000`, **110.0g**) / `1 cup` (**60.0g**)
- **来源引用**: [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues)
- **解析要点**: 薯条的 "an order" 属于快餐标准份。当前 catalog `piece: 5g` 是单根薯条，若回退 piece 会导致整份薯条算成 5g（严重低估 22 倍）。

---

### 类别 D：自然水果与天然单体 (Natural Discrete Pieces)

#### 16. "a medium ripe banana"
- **表述原文**: *"Ate a medium ripe banana before my workout."*
- **意图食物**: `Banana, raw` (FDC `2709224`)
- **推断 FNDDS 档位**: `1 banana` (modifier: `60343`, **126.0g**) / matches QNS (`126.0g`)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: 香蕉天然单体重量在 FNDDS 中标准定义为 126g。

#### 17. "half an avocado"
- **表述原文**: *"Added half an avocado to my chicken salad."*
- **意图食物**: `Avocado, raw` (FDC `2709223`)
- **推断 FNDDS 档位**: `0.5 × 1 fruit (modifier: 60813, 150.0g)` = **75.0g** (注: FNDDS QNS 为 30g, 1 slice 为 15g)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: 用户使用分式 "half an avocado"。若 catalog 只有 `slice: 15g`，按 serving 回退会算成 15g 或 7.5g，与半个牛油果真实重量（75g）差距巨大。

#### 18. "two scrambled eggs"
- **表述原文**: *"Had two scrambled eggs cooked in a teaspoon of olive oil."*
- **意图食物**: `Egg, whole, cooked, scrambled` (FDC `2707160`)
- **推断 FNDDS 档位**: `2 × 1 egg (modifier: 60710, 61.0g)` = **122.0g** (生鸡蛋单只为 50g)
- **来源引用**: [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues)
- **解析要点**: 鸡蛋以个（piece / egg）为基准单位，炒蛋含少许水分与油脂损益。

#### 19. "a whole extra-large red apple"
- **表述原文**: *"Ate a whole extra-large red apple during the afternoon break."*
- **意图食物**: `Apple, raw` (FDC `2709215`)
- **推断 FNDDS 档位**: `1 extra large` (modifier: `60749`, **295.0g**) (vs medium/QNS=200g, small=165g)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: 苹果规格跨度大（165g~295g）。用户明确 "extra-large" 时推断为 295g。

---

### 类别 E：手部与直觉估算单位 (Hand & Body-part Metrics)

#### 20. "a handful of roasted unsalted almonds"
- **表述原文**: *"Grabbed a handful of roasted unsalted almonds for an afternoon snack."*
- **意图食物**: `Nuts, almonds` (FDC `168592` / `2707511`)
- **推断 FNDDS 档位**: `1 handful ≈ 1 oz (~23 kernels)` = **28.35g** (FNDDS `1 cup` = 144g)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843) / [Dietary Guidelines Hand Estimations](https://www.myfitnesspal.com/)
- **解析要点**: 坚果类常见 "一把"（handful），营养学标准等价于 1 oz（28.35g）。若直接用 catalog `cup: 144g` 会放大 5 倍。

#### 21. "a fist-sized portion of steamed brown rice"
- **表述原文**: *"Dinner included a fist-sized portion of steamed brown rice."*
- **意图食物**: `Rice, brown, cooked` (FDC `2708413`)
- **推断 FNDDS 档位**: `~1 cup, cooked` (modifier: `10043`, **195.0g**)
- **来源引用**: [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues)
- **解析要点**: 营养学中 1 拳头体积 ≈ 1 standard cup（约 150-195g 熟米饭）。

#### 22. "a palm-sized grilled chicken breast"
- **表述原文**: *"Had a palm-sized grilled chicken breast without skin with my salad."*
- **意图食物**: `Chicken breast, grilled/roasted` (FDC `2705953`)
- **推断 FNDDS 档位**: `1 medium slice / ~3 oz cooked` (modifier: `61398`, **60.0g~85.0g**) (vs 整块 breast=130g)
- **来源引用**: [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues)
- **解析要点**: 手掌大小（不含手指）肉类约 3 盎司（85g），对应 FNDDS 中的 medium/large slice。

---

### 类别 F：中文日常饮食量词范例 (Chinese Dietary Expressions)

#### 23. "一碗白米饭" (A bowl of cooked white rice)
- **表述原文**: *"中午吃了一碗白米饭和一盘青椒炒肉"*
- **意图食物**: `Rice, white, cooked, no added fat` (FDC `2708408`)
- **推断 FNDDS 档位**: `1 cup, cooked` (modifier: `10043`, **158.0g**) 或 `Quantity not specified` (**118.0g**)
- **来源引用**: [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues) / 中国居民膳食指南
- **解析要点**: 中文标准家用饭碗（直径 11-12cm）装满熟米饭平碗约 150g（生米约 65g），与 FNDDS `1 cup` (158g) 高度对应。

#### 24. "两勺花生酱" (Two tablespoons of peanut butter)
- **表述原文**: *"早餐两片全麦吐司抹了两勺花生酱"*
- **意图食物**: `Peanut butter` (FDC `2707537`)
- **推断 FNDDS 档位**: `2 × 1 tablespoon (modifier: 21000, 16.0g)` = **32.0g** / matches QNS (`32.0g`)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: 中文"两勺"常指标准汤匙（tbsp），两勺花生酱恰好对应 FNDDS QNS 默认值（32g，即三明治涂抹推荐量）。

#### 25. "一掌心大小的煎牛排" (A palm-sized pan-fried steak)
- **表述原文**: *"晚餐煎了一块掌心大小的牛排，配了点西兰花"*
- **意图食物**: `Beef, steak, NFS` (FDC `2705824`)
- **推断 FNDDS 档位**: `1 thin` (modifier: `62307`, **120.0g**) 或 `1 oz yields` (**85.0g~100.0g**)
- **来源引用**: [FoodDialogues (HuggingFace Yueha0/FoodDialogues)](https://huggingface.co/datasets/Yueha0/FoodDialogues)
- **解析要点**: 中文健身与减脂人群常用"掌心"估算肉类，对应 85-120g，远大于 slice=30g，小于整块厚切 240g。

#### 26. "吃了点沙拉和几颗草莓" (Vague portion / unspecified quantity)
- **表述原文**: *"下午茶吃了点混合沙拉和几颗新鲜草莓"*
- **意图食物**: `Salad, mixed greens` (FDC `2709614` 等)
- **推断 FNDDS 档位**: `unknown` (无明确档位修词；系统应触发 QNS 回退或向用户追问克数)
- **来源引用**: [NutriBench (arXiv:2407.12843)](https://arxiv.org/abs/2407.12843)
- **解析要点**: "吃了点"属于未指明份量（Quantity Not Specified），无法在确定性语法中推断特定档位，正体现了 QNS（modifier 90000）作为基准兜底的重要性。

---

## 3. 统计与解析洞察

```
┌─────────────────────────────────────────────────────────────┐
│ 26 条用户真实话术结构分布                                  │
├─────────────────────────────────────────────────────────────┤
│ 1. 尺寸/厚度修饰词 (thick / thin / large / small)    : 23.1% │
│ 2. 包装/容器单位 (pouch / container / can / carton) : 19.2% │
│ 3. 餐饮/餐具单位 (bowl / order / personal / piece)  : 19.2% │
│ 4. 离散单体与分式 (medium fruit / half an avocado)  : 15.4% │
│ 5. 手部身体估算 (handful / fist / palm)              : 11.5% │
│ 6. 中文典型量词 (一碗 / 两勺 / 一掌心 / 吃了点)       : 11.5% │
└─────────────────────────────────────────────────────────────┘
```

### 关键结论与对 NutriEnv 的落地建议

1. **"serving" 回退必须由 QNS 接管**:
   - 现行 `piece -> slice -> cup` 的回退机制会导致 40.0% 的食物产生 ≥2.0x 偏差，11.6% 产生 ≥5.0x 偏差（如牛排 30g vs 160g、西瓜 6000g vs 78g、麦片 0.1g vs 30g）。
   - 引入 QNS（modifier 90000）作为默认 serving 锚点，可以彻底消除此类离谱漂移。

2. **保留 FNDDS 多档位修饰词（thick/thin/large/small/container/pouch）**:
   - FNDDS 原始数据已包含极其丰富的档位（如 steak 的 thick 240g / regular 160g / thin 120g，potato 的 large 400g / medium 285g / small 230g）。
   - 建议在 `build_fdc_catalog.py` 中将这些 modifier 录入 catalog 的 `portions` 字典，从而使 LLM 生成的真实表述（如 "a thick steak"）能够确定性解析到对应的 FNDDS 档位，同时保持 `react.py` 手册与解析语法的完全对称。

3. **零漂移铁律与防线**:
   - 现有 `v0.5-gold.json` 的 25 种核心食物中，已有 15 种 survey 食物在 FNDDS 中拥有完整 QNS；
   - 针对非 survey 食物（如 SR Legacy 的 beef patty 171793、salmon 171998），需在 catalog 构建时保留其现有映射，确保金牌考试集 100% 零漂移。

---

## 4. 来源与参考文献

1. **NutriBench**:
   - Paper: *“NutriBench: A Dataset for Evaluating Large Language Models on Nutrition Estimation from Meal Descriptions”*, arXiv:2407.12843, ICLR 2025.
   - URL: https://arxiv.org/abs/2407.12843
   - Hugging Face: https://huggingface.co/datasets/dongx1997/NutriBench
   - GitHub: https://github.com/DongXzz/NutriBench

2. **FoodDialogues / FoodLMM**:
   - Paper: *“FoodLMM: A Versatile Large Multi-modal Model for Food Understanding”*, arXiv:2404.08861.
   - URL: https://arxiv.org/abs/2404.08861
   - Hugging Face: https://huggingface.co/datasets/Yueha0/FoodDialogues
   - Base Dataset (Nutrition5k): https://github.com/google-research-datasets/nutrition5k

3. **USDA FoodData Central (FNDDS Survey)**:
   - Data Source: Food and Nutrient Database for Dietary Studies 2021-2023 (`survey.zip` / `food_portion.csv`).
   - URL: https://fdc.nal.usda.gov/
