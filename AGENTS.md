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
4. agent 手册对称性：新表达进题前必须同步写进 react.py 手册。
5. 判分规则不动：`Pass ⇔ end state == Oracle`；考试仍是冻结 split 文件。
6. **自然口语与解析（ADR 0019）**：禁止强制 LLM 逐字照抄 FNDDS "a cup" 字段；LLM 负责地道餐桌人话；`resolve_portion` 负责确定性查表；生僻/分数口语量词走 Multi-Agent Vote（FNDDS 参考表 × Multiplier）作为候选辅助人工审核把关。

详细分工、执行顺序、pane 约定见 `docs/agent-orchestration.md`。
