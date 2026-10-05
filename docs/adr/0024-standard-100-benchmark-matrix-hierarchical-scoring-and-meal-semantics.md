# ADR 0024: 标准 100 题评测矩阵、过敏层级化判分与餐品语义门禁

## 状态
**已采纳 (Accepted)** — 2026-08-30
- 联合审查：Claude (深度裁决 CONDITIONAL PASS 闭环) + Grok (实现主力) + GPT (代码复核)
- **Supersedes**: ADR 0009 (废除 240 题小集与 25 食物填空模板)
- **Related ADRs**: ADR 0002 (二元 Pass 铁律), ADR 0016 (终态兼容 Composite 配对), ADR 0020 (Oracle 抽象与 Freezer), ADR 0023 (双层协议与物理容差)

---

## 背景与问题陈述
在接入 USDA 5395+ 真实食物库与大模型常识投票流水线后，近期对 Qwen-3.8-Max, DeepSeek-V4, Kimi-k2.7-code 的实跑盲测与深度 Trace 复盘暴露出了三项深层次机制问题：

1. **过敏致命红线与软营养约束的判分死锁（Fatal Red-Line vs Soft-Target Dilemma）**：
   - 临床与现实中，餐单含致死过敏原时，营养师给出拒绝（`reject`）并指出过敏原因是 100% 充分且救命的。
   - 原判分器强行要求 Agent 必须像静态编译器一样把卡路里不足（`kcal_lo`）等软性偏离一次性报全，否则判 0 分，造成了严重的假阴性（False Negative）。
2. **生成端餐品角色缺失与量词脱节（Meal Semantic Feasibility & Quantifier Drift）**：
   - 抽样引擎将浓缩烘焙膏/酱料（`Sweet potato paste`，标准份量 QNS=20g/1汤匙）单独抽为一顿午餐，生成了 *"a small bowl of sweet potato paste"*（人类常识一小碗约为 100g~150g），导致底层规则粗暴将 "bowl" 映射到 20g 黄金锚点，大模型依据人类常识推断 100g 被全员误判。
3. **历史 240 题玩具模板过时与难度配比失衡（Obsolescence of Legacy 240-Slice Exam）**：
   - 240 题（ADR 0009）是基于 25 种食物的手写 dataclass 填空模板，充斥着机械性简单题，无法衡量现代顶级 Agent 的真实智力天花板。

---

## 核心架构决策

### 1. 标准 100 题金标矩阵（Standard 100-Task Benchmark Matrix）
彻底废弃 240 题老旧小集，正式确立 **100 题百分制权威基准（1 题 = 1%）**，将 80% 题量倾斜于高难单任务与复合对抗性任务：

| 题型家族 (Family) | 配额 (题数/占比) | 核心考察维度 | 预期平均通过率 |
|---|:---:|---|:---:|
| **Family 1: Update (画像维护)** | **5 题 (5%)** | 基础指令遵循、生理公式重算、幂等过敏确认 (ADR 0023) | 85% ~ 95% |
| **Family 2: Log (口语记录)** | **15 题 (15%)** | 纯感知与口语量词物理接地（分数、地道餐桌量词、去标签化） | 50% ~ 70% |
| **Family 3: Evaluate (安全审计)** | **20 题 (20%)** | 致命过敏一票否决拦截、宏量营养素失衡预警、达标餐单核准 | 45% ~ 65% |
| **Family 4: Recommend (多维规划)** | **20 题 (20%)** | 6 维不等式背包长程搜索求解（动态余量规划、特定多重禁忌） | 10% ~ 25% |
| **Family 5: Composite (复合主战场)** | **40 题 (40%)** | 全真长句多意图拆解与状态机流转 (`Log+Rec`, `Log+Eval`, `Log+Upd`, `Update+Rec`) | 20% ~ 40% |
| **全卷合计** | **100 题 (100%)** | **高难与复合题占比 80%，整体期望通过率约 45%** | — |

* **终态兼容的多意图复合梯队（Composite 3-Tier Multi-Intent Hierarchy）**：
  - **Tier-1 双意图基础复合（24 题）**：`Log + Rec` (12题), `Log + Upd` (4题), `Log + Eval` (4题), `Update + Rec` (4题)；
  - **Tier-2 三意图高阶复合（12 题）**：
    - `Update + Log + Rec` (4题)：更新过敏/运动 $\to$ 记录午餐 $\to$ 扣除后规划晚餐；
    - `Log + Update + Eval` (4题)：记录午餐 $\to$ 更新体重/阶段 $\to$ 基于新窗口评估下午茶；
    - `Update + Log + Eval` (4题)：更新运动水平 $\to$ 记录午餐 $\to$ 评估下午加餐；
  - **Tier-3 四意图终极挑战（4 题，Boss 题）**：
    - `Update + Update + Log + Rec` (4题)：更新过敏原 + 更新运动水平 $\to$ 记录午餐 $\to$ 规划零过敏合规晚餐；
  - 严禁 `Eval (reject) + Rec (plan)` 单独冲突，所有多意图组合均严格通过 `compose_oracles` 状态机接缝推导。
