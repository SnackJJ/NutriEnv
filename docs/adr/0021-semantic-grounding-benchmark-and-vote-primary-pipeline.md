# ADR 0021: 语义接地评测架构与多模型投票主力流水线 (Semantic Grounding Benchmark Architecture & Vote-Primary Resolution Pipeline)

- **状态**: Accepted (已通过)
- **日期**: 2026-08-29
- **相关 ADR**:
  - [ADR 0019: 自然口语泛化与两级解析架构](0019-natural-portion-expansion-and-semantic-vote-fallback.md)
  - [ADR 0020: Oracle 领域抽象与标准 Split 流水线收敛](0020-oracle-abstraction-and-split-pipeline-convergence.md)

---

## 1. 背景与核心问题 (Context)

在 ADR 0019 与 ADR 0020 的推进过程中，我们发现并彻底剖析了两个核心系统性问题：

### 1.1 手册（`react.py`）定位的异化
此前的部分设计试图在 Agent 手册（`react.py`）中巨细靡遗地罗列口语量词映射字典（如 `"遇到 pack 映射为 qns"`, `"遇到 slice 映射为 slice"` 等）。
**这种设计背离了 Benchmark 的评测初衷**：
- 如果手册把所有口语量词硬编码成查表字典，评测的就不是 LLM 的**端到端常识推理与领域数据库接地能力 (Semantic Grounding & Commonsense)**，而退化成了机械的“抄手册测试”；
- 真实的智能体评测，必须让 Agent 面对自然的餐桌人话，自主调用 `search_foods` / `get_food` 查询 USDA 数据库的 `portions` 字段，并凭借自身的常识判断该口语对应表中的哪一个物理量词（是 `piece`、`qns`、`cup` 还是克数）。

### 1.2 正则代码解析器的局限与 Fail-Open 隐患
在真实人类饮食记录中，死板的标准表达（如 `"100 g chicken breast"`）极其罕见，90% 以上是地道口语（如 `"a pack of cheese crackers"`, `"a handful of almonds"`, `"a bowl of leftover curry"`）。
代码硬编码正则（`portions.py`）在面对真实口语时不仅覆盖率低，而且存在**严重的 Fail-Open 静默猜错漏洞**：
- 例如在处理 `"a pack of cheese crackers"`（芝士饼干小包装，FNDDS 标准重 `18.0g`）时，由于字典中缺少 `pack`，规则解析器将 `pack of` 视为残词丢弃，直接触发了无量词裸名词兜底逻辑（*“默认算 1 piece”*），**静默将整包饼干算成了 1.0g（一颗碎渣饼干）**！

---

## 2. 核心架构决策 (Decisions)

### 决策 1：瘦身 Agent 手册，确立“自主语义接地”考核 Seam
1. **手册职责边界**：`src/nutrienv/harness/react.py` 严格作为**工具协议与环境交互指南**，严禁硬编码口语量词的小抄字典。
2. **考核定义**：明确将“从 `get_food` 的 `portions` 表中推导并匹配用户口语量词”作为被测 Agent 的核心智能考核点。手册指导 Agent 调用 `get_food` 观察真实物理数据，由 Agent 自主完成语义推理。

### 决策 2：修复 Tier-1 代码解析器，严格执行 Fail-Closed
1. **残词守卫 (Crumb Guard)**：在 `portions.py` 的 `_bare_food_noun_grams` 逻辑中加入严格检查。凡是句子中包含未解析的前缀修饰词或容器词（如 `pack of ...`），**一律严格返回 `None`**，坚决禁止退化为 1.0g 的裸名词盲目猜测。
2. **规则边界**：Tier-1 仅保留对绝对无歧义的物理单位（如明确的 `100g`, `2 cups`, `3 slices`）的高速确定性直通。

### 决策 3：造题流水线全面确立“三模型投票 + FNDDS 乘法”为主力接地引擎
1. **专家常识委员会**：在考题生成流水线中，纯口语表达统一接入 **DeepSeek-v4-flash + Kimi-k2.7 + GLM-5.2** 三模型投票集群。
2. **代码确定性算量**：
   - 彻底删除 `semantic_vote.py` 中接受 LLM 自报克数的 `elif "grams" in v` 后门；
   - 模型只输出 `(base_unit, multiplier)`，且 `base_unit` 必须精确存在于该食物的 FNDDS `portions` 表中；
   - `multiplier` 严格约束在离散档位：`{0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.5, 2.0, 3.0}`；
   - 最终克数必须由 Python 代码严格执行  = 	ext{round}(base\_grams 	imes multiplier)$ 并取整。

### 决策 4：全流程物理白名单门禁 (Portion Table Invariant)
所有生成的候选 Oracle 克数，必须 100% 通过 `matches_portion_table(food_id, grams, catalog)` 物理白名单校验，确保任何由口语推导出的标答均严格落在 FNDDS 物理基线允许的倍数范围内。

---

## 3. 系统影响与收益 (Consequences)

1. **Benchmark 效度质变**：NutriEnv 从“考小抄记忆”回归到真正的“考通用智能与营养数据库接地能力”，测评更真实、更具说服力。
2. **根除静默克数污染**：通过 Tier-1 的 Fail-Closed 修复和投票后门的彻底封死，杜绝类似 `1.0g` 饼干碎渣的荒谬标答污染 Gold Split。
3. **高效与地道的统一**：大模型负责输出丰富的餐桌人话，多模型共识负责推断地道常识，Python 代码与 FNDDS 表负责严格锚定真理，兼顾了口语自然度与数据科学严谨性。
