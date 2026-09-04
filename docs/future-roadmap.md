# NutriEnv 未来大版本演进路线图 (Future Roadmap for v2.0+)

本文档记录在 NutriEnv v1.0-gold 策展期深度研讨、具有极高学术与临床价值，但因依赖底层架构升级而规划至未来大版本（v2.0+）的重点题型与核心演进方向。

---

## 1. 药物-营养素相互作用红线审查 (Drug-Nutrient Interaction Gate)

### 背景与定位
现实临床中，患者的慢性病管理绝不仅是卡路里或三大营养素的简单加减。药物与食物之间存在严重的生化相互作用（如维生素 K 与抗凝药华法林、酪胺与单胺氧化酶抑制剂 MAOI、西柚与降压药/他汀类）。

### 架构演进需求
1. **药典与食物生化相互作用库**：
   - 当前系统的食物底座为 USDA FNDDS 数据库，包含宏量与微量营养素，但缺乏药典交互关系表；
   - 需要在 `data/` 下挂载临床认可的 Drug-Nutrient Interaction 知识库（如 FDA 药典与临床营养指南标准映射表）。
2. **Profile 字段语义激活**：
   - 当前 `Profile.medications` 字段虽在数据流中传递，但未参与判分；
   - v2.0 将在 `Scorer` 中新增药食相互作用红线判定分支，实现临床安全一票否决。

---

## 2. 字典序多目标最优化推荐 (Lexicographic Multi-Objective Optimization)

### 背景与定位
当前 NutriEnv 的推荐任务（Recommend）本质上是**约束满足问题（SAT）**——只要餐盘落在营养素窗口内即可。而在现实健身、控糖与慢性肾病饮食中，用户往往追求**最优解（OPT）**（如“在 500 kcal 内让蛋白质最大化”）。

### 架构演进需求
1. **离散背包最优解求解器（Offline MILP Solver）**：
   - 食物组合存在大量离散等价解（Tie-breaking，如为了多 1g 蛋白质导致碳水微调）；
   - 为避免判分器引入假阴性，需要在离线环境使用整数线性规划（MILP）在有限食物子集与物理白名单份量上离线穷举证明全局唯一最优值或严格 Pareto 等价集合。
2. **Scorer 端目标函数支持**：
   - 在 `Oracle` 中引入 `objective_key` 与单边容差判定（如目标函数的 95%~100% 逼近度判定）。

---

## 3. 纵向多日跨天预算与延迟后果规划 (Longitudinal Deferred-Consequence Budgeting)

### 背景与定位
真实世界中，患者或节食者经常需要为已知的未来事件提前做热量或微量元素储备（如“周日婚宴预计吃 3000 kcal，周三至周六提前攒出热量缺口，但每天不低于基础代谢”）。这是长程规划智能体（Long-Horizon Planning Agent）最纯粹的能力体现。

### 架构演进需求
1. **WorldState 与 Ledger 多日时间轴重构**：
   - 当前系统核心数据结构 `LedgerRow.eaten_at` 严格基于单日餐次（`today-breakfast`, `today-lunch`, `today-dinner`）；
   - v2.0 将把时间线升级为多日日历模型（`Day_T-3`, `Day_T-2`, ..., `Day_T`），支持跨天账本记录与动态剩余预算计算。
2. **多阶段动态规划判分器**：
   - 检验 Agent 在 4 天 × 6 维营养素联立方程下的跨日资源分配能力。
