# ADR 0022: 食物分层抽样与去标签化自然餐桌语转译 (Stratified Food Sampling & De-Bureaucratized Colloquial Translation)

- **状态**: Accepted (已通过)
- **日期**: 2026-08-29
- **相关 ADR**:
  - [ADR 0019: 自然口语泛化与两级解析架构](0019-natural-portion-expansion-and-semantic-vote-fallback.md)
  - [ADR 0020: Oracle 领域抽象与标准 Split 流水线收敛](0020-oracle-abstraction-and-split-pipeline-convergence.md)
  - [ADR 0021: 语义接地评测架构与多模型投票主力流水线](0021-semantic-grounding-benchmark-and-vote-primary-pipeline.md)

---

## 1. 背景与核心问题 (Context)

在构建 NutriEnv 自然口语评测题库的过程中，我们发现了两个直接影响题库真实度与生活感的关键问题：

### 1.1 均匀随机抽样导致“小众科研食物泛滥”
USDA FNDDS 数据库包含 5,431 种食物，其中含有大量 NHANES 科研调查特有的生僻冷门条目（如婴儿配方粉、蒸馏配方水、地方小众风味油渣、未明确脂肪含量的特殊配方等）。
此前代码采用无差别的均匀随机抽样，导致题库中频繁出现不符合正常成年人日常饮食习惯的冷僻食材，脱离了真实餐桌场景。

### 1.2 LLM 生成时的“行政标签照抄病 (Bureaucratic Copy-Paste)”
此前生成 Prompt 直接将 FNDDS 数据库的科研分类全名（如 `"Green plantain with cracklings, Puerto Rican style"`, `"Coffee, decaffeinated, pre-sweetened with sugar"`）输入给大模型。
大模型为了确保匹配，倾向于机械照抄长串分类全名，生成了如 *"a cup of brewed decaffeinated pre-sweetened sugar coffee"* 这种充满行政科研标签味、真人绝不会说的假人话。

---

## 2. 核心架构决策 (Decisions)

### 决策 1：75:25 食物分层抽样机制 (Stratified Sampling)
在 `src/nutrienv/bench/pipeline/sampler.py` 中建立主流常见日常食物索引层：
1. **主流常见食物池 (Common/Staple Tier, 75% 权重)**：
   - 覆盖主食烘焙（米饭、意面、面包、土豆、燕麦、卷饼等）；
   - 主流蛋白质（鸡胸/鸡腿、牛排、三文鱼、鸡蛋、大虾、豆腐、酸奶等）；
   - 常见果蔬（西兰花、番茄、苹果、菠菜、胡萝卜、香蕉、牛油果等）；
   - 日常饮品与餐盘（牛奶、咖啡、绿茶、披萨、汉堡、沙拉、三明治、卷饼等）；
   - 过滤掉婴儿食品、医用特配等非成人饮食干扰。
2. **长尾探索食物池 (Long-tail Tier, 25% 权重)**：
   - 保留全量 FNDDS 数据库的长尾食材，用于评测 Agent 对特色菜品与生僻料理的泛化理解能力。

### 决策 2：Prompt 彻底去标签化与地道餐桌语转译 (De-Bureaucratization)
在考题生成 Prompt 中建立严格的自然口语转译规范：
1. **🚫 负向约束**：严禁在生成的 User Query 中出现 `NS as to...`（未指明脂肪）、`prepared from mix`（预拌粉制备）、`pre-sweetened with sugar` 等科研分类字眼；
2. **🗣️ 正向转译**：
   - `Coffee, decaffeinated, pre-sweetened with sugar` $ightarrow$ *"a cup of sweet decaf coffee"*；
   - `Turkey and ham sandwich on white, with cheese` $ightarrow$ *"a turkey ham and cheese sub"*；
   - `Chicken tenders or strips, breaded, from frozen` $ightarrow$ *"crispy chicken tenders"*。

---

## 3. 收益与影响 (Consequences)

1. **题库生活感与地道度质变**：题目全面贴近人类在 MyFitnessPal、Reddit、日常生活中的真实表达。
2. **兼顾核心日常与长尾泛化**：75% 主流食材确保评测基线稳固，25% 长尾食材确保评测具备鲁棒性与广度。
3. **保持精准锚定**：虽然表层 Prompt 转译为大白话，但底层仍精确绑定该食物的 FDC ID 与 FNDDS 数据库物理 Portion，标答克数坚固零漂移。
