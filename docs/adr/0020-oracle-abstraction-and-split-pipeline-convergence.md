# 0020. Oracle 架构对齐、标准 Realize 接缝收敛与数据集流水线闭环

- **状态**: Accepted
- **日期**: 2026-08-29
- **相关 ADR**: ADR 0002, ADR 0006, ADR 0007, ADR 0013, ADR 0014, ADR 0015, ADR 0016, ADR 0019
- **审查参与**: Claude Code, Grok, Gemini (AGY)

---

## 背景与问题陈述

在对 `v2.1-gold` 40 题生成数据集的审计复核中，Claude Code 与 Grok 联合发现了生成流水线绕过核心评测接缝所带来的结构性隐患：

1. **绕过成熟领域接缝**：`generate_samples_v2.py` 曾手搓 `Task(oracle=WorldState(...))` 简单对象，导致 Update 遗漏了按规则选择性重算 Windows、Recommend 遗漏了剩余预算扣减与 `last_plan=[]` 自由推荐标记、Evaluate 遗漏了 `last_reasons` 自动推导；
2. **Split Schema 私有化失准**：数据集直接使用了 `{"tasks": [...]}` 私有格式且缺少 `catalog_sha256` 与 `s0` 全窗数据，导致现有 `load_split` / `load_exam` 与 `Scorer` 无法读取评分；
3. **Tier-2 投票算量与共识分母漏洞**：直接信任 LLM 自报克数而非代码按表核算，且在 1/1 幸存投票时误判为 100% 高置信度；
4. **人审闭环未实质落地**：未审的 Tier-2 候选直接写入带有 `-gold` 后缀的正式文件，违背 ADR 0019 纪律。

---

## 架构决策

### 1. 全面收敛至深度 Realize 领域接缝（禁止手搓浅层 Oracle）

流水线禁止直接实例化无序的 `Oracle` 字段包，所有题型必须通过或对接已有的成熟构造逻辑：

* **Log 题型**：调用 `_log_oracle` / `realize`，同时填入 `ledger_tail`（新增记录）与 `ledger = S0 ⊕ tail`（全量状态校验），完整保留 `profile`；
* **Evaluate 题型**：调用 `realize_evaluate`，由领域逻辑内部自动计算营养窗口与违规原因，自动推导 `last_verdict`（`"accept"` / `"reject"`）、`last_reasons`（如 `("ALLERGY_MILK",)`）、`evaluated_plan` 与 `bound_labels`。安全 Knife 攻击项保留过敏 tag，正常餐盘严格执行 `allergen_clash` 过滤；
* **Recommend 题型**：调用 `plan_windows_for_meal(profile.windows, ledger_totals(cumulative_ledger), occasion)` 精确推导该餐的剩余营养预算，显式设置 `last_plan=[]`（自由推荐标记）、`plan_must_be_safe=True`、`plan_must_fit_windows=True`，并绑定当前累计饮食 `ledger=tuple(cumulative_ledger)`；
* **Update 题型**：严格按照 ADR 0014/0015 的 Env 规则打补丁——仅在体征/阶段变更时重算 Windows，过敏原修改保持原 Windows 不动，隐式意图设定 `update_band`（保留 S0 作为基线），且必须设置 `ledger`；
* **Composite 题型**：调用 `compose_oracles`，多阶段子任务共享同一个终态 `WorldState`，后续阶段的推荐/评估子窗口必须严格建立在“S0 ⊕ 前序 Log 产物”的基础之上。

### 2. 标准 Split JSON Schema 统一规范

数据集完全对齐 `split.py` / `freezer.py` 既有规范：

```json
{
  "version": "v2.1-gold",
  "catalog": "catalog-v2.sqlite",
  "catalog_sha256": "...",
  "count": 40,
  "items": [
    {
      "id": "adr19-eval-1014",
      "family": "evaluate",
      "query": "Evaluate this lunch: a bowl of Greek yogurt.",
      "persona": "everyday",
      "situations": [],
      "s0": {
        "profile": {
          "user_id": "roster-fay",
          "sex": "female",
          "age_y": 28,
          "weight_kg": 58.0,
          "height_cm": 165.0,
          "activity": "moderate",
          "allergies": ["milk"],
          "windows": { "kcal": [1800.0, 2200.0], "protein_g": [70.0, 110.0] }
        },
        "ledger": []
      },
      "oracle": {
        "evaluated_plan": [{ "food_id": "2705430", "grams": 200.0, "eaten_at": "today-lunch" }],
        "last_verdict": "reject",
        "last_reasons": ["allergy_milk"],
        "plan_windows": { "kcal": [600.0, 800.0], "protein_g": [25.0, 40.0] }
      },
      "resolutions": [ ... ]
    }
  ]
}
```

### 3. 数据流严格分层与人工审核闭环

为贯彻“LLM 产出永远是候选，非人工核准绝不进 Gold”的硬纪律：

1. **候选池**：生成流水线一律输出至 `data/candidates/v2.1-candidates.json`；
2. **审核看板**：`reports/v2.1-gold-review.html` 提供查看口语题面、两级解析与三模型投票推理细节，并在审核通过后提供一键导出功能；
3. **已审池**：导出为 `data/approved/v2.1-approved.json`；
4. **冻结金标**：由 `freezer` 编译器加载已审池，校验所有 Tier-2 均有核准标记后，编译为 `data/splits/v2.1-gold.json`。若有未审的 Tier-2 候选，`freezer` 坚决 Fail-closed 拒绝编译。

### 4. Tier-2 多模型投票共识与防呆核算

1. **投票对象**：DeepSeek、Kimi、GLM 三模型针对 FNDDS 事实表投票，推断 `(base_unit, multiplier)`；
2. **代码核算**：由代码在 FNDDS 表中查找真实 `base_grams`，计算 grams = round(base_grams * multiplier)，统一取整到整克，杜绝 LLM 算术误差与非整克漂移；
3. **严格共识判定**：
   High Confidence <=> Valid Voters >= 2 and Consensus Ratio >= 66%
   单票幸存（1/1）坚决不标为 High Confidence，提示人工介入。

---

## 验证与验收标准（Round-Trip Test）

整改完成的唯一客观验收判据：
Candidates -> Approved -> Freezer -> load_split -> Scorer.score() => 100% PASS
