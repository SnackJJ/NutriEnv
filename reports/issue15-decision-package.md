# Issue 15 设计裁决包（给主 agent，一次拍板）

> **用途**：把分散在 `ticket-draft-new-form-items.md`、`tier-mapping-draft.md`、
> `issue15-runbook.md`、`impl-*.md` 的信息浓缩为 5 个可拍板的决策。每个问题给
> 选项 + 技术现状 + 影响 + 推荐。全部技术验证已完成（1340 passed），裁决后可直接照
> `issue15-runbook.md` 开跑。

## 裁决 1 — 新题是替换还是扩展 archive v1.0-gold？

- 背景：v1.0-gold（20 题，log+evaluate-fit only）已归档；用户已表态"gold 是归档旧产物，讨论新形态"。
- 选项：
  a) **替换**：新形态题成为新的 240 exam（v2.0-gold 之类），archive v1.0-gold 保持归档（推荐，与你的表态一致）
  b) 扩展：与 v1.0-gold 并存另一套（语义重复，不推荐）
- 影响：决定冻结产物文件名、EXAM_SPLIT_PATH 是否切换、landing_verify 是否加新 exam 分支。
- **技术现状**：EXAM_SPLIT_PATH 现在指向 v0.5-gold（240 旧考试）；新 exam 走新文件即可。

## 裁决 2 — 240 内五 family 配额

- ADR 0016 表：recommend 72 / evaluate 48 / update 36 / composite 36 = 192 → **log = 48**（240-192）。
- 注意：ticket-draft 早期写的 "log 60" 是错的（会超 240）；quota_ledger 已按 48 验证满额接受。
- 选项：确认 log 48 / evaluate 48 / recommend 72 / update 36 / composite 36（推荐）；或调整数字。
- 影响：决定每次 generate_batch 的 `--count` 分配；floors 在 evaluate/recommend 内（unfit≥8、constrained≥8、leftover≥24）。

## 裁决 3 — Evaluate tier 六档的题面内容词典

- tier 数据通道已就绪（`tier=` + recipe `evaluate:tier`，freeze 往返保留）。
- **single/pair/triple = items 1/2/3**（已实证：triple 4/4 产三食物题）。
- **explicit_grams** = `amount_path=explicit_grams`（题面说克数，gram-exact 已实证）。
- **long / synonym** 需词典裁决：
  - long：定义何为"长话术"（多从句/杂讯的 evaluate query）——需确认接受"现有陈述式 query 算 long"还是需专门 shell。
  - synonym：用别名/俗名（PB ↔ peanut butter）——依赖 catalog 别名丰富度 + near_synonym 行；需确认 alias 覆盖策略。
- 影响：决定 tier 内容配方（recipes 怎么组合）；floors 底线 single 7/pair 11/triple 11/long 5/explicit_grams 4/synonym 3。

## 裁决 4 — Evaluate-unfit 的批量参数

- 技术现状：fit→knife 构造已打通（pool_allergen + exclude_allergens + knife=allergy + person + items=2），生产路径 **~4-6/30 unfit**（occasion 调到 breakfast 更高 6/30；items 递增 yield 增）。
- 需裁决：unfit 批量用哪些参数组合达标 8？
  - 推荐：多 person × seed 累积（cam/egg、kim/soy、fay/milk、hao/shellfish…）× items=2 + occasion=dinner，多批跑到 ≥8。
  - 或接受"homework 绕行"：unfit 用确定性 fixture catalog 产 + 标注 synthetic-only。
- 影响：决定 evaluate 配额里 unfit 的 recipe 配方与批次数。

## 裁决 5 — live 还是 synthetic 批量产

- synthetic：离线、零配额、可复现（seed 固定）；**runbook 默认**；recommend/update/composite 全通过。
- live（LLM expander）：需接 recommend/update prompt shells（batch-families 已知限制，**未布线**）；耗配额；文字更真实。
- 选项：
  a) **synthetic 全量 240 + 冻结**（推荐——管线能力已全验证，冻结产物是代码定锚）
  b) live 全量（需先接线 recommend/update shells —— 一个额外 issue）
  c) synthetic 产 + live 精选替换（混合）
- 影响：决定产出过程成本与产物品多样性来源。

## 裁决后的执行路径（照 runbook）

1. 按裁决 2 配额 × 裁决 1 的文件名，分次跑各 family/recipe 变体（evaluate 变体一次一个）。
2. 合并分次产物 → 跑 14 断言全验（constrained 达标实证、unfit 生产路径 3/8 已证、tier/persona/leftover 配方路径全通）。
3. 缺口扩量（seed 累积/occasion 调优）到 floors 全达标。
4. freeze → load_split 往返 → landing_verify → 14 断言最终验收。
5. 更新 EXAM_SPLIT_PATH（如需）与 issue 14 的 4 条 checkbox。