# 0013 — Composite Task / Oracle contract

ADR 0012 允许复合题，但把「形状、判分、配额数字」留给 v1.0 冻结前再裁决一次。
本文件是那次裁决的输入（issue 11）。实现按本文落地；主 agent 可改数字或否决
某条，但不得改判分铁律。

**Status**: proposed (implementation follows this text unless the main agent
overrides)

## Decision

一个复合 Task 仍只有一个 `Task.oracle`。`Oracle` 新增可选字段
`sub_oracles: tuple[Oracle, ...] | None = None`。

- `sub_oracles is None`（或缺省）：单 family 路径，与今天完全一致。
- `sub_oracles` 为长度 ≥ 2 的元组：该 Oracle 是容器；判分只看子 Oracle。
  父级 `ledger_tail` / `last_plan` / `plan_*` **不单独计分**。
- `Task.family` 仍是 **primary Family**（第一步的 family，v1 固定为 `log`）。
  分类账不变。复合不是第六个 family。
- Runner 继续 `scorer.score(env.state(), task.oracle)`，不改 harness。

### 为什么是 `Oracle.sub_oracles`，不是 `Task.oracles`

| 方案 | 取 | 舍 |
|---|---|---|
| **A. `Oracle.sub_oracles`**（采纳） | runner / `Task` 字段 / 冻结 JSON 顶层形状零改；旧 payload 缺字段即 `None`；单 Oracle 路径字节级兼容 v0.5 / v1.0 | 复合时父 Oracle 字段闲置（只当容器） |
| B. `Task.oracles: tuple[Oracle, ...]` | 语义更直 | 每个 `Task(...)` 调用、runner、freezer、load 都要改；旧 JSON 没有顶层 `oracles`，还得发明「单元素回退」，漂移面比 A 大 |
| C. 父 Oracle 自己也计分 + `sub_oracles` 追加 | 不用容器 | N+1 次判分，父字段和第一个子 Oracle 必重复，账对不齐 |

A 满足「单 family 判分零回归」和「runner 最好不动」。容器闲置是显式的：freezer
在复合时只写 `profile: "s0"` + `sub_oracles`，不把 log 字段再抄一份到父级。

## 判分

铁律不变，作用域变成每个子 Oracle：

```
Pass ⇔ ALL(end_state == sub_oracle_i)   for i in sub_oracles
```

同一 end state 评所有子 Oracle（一次 episode，一次 hand-in）。不是分步中间态。

- 单 Oracle：`score()` 走现有 `_score_one`，返回值 **只有** `{passed, tag}`。
  现有测试的 `== {"passed": True, "tag": "pass"}` 继续成立。
- 复合：对每个子 Oracle 调 `_score_one`。
  - 全过：`{passed: True, tag: "pass", sub_tags: ("pass", ...)}`
  - 有失败：`tag` = **第一个**失败子 Oracle 的 tag（顺序 = `sub_oracles` 顺序）；
    `sub_tags` = 每个子 Oracle 的 tag 元组（诊断用，runner 仍只读 `tag`）。

v1 子 Oracle 顺序约定：先 log，再 recommend。所以「没记上」先于「推荐不合窗」。

每个子 Oracle 必须按 **最终** end state 写合同：

- log 子 Oracle：`ledger_tail` + `ledger = S0 ⊕ tail`（与今天 log 相同）。
- recommend 子 Oracle：`last_plan=[]`（自由推荐）、`plan_must_be_safe`、
  `plan_must_fit_windows`、`plan_windows` = **S0 ⊕ lunch 之后** 的 remainder
  （ADR 0007），`ledger` 也是最终账本。若把 leftover 的
  `ledger=tuple(S0.ledger)` 原样搬过来，log 成功后 recommend 会 `log_miss`。

  > **SUPERSEDED (2026-08-22, issue 10 ruling):** the `plan_windows` sentence
  > above (pure daily remainder after the log) is superseded by ADR 0014
  > (accepted): composite Recommend `plan_windows = meal-slot ∩ remainder`
  > (`plan_windows_for_meal`), the convention the mill, resolver, and the
  > single admission gate all use. ADR 0016 supersedes this file's pair
  > list. The Pass ⇔ sub-oracles rule is unchanged.

子 Oracle 不得再嵌套 `sub_oracles`（load 拒绝）。

## Serialization

复合 item 的 `oracle` 对象：

