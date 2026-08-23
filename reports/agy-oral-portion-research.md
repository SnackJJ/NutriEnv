# 英语口语饮食与份量表达（Oral Portion Size）调研报告

> **目标**：调研英语母语者在日常饮食记录、评估、建议与修正场景中如何自然口语化表达餐食与份量，梳理相关学术 Benchmark，构建符合真实语用习惯的自然表达语料库，为营养领域 Agent / LLM 的份量理解与多轮对话系统提供评测与基准参考。

---

## 重点一：营养领域口语份量（Portion Size）相关 Benchmark 调研

目前学术界在 **“LLM / Agent 理解自然语言餐食描述与估算营养”** 这一细分方向已有关键基准建立，其中最具代表性的是 **NutriBench** 及相关衍生评测集：

### 1. 核心 Benchmark：NutriBench
* **名称**：**NutriBench: A Dataset for Evaluating Large Language Models on Nutrition Estimation from Meal Descriptions**
* **论文与代码链接**：
  * arXiv 论文：[arXiv:2406.02702](https://arxiv.org/abs/2406.02702)
  * Hugging Face Dataset：[`dongx1997/NutriBench`](https://huggingface.co/datasets/dongx1997/NutriBench)
  * GitHub 仓库：[NutriBench on GitHub](https://github.com/dongx1997/NutriBench)
* **核心机制与份量设计**：
  * 包含 **11,000+** 条真实餐食描述（基于美国国家健康与营养调查 **NHANES / WWEIA** 以及 **FAO/WHO GIFT** 数据库构建并经人工核验）。
  * 专门设立了 **“Natural Serving Units（自然日常度量）”** 与 **“Metric Units（公制度量/克数）”** 的对比子集。
  * **结论**：当前前沿模型（GPT-4o, Claude 3.5 Sonnet 等）在公制克数输入时估算较为平稳，但在面对英语口语化日常份量单位（如 *cups, slices, tablespoons, medium pieces, fist-sized*）时，会产生严重的 **“Serving Unit Conversion Error（份量单位换算误差）”** 与 **“大份量系统性低估（Underestimation of large portions）”**。
* **NutriBench 样例表达**：
  * *"A breakfast of 2 large scrambled eggs cooked with a pat of butter, 2 slices of toasted whole wheat bread, and 1 medium navel orange."*
  * *"Lunch was 1 cup of cooked white rice with 4 oz of grilled chicken breast and half a cup of steamed broccoli with a drizzle of soy sauce."*
  * *"Snacked on a handful of roasted unsalted almonds and a small cup of low-fat vanilla yogurt."*

### 2. 其它相关视觉与多模态份量 Benchmark
* **FPB (Food Portion Benchmark)**: [Hugging Face: FPB](https://huggingface.co/datasets/fpb) / CVPR 经典基准，专注多目标食物检测与真实克重（Ground-truth portion weights）预测。
* **Nutrition5k**: [GitHub: Nutrition5k](https://github.com/google-research-datasets/Nutrition5k) / Google Research 发布的 5000+ 真实餐盘多视角图像与精确营养成分基准。
* **ASA24 (Automated Self-Administered 24-Hour Dietary Assessment Tool)**: 美国国家癌症研究所（NCI）的标准 24 小时饮食召回系统，其基于 **AMPM (Automated Multiple-Pass Method)** 的交互流是口语多轮澄清份量事实上的金标准。

---

## 重点二：自然英语一餐表达语料库（28条，按场景分类）

> **设计原则**：严格杜绝类似 `"a regular serving of Pork and a cup of Black beans"` 这种生硬、机器翻译式的模板组合；完全采用英语母语者在日常生活、快餐店/咖啡厅点单、家庭烹饪及健身/减脂社区（如 Reddit *r/loseit*, *r/MacroFactor*, MyFitnessPal）中的真实口语表达与量词短语。

### 场景一：Log（用户日常记录餐食 - 7条）

1. **经典美式快餐**：
   > *"A double bacon cheeseburger from Five Guys, a regular cajun fry, and a large Diet Coke with ice."*
   > *(量词/短语：double [patty], regular [fry size], large with ice)*

2. **自制健康早餐**：
   > *"Two sunny-side up eggs on toasted sourdough with half an avocado mashed on top, plus a tall oat flat white."*
   > *(量词/短语：two sunny-side up eggs, half an avocado, tall [Starbucks coffee size])*

3. **快捷墨西哥碗（Chipotle风格）**：
   > *"A grilled chicken burrito bowl with a double scoop of black beans, extra fajita veggies, fresh pico, and a hefty dollop of sour cream on the side."*
   > *(量词/短语：burrito bowl, double scoop, extra [topping], hefty dollop, on the side)*

4. **谷物燕麦碗**：
   > *"A bowl of steel-cut oatmeal cooked in whole milk, topped with a generous handful of blueberries and a drizzle of maple syrup."*
   > *(量词/短语：a bowl of, a generous handful of, a drizzle of)*

5. **熟食店三明治（Subway风格）**：
   > *"A footlong turkey sub on multigrain with pepper jack cheese, shredded lettuce, tomatoes, and a light squeeze of yellow mustard."*
   > *(量词/短语：footlong [12-inch sub], shredded, a light squeeze of)*

6. **家常高蛋白晚餐**：
   > *"A palm-sized grilled salmon fillet with half a plate of roasted asparagus and a fist-sized baked sweet potato with a knob of butter."*
   > *(量词/短语：palm-sized, half a plate of, fist-sized, a knob of butter)*

7. **午后零食/下午茶**：
   > *"Half a bag of salt and vinegar kettle chips and a fun-sized Snickers bar with a can of sparkling water."*
   > *(量词/短语：half a bag of, fun-sized [mini candy bar], a can of)*

---

### 场景二：Evaluate（评估摄入/询问营养赤字 - 7条）

8. **牛排大餐复盘**：
   > *"I just smashed a 12-oz ribeye steak with a loaded baked potato (sour cream, bacon bits, chives) and two glasses of Cabernet. How bad is the damage?"*
   > *(量词/短语：smashed [口语：干掉/吃了], 12-oz, loaded [加满料的], two glasses of)*

9. **冰淇淋甜品评估**：
   > *"Had two hefty scoops of vanilla Häagen-Dazs in a waffle cone with warm fudge drizzle—how many carbs are we looking at?"*
   > *(量词/短语：two hefty scoops, waffle cone, fudge drizzle)*

10. **连锁快餐热量校验**：
    > *"For lunch I got a 6-piece chicken nugget meal with a medium order of fries and two tubs of sweet & sour sauce. Does this fit in my 700 kcal budget?"*
    > *(量词/短语：6-piece meal, medium order of, two tubs of [酱料盒])*

11. **连锁咖啡高糖饮品评估**：
    > *"I drank a 24-oz iced caramel macchiato made with whole milk and extra whipped cream on top. Did that completely blow my morning deficit?"*
    > *(量词/短语：24-oz [Venti/Iced], extra whipped cream on top, blow my deficit)*

12. **东南亚风味大份汤面**：
    > *"Finished a hearty bowl of beef pho with extra rice noodles, beansprouts, and a couple of fried spring rolls on the side. What's the rough protein and sodium breakdown?"*
    > *(量词/短语：hearty bowl of [大碗分量足的], extra noodles, a couple of [2-3个])*

13. **街头墨西哥卷饼热量测算**：
    > *"I ate three street-style carne asada tacos on corn tortillas with a side of refried beans and a ramekin of guacamole. How are my macros looking?"*
    > *(量词/短语：three street-style tacos, a side of, a ramekin of [小酱料碟])*

14. **烘焙甜点摄入核算**：
    > *"A grande pumpkin spice latte and a thick slice of iced lemon loaf cake from Starbucks—how much added sugar did I just take in?"*
    > *(量词/短语：grande, thick slice of)*

---

### 场景三：Recommend（给出配餐建议/规划 - 7条）

15. **高蛋白减脂正餐替换建议**：
    > *"Swap the ribeye for a palm-sized grilled chicken breast, pair it with a heaping cup of steamed broccoli, and add a fistful of brown rice."*
    > *(量词/短语：palm-sized breast, a heaping cup of [高高堆起的一杯], a fistful of)*

16. **饱腹感早餐搭配方案**：
    > *"For a high-protein breakfast, aim for a 3-egg omelet loaded with a handful of baby spinach, diced bell peppers, and a sprinkle of feta, along with one slice of whole-wheat toast."*
    > *(量词/短语：3-egg omelet, a handful of, diced, a sprinkle of)*

17. **下午抗饿轻食加餐**：
    > *"Try snacking on an individual Greek yogurt cup (plain 2%) swirled with a tablespoon of chia seeds and a small fistful of raw almonds."*
    > *(量词/短语：individual cup, swirled with, a tablespoon of, a small fistful of)*

18. **哈佛健康餐盘视觉法则指导**：
    > *"Build your dinner plate with half non-starchy roasted veggies, a deck-of-cards-sized portion of pan-seared tofu, and half a cup of cooked quinoa."*
    > *(量词/短语：half plate of, a deck-of-cards-sized portion [扑克牌大小/约85g肉豆腐标准], half a cup of)*

19. **练后蛋白奶昔配比**：
    > *"Post-workout, blend one level scoop of whey isolate with a medium frozen banana, a cup of unsweetened almond milk, and a rounded tablespoon of peanut butter."*
    > *(量词/短语：one level scoop [平勺], medium banana, a rounded tablespoon [带弧度满勺])*

20. **外食意大利餐厅控卡技巧**：
    > *"If you're eating Italian tonight, order the grilled branzino with a double side of sauteed greens and limit the bread basket to a single piece with a light dip of olive oil."*
    > *(量词/短语：double side of, bread basket, a single piece, a light dip of)*

21. **简易午餐便当组装**：
    > *"Pack a two-finger-thick cut of frittata, a mason jar of mixed greens tossed in a splash of vinaigrette, and a small apple."*
    > *(量词/短语：two-finger-thick cut, a mason jar of, a splash of)*

---

### 场景四：Update（对话中修正/增删/细节变更 - 7条）

22. **更改主料份量与追加配菜**：
    > *"Actually, make that just one egg instead of two, and I forgot to mention I had two strips of crispy bacon on the side."*
    > *(量词/短语：make that just one egg, two strips of bacon on the side)*

23. **去配料与主食换配菜**：
    > *"Hold the cheese on that turkey burger, and swap the regular fries for a small side garden salad with dressing on the side."*
    > *(量词/短语：hold the [不要加某物], swap X for Y, small side salad, dressing on the side)*

24. **修改饮品奶基底与剩余比例**：
    > *"Change the milk in my latte from whole to oat milk, and I only ended up finishing about half the blueberry muffin."*
    > *(量词/短语：from whole to oat, only finished about half the)*

25. **更正主食类型与配料替换**：
    > *"Scratch the white rice in that bowl—I actually got brown rice, and they gave me a double scoop of black beans instead of pinto."*
    > *(量词/短语：scratch the [撤销/划掉], double scoop of)*

26. **扣除剩菜与追加多人共享小吃**：
    > *"Update my lunch: I left half the bun on the burger, but I ended up sharing a large basket of onion rings and had about 4 or 5 rings."*
    > *(量词/短语：left half the bun, a large basket of, about 4 or 5 rings)*

27. **修改酒水规格与赠送给朋友**：
    > *"Correct that to a 16-oz draft IPA rather than a 12-oz can, and remove the side of fries—I gave them all to my friend."*
    > *(量词/短语：16-oz draft, 12-oz can, side of fries)*

28. **更换沙拉酱汁与追加蛋白质顶料**：
    > *"On that garden salad, switch the ranch to a light splash of balsamic vinaigrette, and add a palm-sized grilled chicken cutlet on top."*
    > *(量词/短语：switch X to Y, a light splash of, a palm-sized cutlet on top)*

---

## 重点三：后续可深度深挖的 3 个信源方向

为了让后续 Agent / LLM 系统的 Prompt 构建、SFT 数据集构造和 Evaluator 对齐更贴近真实世界，建议在以下 3 个信源方向继续深挖：

### 1. USDA FNDDS / NHANES WWEIA 官方食物份量编码手册 (Food Portion Coding Manuals)
* **信源说明**：美国农业部（USDA）与疾控中心（CDC）在开展全美膳食调查时，积累了极具权威性的 **Food Portion and Weight Conversion Guide**（如 USDA Food and Nutrient Database for Dietary Studies, FNDDS）。
* **深挖价值**：
  * 该手册定义了数千种食物从口语描述（如 *“1 small fist of mashed potato”*, *“1 slice, thick (1/2 inch)”*, *“1 deck of cards size meat”*, *“1 drumstick with skin”*）到标准公制克数（Grams）的标准映射基准表。
  * 是构建**份量解析规则库（Deterministic Portion Resolver）**和真实度量 Ground-truth 的权威医学/营养流行病学源头。

### 2. NCI ASA24 / USDA AMPM 自动化多次通过法交互流 (Multi-Pass Dietary Recall Workflows)
* **信源说明**：美国国家癌症研究所（NCI）的 ASA24 系统及其底层的 **Automated Multiple-Pass Method (AMPM)**。
* **深挖价值**：
  * 提供了标准化的 5 步多轮追问逻辑（Quick List $\to$ Forgotten Foods Probe $\to$ Time & Occasion $\to$ Detail & Portion Review $\to$ Final Probe）。
  * 包含大量针对模糊表达的标准 Clarification Prompt（例如当用户说 *"I had a sandwich"* 时，系统如何自然追问 bread type, condiments, thickness, spread size）。可直接转化为 Agent 多轮对话策略的状态机设计。

### 3. 自然真实饮食社区语料库（Naturalistic Community Food Logs & Micro-blogging）
* **信源说明**：
  * Reddit 深度健康/减脂社区：`r/loseit`, `r/1200isplenty`, `r/1500isplenty`, `r/MacroFactor`, `r/CICO`；
  * MyFitnessPal / Cronometer 社区的非结构化随手记（Natural text meal diaries）。
* **深挖价值**：
  * 蕴含海量英语母语者在真实生活中的俚语（Slang）、简写（*“protein shake w/ almond milk”*, *“2 tbsp PB”*, *“half an avo”*, *“grabbed a bite of...”*）、品牌定制词（*Starbucks sizes, Chipotle hacks, Five Guys terminology*）以及自发修正模式。
  * 可通过清洗抽取，构建逼真的 SFT 多轮对话微调数据集与鲁棒性压力测试集（Robustness stress-testing suite）。

---

*报告生成时间：2026-08-23 | AGY Scout 自动调研与落盘完成*