* **继承与超量造题策略（Inheritance & Over-Generation Protocol）**：
  - **v2.1 继承保留**：经过审计剔除 6 道缺陷题后，保留 **34 题**（Update 5, Log 7, Eval 7, Rec 8, Comp 7）；
  - **增量超量候选池**：按 1.5×~2.0× 超量生成 **~115 题候选**（Log 16, Eval 25, Rec 20, Comp 54），经三模型投票共识与沙箱可达性门禁筛选出最完美的 **66 题**；
  - **冻结金标与 Mini Split**：合计 100 题冷冻为 `data/splits/v2.2-gold.json`；等比抽样 20 题生成 `data/splits/v2.2-mini.json`。
* **Situation 底线记账**：Eval 20 题中 $\ge 8$ 题为 Reject（含 $\ge 4$ 个过敏刀、$\ge 2$ 纯宏量违规）；Recommend 20 题中 $\ge 6$ 题为高难约束题（不可能窗口或过敏陷阱）。

---

### 2. 致命过敏层级化判分机制（Hierarchical Safety Scoring）
重构 `Scorer._score_verdict` 对膳食评估（Evaluate）违规原因的判定逻辑，钉死不变量：

```python
# Scorer._score_verdict reject 分支精确不变量
gold_reasons = set(oracle.last_reasons)
got_reasons = set(state.last_reasons)

if "allergy" in gold_reasons:
    # 致命红线分支：若金标含过敏，Agent 必须且只要报告了 allergy 拦截即 Pass
    if "allergy" not in got_reasons:
        return "wrong_goal"  # 漏报过敏，Fatal Fail (0分)
    return None  # 成功命中 allergy 拦截，Pass（容许附带宏量超标理由）
else:
    # 纯宏量违规分支：保持严格集合精确匹配
    if got_reasons != gold_reasons:
        return "wrong_goal"
    return None
```
- `reject` 依然严格断言 `state.last_verdict == "reject"` 且 `state.last_plan == []`；
- `accept` 路径依然严格要求合规餐单且空 `reasons`，若误报过敏或提交含敏餐直接判 Fail。

---

### 3. 餐品常识语义门禁（Meal Semantic Feasibility Gate）
在出题流水线的采样层引入**非餐角色黑名单 + 量词物理兼容双层门禁**：
* **非餐黑名单**：单品餐（Single-item meal）若食物角色属于纯佐料/酱汁类（`condiment`, `paste`, `sauce`, `dressing`, `syrup`, `oil`, `seasoning`, `extract`, `powder-mix`），直接拒绝生成单品餐；
* **量词物理兼容门禁**：若食物属性为 paste/sauce，口语量词仅允许 `tbsp/tsp/packet`，严禁生成 `a bowl of paste` 等物理冲突表述。

---

### 4. 步数预算解耦与效率记录（Decoupled Step Budget & Efficiency Metric）
针对不同任务的计算与搜索复杂度，解耦最大步数限制（`max_steps`）：
* **Update 题型**：上限 **6 步**；
* **Log / Evaluate 题型**：上限 **12 步**；
* 在 Leaderboard 记录 `steps-to-solve` 作为未判分的效率梯队指标。

---

### 5. 账本记录无序多重集判分（Order-Independent Ledger Scoring）
* **消除顺序死板判定**：在现实生活中，同一餐吃下的多种食物无论以何种顺序记录（如先记牛肉后记冰淇淋，或先记冰淇淋后记牛肉），其摄入总量与生理状态完全等价。
* **判分实现**：`Scorer` 比对账本末尾切片时采用 `Counter(end_state.ledger[-k:]) == Counter(oracle.ledger_tail)` 进行无序多重集比对，彻底根除因为从左往右或从右往左解析造成的假阴性。

---

### 6. 量词解析双层边界（Two-Tier Portion Resolution Boundary）
* **Tier-1 (确定性快速短路)**：严格局限于 100% 显式、无歧义的精确量词（`g`, `oz`, `1 cup`, `2 slices` 等精确自带行）；
* **Tier-2 (LLM Triad 常识投票主力引擎)**：所有日常餐桌容器（`a bowl`, `a plate`, `a mug`）与口语量词（`three-egg`, `a handful`, `a serving`, 分数量词），全面交由 DeepSeek + Kimi + GLM 三模型投票。投票引擎基于人类餐桌生活常识，从 FNDDS 的合法物理行中选出最合理的一档（$base\_grams \times multiplier$），彻底消灭死板 Python 规则 Fallback 带来的反人类锚点。
