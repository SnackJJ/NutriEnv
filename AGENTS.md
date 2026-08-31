# AGENTS.md — NutriEnv 协作约定

本项目（/home/jzq/Projects/nutri-env）的 LLM 造题流水线方案与多 agent 分工，已固化在：

- `docs/llm-generated-exam-data.md` — 方案背景（四层架构、FNDDS/QNS 锚点、实验验证、隐患清单）
- `docs/agent-orchestration.md` — **多 agent 分工编排（本文件是它的摘要）**

## 分工速查

| Agent | 定位 | 限量 |
|---|---|---|
| grok | 实现主力（改代码、dry-run、probe、gate） | 周限量 |
| GPT (codex) | 审查主力（零漂移验证、代码复核） | 周限量 |
| AGY (gemini) | 搜索 + 网页汇报（差距审计、话术搜集） | 5h 限量 |
| claude | 深度裁决（收尾必用一次 + 关键节点按触发用） | 5h 限量 |

## 硬纪律

1. **克数锚点 = FNDDS 表值 / QNS；LLM 产出永远是候选，不是事实。**
2. catalog 重建必须先 dry-run 列"哪些食物克数会变"→ GPT 审查 → claude (Opus) 裁决，确认冻结 split 零漂移才落地。
3. judge 封 gate 前必须过灰区用例（sandwich 1.5× / lasagna 1.2× / omelet 2.0×），灰区结果由 claude (Opus) 终裁。
4. **Agent 语义接地考核（ADR 0021）**：`react.py` 手册严格作为工具协议与交互规范，严禁硬编码口语量词的小抄字典；考核 Agent 面对口语调用 `get_food` 自主进行常识推理与 FNDDS 数据库接地能力。
5. 判分规则不动：`Pass ⇔ end state == Oracle`；考试仍是冻结 split 文件。
6. **自然口语与解析（ADR 0019）**：禁止强制 LLM 逐字照抄 FNDDS "a cup" 字段；LLM 负责地道餐桌人话；`resolve_portion` 负责确定性查表；生僻/分数口语量词走 Multi-Agent Vote（FNDDS 参考表 × Multiplier）作为候选辅助人工审核把关。
7. **Oracle 构造与 Split 对齐（ADR 0020）**：流水线必须收敛至 `realize` / `realize_evaluate` / `compose_oracles` 领域接缝，严禁手搓未推导的 Oracle；Split 输出严格符合 `split.py` 标准结构；所有候选必须经 Human-in-the-loop 核准后由 freezer 编译为正式 Gold Split，并通过端到端 Round-Trip 回归测试（`Scorer.score() -> 100% Pass`）。
8. **流水线投票主力与安全闸门（ADR 0021）**：自然口语题目生成全面以 DeepSeek + Kimi + GLM 三模型投票为主力接地引擎，代码严格执行 $base\_grams \times multiplier$ 离散档位乘法，彻底删除模型自报克数后门；Tier-1 严格 Fail-Closed（未知前缀残词一律返回 None），全流程候选 100% 必须通过 `matches_portion_table` 物理白名单门禁。
9. **分层抽样与去标签化自然语（ADR 0022）**：题库抽样采用 75% 常见日常食物 + 25% 长尾特色食物的分层抽样；Prompt 强制去标签化（严禁照抄 `NS as to fat` / `prepared from mix` 等科研分类词），确保生成的 User Query 为人类餐桌真实大白话。
10. **双层评测协议与物理容差（ADR 0023）**：流水线实行“阶段一：Oracle Solver 全量 Round-Trip 100% Pass 证明题目健康可解”与“阶段二：受测 Agent 极简协议盲测考察真实常识推理”的双层架构；Oracle 保留 Gold 锚点，判分器支持 FNDDS 物理白名单离散容差；用户重复过敏原等真实人机交互打标为 `idempotent_update` 幂等测试。
11. **标准 100 题矩阵与安全层级化（ADR 0024）**：彻底废弃老 240 题模板，确立 100 题百分制基准（Update 5% + Log 15% + Eval 20% + Rec 20% + Comp 40%）；判分器实行过敏致命红线层级化（只要识别出 `allergy` 拦截即 Pass，漏报 `allergy` 必 Fail）；账本记录实行无序多重集判分（消除同餐记录先后顺序死板判定）；抽样层强制餐品常识语义门禁（严禁调味品/浓缩膏/纯饮料单独成餐）；Recommend/Composite 步数预算放宽至 30 步。

详细分工、执行顺序、pane 约定见 `docs/agent-orchestration.md`。
