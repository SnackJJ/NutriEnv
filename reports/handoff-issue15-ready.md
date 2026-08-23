# Handoff — issue 15 ready-to-execute state (2026-08-23)

> 30 轮目标推进的浓缩快照。**全部技术准备完成，只等主 agent 对 6 个设计裁决拍板。**

## main 状态

- HEAD: `4e1a12d` (docs: correct qns_gap_audit…) — 本 session 63 commits
- 全量 pytest: **1352 passed, 0 failed**，工作树干净
- 变更域：quality_gates（composite floors）、pipeline（5-family batch + recipe 全套）、
  resolver/sampler/expander、freezer/split（reload-valid）、scripts（verify_issue15 +
  gray_zone_probe 修复）、tests、reports（spec/impl/审查记录）
- 未动：docs/adr（仅注记）、data/splits（新 exam 尚未产）、*.sqlite、scorer.py、
  reactor.py（对称已由各轮审查确认）

## 已交付能力（全部经审查，附审查者）

| 能力 | 描述 | 审查 |
|---|---|---|
| composite floors 口径 | quality_gates lens：composite 的 recommend/evaluate 子 oracle 计入 4 个 floors | codex ACC |
| 5-family 批量入口 | generate_batch --family log/evaluate/recommend/update/composite | codex ACC |
| tier 通道 + recipe items/amount_path | tier 附 authoring 数据 + 定向食物数/克数 | codex ACC / claude RELEASE |
| recipe person | roster 人驱动 identity（persona×过敏原）collision-safe | claude RELEASE |
| pool_allergen + exclude_allergens | unfit fit→knife 构造，生产路径 ~4-6/30 | claude + codex RELEASE |
| verify_issue15.py | 14 断言 admission gate（rc 0/1/2） | codex 4 轮 ACC/RELEASE |
| mill reload-valid | generate_one fit/unfit 输出可 load_split | claude RELEASE |

## 14 断言实证（配方可产可累计）

- constrained ≥8：composite 自动达标（单一 composite 36 即 32 双命中）
- unfit ≥8：person × items=2+dinner，3 人 20 pool → 14 unfit
- tier：items 1/2/3 → single/pair/triple（explicit_grams 有 amount_path）
- persona×过敏原：person= → cam/fay/ben → 全 personов + egg/milk 覆盖
- leftover ≥24：composite 双命中 + scene 单 family

## 待裁决（reports/issue15-decision-package.md 全文）

1. 新题替换 vs 扩展 archive v1.0-gold（建议替换；EXAM_SPLIT_PATH 切换 + 2 处测试更新已定位）
2. 240 配额：log48/evaluate48/recommend72/update36/composite36（log=48 非 60）
3. tier 词典：single/pair/triple=items 1/2/3；explicit_grams 已通；long/synonym 定义
4. unfit 批量参数：person × items=2 + occasion（dinner/breakfast 调优）
5. live vs synthetic 全量（synthetic <5s，全能力验证过）
6. **冻结绑定 catalog：v1（13224 食物）vs v2（5431，配方全验证）→ 建议 v2**

## 裁决后第一步（精确）

```bash
# 1. 按配额 × 裁决 6 catalog 分次合成批量（evaluate 变体一次一个）
.venv/bin/python scripts/generate_batch.py --synthetic --model synthetic \
  --catalog data/fdc/catalog-v2.sqlite --family composite --count 36 \
  --recipe composite:person=roster-ben --seed 20260823 --output .work/comp.json --force
# ...（其余 family/变体按 issue15-runbook.md 分次）
# 2. 合并（list 拼接）+ 一次 freeze_tasks → 新 gold
# 3. 验收
.venv/bin/python scripts/verify_issue15.py --split <new-gold>
# 4. 14 断言全部 PASS 后：EXAM_SPLIT_PATH 切换 + test_split 更新（位置已定位）
```

## 文件索引

- 执行蓝图：`reports/issue15-runbook.md`（含演练/合并/成本证据）
- 裁决：`reports/issue15-decision-package.md`（6 点 + 影响面）
- 技术：`reports/tier-mapping-draft.md`、`reports/spec-*.md`、`reports/impl-*.md`
- 缺口全景：`reports/issue-consistency-audit.md`
- 验收工具：`scripts/verify_issue15.py`