```json
{
  "profile": "s0",
  "sub_oracles": [
    {
      "profile": "s0",
      "ledger_tail": [{"food_id": "...", "grams": 244.0, "eaten_at": "today-lunch"}],
      "ledger": "s0_plus_tail"
    },
    {
      "profile": "s0",
      "last_plan": [],
      "plan_must_be_safe": true,
      "plan_must_fit_windows": true,
      "plan_windows": {"kcal": [..., ...], "protein_g": [..., ...]},
      "ledger": "s0_plus_tail",
      "ledger_tail": [{"food_id": "...", "grams": 244.0, "eaten_at": "today-lunch"}]
    }
  ]
}
```

- 缺 `sub_oracles` 或 `null` → `None`（旧 v0.5 / v1.0 / v0-gold 原样加载）。
- 出现则必须是长度 ≥ 2 的对象数组；否则 fail-closed。
- 每个元素复用今天的 `_oracle()` 形状（`profile` / `ledger` 哨兵 /
  `ledger_tail` / `last_plan` / `plan_*`）。recommend 子 Oracle 带与 log
  相同的 `ledger_tail`，以便 `ledger: "s0_plus_tail"` 解出最终账本。
- `load_exam` 额外接受 version `v1.0-composite-sample`（样例冻结，不是正考）。
  `v0.5-gold` / `v1.0-gold` 仍是已发布考试。正考文件 **不** 因本 ADR 改字节。

`Task.family` 序列化仍是 primary family（`log`），不是 `"composite"`。

## Quota（提案，待主 agent 裁决；未写入正考）

| 账本 | 数字 | 状态 |
|---|---|---|
| 基础考试 | **240**（ADR 0009 的 family 分配） | 已冻结在 v0.5；v1.0 正考扩量时仍按此账，不挤占 |
| 复合题额外配额 | **24**（= +10%） | **提案**。不写入 `v1.0-gold.json` |
| v1 复合 pair | 24 × `log → recommend` | 提案。唯一写入 v1 管线的 pair |

不采纳的数字：

- **0**：否决 ADR 0012。
- **12（+5%）**：切片太薄，family × persona 看不出信号。
- **48（+20%）**：在扩写通过率未知时过大；试点 20 还是单 family。
- 把 24 摊进 log / recommend 基础配额：否决（ADR 0012：额外占用，不挤占）。
- 把 `"composite"` 算进 `Task.family` 配额：否决（分类账不变）。

管线 / freeze extra 必须分栏记录，不得把复合计入 `base_accepted[log]`：

```json
"quota_ledger": {
  "base_quota": 240,
  "composite_extra_quota": 24,
  "base_accepted": {"log": N, "evaluate": M},
  "composite_accepted": K,
  "requested": {"log": ..., "evaluate": ..., "composite": ...}
}
```

`data/splits/v1.0-composite-sample.json` 只证明格式 + `load_exam` 往返，
**不** 冒充 24 题正考。pilot-20（`v1.0-gold.json`）保持单 family。

## Pipeline

`family_quotas` 可含键 `"composite"`（这是配额键，不是 `Task.family`）。

1. **Sampler**：`family="composite"` 只当池标签；仍抽 ~8 种可说 PortionFact。
2. **Expander**：composite 模式要一句多步 query + `steps: ["log","recommend"]`。
   `items` 只覆盖要 log 的餐。推荐步是自由推荐，不点名食物（克数仍不经 LLM）。
3. **Resolver**：`family=="composite"`（或 `steps` 长度 ≥ 2）走复合分支。
   先按 log 实现 Task，再构造 remainder recommend 子 Oracle，
   `Task.oracle = compose_oracles(log, recommend)`，`Task.family` 留 `"log"`。
   v1 只接受 `("log", "recommend")`；其他 pair fail-closed（`unresolvable`）。
   去重键加上 `"__composite__"` 前缀，避免和基础 log 抢同一食物多集
   （额外配额不能被基础题挤掉）。
4. **Judge / `validate_oracle_grams`**：对 `scored_oracles(task.oracle)` 逐个看克数。
5. **`validate_draft`**：整句 query 的泄漏检查仍跑；复合额外检查
   remainder 窗 = S0 ⊕ lunch，以及 recommend 窗可满足。
6. **Reviewer**：`resolved_items` 遍历子 Oracle（log tail 去重），不要看空容器。
7. **Freezer**：`sub_oracles` 按上面的 JSON 写出；单 family item 的 key 集合
   与今天字节一致。

## Out of scope

- 不改 runner、不改判分铁律、不改 v0.5 / v1.0 正考字节。
- 不在本轮冻结 24 道复合正考。
- 不引入 log+evaluate / update+recommend 等 pair（scorer 已与 pair 无关；
  管线 v1 只产 log+recommend）。
- 不把 `"composite"` 加入 `FAMILIES` / `Task.family`。
