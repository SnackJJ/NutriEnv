# Issue 全套一致性评估（2026-08-22，main @ d9d687f）

协调者按用户要求通读全部 14 个 issue + 关键 ADR + roadmap，核对代码证据，
判断哪些 checkbox 是"漏勾"、哪些是真实缺口、哪些设计已过时。

## 结论先行

**14 个 issue 的实现全部在 main 上**（含 09/10 本次排程合并、14 之前并入）。
发现的"未勾 checkbox"绝大多数是**早期 issue 勾选纪律缺失**（实现早已存在），
不是实现缺口。真正值得推进的是二类：① 需要"新 exam 存在"才能验证的
**admission/freeze 前置断言**（14 的 4 项 + 08 已有实现的 band 往返门）；
② 冻结统计口径的 composite 处理（1030 审查遗留，见下）。

## 各 issue 评估矩阵

| # | checkbox | 实现证据 | 判定 |
|---|---|---|---|
| 01 Evaluate verdict envelope | 0/7 勾 | scorer.py `_score_verdict`（accept/reject/silence）、realize.py reject 合同 | 漏勾（实现齐全） |
| 02 Profile body facts | 0/3 勾 | types.py `sex/age_y/height_cm/weight_kg/activity/phase`，phase 默认 `maintain` | 漏勾 |
| 03 Scorer zero-drift | 0/6 勾 | scorer.py `score()`/`_fail`/verdict 分支；240 零漂移历史测试 | 漏勾 |
| 04 window rederive + bands | 0/5 勾 | generate_one.py update 路径 band（cut/muscle/fatigue）、windows.py | 漏勾 |
| 05 evaluate-unfit | 6/6 勾 | quality_gates unfits、validator unfit 校验、realize bind reasons | 完成 |
| 06 mill Log | 8/8 勾 | generate_one log family；"故意难度"尾巴留给 admission（明示） | 完成（尾巴已记录） |
| 07 mill Evaluate knives | 0/6 勾 | 07 系列 commits 已在 57434b1（merge-base）历史；swap/over/under/allergy 在 realizations/tables/ | 漏勾 |
| 08 mill Rec/Update 模板 | 0/7 勾 | 08 系列 commits 已在 merge-base；`test_band_freeze_replay.py` 已实现最后一项 band 往返门 | 漏勾（含 band 门已实现） |
| 09 两阶段 review | 7/7 勾 | 本次排程合并（ecae26d）；gray-zone-probe-v2 freeze-blocker 已满足（d9d687f） | 完成 |
| 10 composite | 5/5 勾 | 本次排程合并（e0f7dab）；ADR 0014 六窗、36-in-240、occasions.py | 完成 |
| 11 catalog immutable | 0/5 勾 | catalog.py freezable/immutable（13 的序列化定序配套） | 漏勾 |
| 12 achievable bench 能力 | 5/5 勾 | bench/achievable.py | 完成 |
| 13 catalog 可复现 | 4/4 勾 | build_fdc_catalog 确定性排序 | 完成 |
| 14 质量门 | 1/6 勾 | quality_gates.py 五 gate 全在（window_leaks/leftover_recommends/recommend_coverage/evaluate_tier/situation_floors） | **4 项是"等新 exam"断言**（见下） |

## 新旧设计矛盾审计

| 矛盾点 | 状态 |
|---|---|
| ADR 0012 "composite extra quota" vs ADR 0016 "36 inside 240" | **已处理**：0012 注记 superseded（6039070） |
| ADR 0013 "plan_windows 纯 remainder" vs ADR 0014 "meal-slot ∩ remainder" | **已处理**：0013 注记 superseded（6039070）；代码统一 `plan_windows_for_meal` |
| roadmap Phase 6 "复合题额外配额（ADR 0012）" | **过时**：ADR 0016 已改 36-in-240，roadmap 这句话是历史的（roadmap 早于 0016）。已在 10 实现按 0016 |
| roadmap Phase 3 灰区三对 vs issue 09 freeze-blocker 三对锚点 | 两者互补：roadmap 三对（sandwich/lasagna/omelet）v1 已跑；freeze-blocker 锚点（chicken/tuna/beef）v2 已跑（d9d687f）。**无矛盾，均满足** |

## 真正待推进的（按优先级）

1. **14 的 4 项"等新 exam"断言**（admission/freeze 票）：
   - Recommend 覆盖 persona×过敏原 + 题面不泄漏窗口数字
   - Evaluate 覆盖每个难度档
   - leftover Recommend 达 ADR 底线（24）
   - Evaluate-unfit / constrained Recommend situation floors 被测试钉住
   → 这些**必须有 v1.0 exam 冻结产物才能跑**。是 admission/freeze ticket 的验收门。
   → 前置：Phase 5 试点 20 题全链跑（roadmap）——首批候选 → freeze → 用这 4 项断言验证。

2. **冻结统计口径的 composite 处理**（1030 审查遗留，非 14 的范畴）：
   - `leftover_recommends` / `recommend_coverage` / situation floors 只认
     `task.family == "recommend"`，composite（family log/update）含 recommend
     子 oracle 但不计入 → 冻结时 composite 的 recommend 场景不贡献 floor。
   - ADR 0016 说 floors 在 evaluate/recommend 内；composite 的 recommend 子
     oracle 是否计入需要设计裁决。**这是"继续推进"里最值得先定的口径。**

3. **06 的"故意难度"尾巴**：naked cut-nouns 不作为 pass-expected 冻结项，
   除非 admission ticket 显式裁决"intentional difficulty"——留给 admission。

4. **roadmap Phase 5 试点 20 题 + Phase 6 扩量**：管线已具备全部代码
   （Sampler/Expander/Resolver/Judge/validate/Review/Freezer 都就位），
   试点是让冻结口径落地的实际载体。

## 建议

推进顺序（用户裁决后执行）：
A. 定 composite situation floor 口径（改 quality_gates 或记录裁决）
B. Phase 5 试点 20 题全链跑 → 产出首批 v1.0 候选 + freeze
C. 用 14 的四条断言验收试点产物 → 正式 admission/freeze ticket 闭环

不动的：01-13 的 checkbox 补勾（纯记录，不产生行为变更，可在 admission 时
顺手补）；已 supersede 的 ADR 注记保持现状。

## 追记 (2026-08-22)

待推进第 2 项（composite situation floor 口径）已裁决并落地：composite 的
recommend/evaluate 子 oracle 现在计入 constrained / leftover / persona×allergen
coverage / Evaluate-unfit floors（`_recommend_lenses` / `_evaluate_lenses`，
commit fec223d，spec 见 `reports/spec-composite-floors.md`，实现报告
`reports/impl-composite-floors.md`）。剩余前置只有 14 的四条"等新 exam"断言
与 Phase 5 试点。
## 更新（2026-08-23）：checkbox 补勾完成

按上表核对的"漏勾"项已全部补勾（.scratch 记录）：
- 01/02/03/04/07/08/11：34 个 checkbox 全部 [x]（实现已在表中核实：scorer verdict、types.py body facts、update bands、knives、模板+band 门、catalog immutable）。
- 14：`检查函数不硬编码 data/splits/*.json 或具体 item id` 已核对勾选（quality_gates.py 无路径/ID 字面量）；其余 4 项（persona×过敏原覆盖 / Evaluate 全 tier / leftover 24 / situation floors）仍等新 exam 冻结产物（issue 15 交付后验收）。
- 04 的 Status 补注"checkbox 实现核对后补勾"。
剩余直接依赖 design 裁决的只有 issue 15 的 4 个 checkbox（配额确认、批量产、floors 达标、冻结+14 验收）。
