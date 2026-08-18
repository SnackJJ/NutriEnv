# NutriEnv 多 Agent 分工编排（固化约定）

> 本文件是主 agent（DSH/Claude/任意协调者）指挥四个执行 agent 的固定分工方案。
> 项目方案背景见 `docs/llm-generated-exam-data.md`；本文件只管"谁干什么"。

## 角色与分工

| Agent | 工具/模型 | 定位 | 分到的活 |
|---|---|---|---|
| **grok** | grok (terminal) | 实现主力 | 编码、改代码、dry-run 脚本、probe 扩展、gate 封装 |
| **GPT** | codex (terminal) | 审查主力 | 代码审查、独立复核、零漂移验证、validate_draft 检查抽函数 |
| **AGY** | agy + gemini-3.7-flash-high | 搜索 + 汇报 | 差距审计数据整理、网页版汇报（review-sheet 风格）、真实话术源搜集 |
| **claude** | claude (Opus) | 深度裁决 | 收尾终审必用一次；关键节点按触发用（就绪检查/升级裁决/阻塞消解/集成检查点/硬纪律门）；关键部分 review 与 codex 并行交叉验证。不参与日常循环 |

## 限量约束（硬约束，分配时优先）

- **grok / GPT（codex）= 周限量** → 主力，承担 ~80% 工作量；重活、长任务全给它们。
- **claude / AGY（gemini）= 5 小时限量** → 省着用：
  - claude 只接一次性高价值任务（终审、裁决），不挂机、不轮询；
  - AGY 只接短平快任务（一次搜索/一份网页），独立并行，不等待。

## 执行顺序与依赖（标准流程）

```
第一波（并行）：grok → 任务①（FNDDS dry-run）
                AGY → 任务②（差距审计，用现有 catalog，不依赖①）
第二波：grok 产出 → GPT 审（零漂移验证）→ claude (Opus) 裁决 → 才允许落地重建 catalog
第三波：grok → 短语级 probe + judge gate → 灰区用例通过 → GPT 审 → claude 终审收尾
```

## 纪律（不可违反）

1. **catalog 重建必须过 dry-run + GPT 审查 + claude (Opus) 裁决**，dry-run 的"哪些食物克数会变"清单先给人看，确认冻结 split 零漂移才落地。
2. **judge 封 gate 前必须先过灰区用例**（sandwich 1.5× / lasagna 1.2× / omelet 2.0×，ground truth 已知），灰区结果由 claude (Opus) 终裁。
3. **claude 收尾终审必用一次，关键节点按触发用**（就绪检查、升级裁决、阻塞消解、集成检查点、硬纪律门；关键部分 review 与 codex 并行交叉验证），不参与日常迭代循环；每次 run 预算 2–8 次调用。
4. 克数锚点 = FNDDS 表值/QNS；**LLM 产出永远是"候选"，不是"事实"**；任何克数不允许由 LLM 直接定义。
5. agent 手册对称性：新表达（如 "a thick steak"）进题前必须同步写进 react.py 手册。

## Pane 约定（herdr）

- 项目 workspace：`w8`（nutri-env），主 agent（DSH web）固定占 `w8:pC`。
- 执行 agent 建议命名：`impl`（grok）、`reviewer`（codex）、`scout`（agy）、`adjudicator`（claude）。
- 新任务默认在 w8 开 sibling pane（`pane split --current --direction right --cwd "$PWD" --no-focus`），不新建 workspace。

## 启动一个任务时的标准动作（主 agent）

1. `pane split` 开 pane（保持 w8 + 当前 cwd）
2. `agent start <name> --kind <kind> --pane <id>`（grok/codex/agy/claude）
3. `agent prompt <name> "任务全文（自包含）" --wait`
4. `agent read <name>` 收结果；需要复核的活交给 reviewer 后再裁决
