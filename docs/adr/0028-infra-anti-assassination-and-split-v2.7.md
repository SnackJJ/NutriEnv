# ADR 0028: 基础设施超时容错升级、量词公理重导出与 split v2.7-gold

- **状态**: Accepted
- **日期**: 2026-09-03
- **涉及系统**: `scripts/eval_benchmark_suite.py`, `src/nutrienv/bench/scorer.py`, `src/nutrienv/bench/split.py`, `scripts/build_v2_7_gold.py`, `data/splits/v2.7-gold.json`
- **关联文档**: ADR 0025, ADR 0026, ADR 0027, `.scratch/reviews/claude_v2_7_evaluation.md`

---

## 1. 背景与核心问题

在 NutriEnv v1.0 全量 128 题（双模型 256 条轨迹）的构造效度三方独立审计中，Claude Opus 5 与 Grok 揭示了四大关键系统性缺陷：
1. **基建级超时暗杀事故（P1）**：`scripts/eval_benchmark_suite.py` 在 API 读超时（45s）时，将异常静默篡改为 `{"op": "finish"}` 强制交卷判零分。由于 DeepSeek 推理耗时长（单步为 GLM 的 2.1 倍），历史榜单上 DeepSeek-Pro 有 25% 的题目、DeepSeek-Flash 有 17.2% 的题目被基建腰斩，导致历史榜单名次严重倒挂。
2. **量词与金标倒挂（P2）**：题干明写量词，物理表有专属 key，但金标锁死了错误量词（`adr20-comp-5050` patty 85g 锁死 65g；`adr20-comp-5034` piece 35g 锁死 85g；`adr26-eval-1304` cup 158g 错记为 118g）。
3. **退化策略可利用面（P4）**：`scorer.py` 判定拒绝理由时仅要求交集非空，无脑罗列 13 个理由码可利用漏洞。
4. **加载器版本硬编码**：`src/nutrienv/bench/split.py` 硬编码限制了旧版考试集，导致新版文件报错。

---

## 2. 决策内容

### 2.1 基础设施工业级容错升级（P1）
1. 单步超时时间从 45.0s 提高至 **90.0s**，增加 4 次带指数退避的单步重试；
2. 彻底删除 `text = '{"op": "finish"}'` 静默伪造代码，改为抛出 `EpisodeInfraError`；
3. 引入**回合级自动整局重试（Episode-level Retry）**：若某回合遭遇不可抗力网络断开，自动执行 `env.reset()` 进行整局重跑（最多重试 2 次）；
4. 若重试耗尽仍失败，标记 `is_void=True`，记录 `score_tag="VOID_INFRA_ERROR"`，并单独输出 `void_count` 与 `clean_pass_rate_pct`，绝不计入有效得分分母。

### 2.2 判分器反伪造安全门禁（P4）
在 `scorer.py:_score_verdict` 中增加两道硬性安全门禁：
1. **矛盾理由互斥门禁（Mutual Exclusion）**：在同一营养素维度上，严禁同时报出 `_hi` 与 `_lo`；
2. **虚假过敏指控门禁（Phantom Allergy Accusation）**：若食物与档案中完全不存在过敏原，模型虚构报出 `allergy` 直接判 `wrong_goal`。

### 2.3 解除加载器版本硬编码
在 `src/nutrienv/bench/split.py` 中，将 `_EXAM_VERSIONS` 升级为正则动态验证器 `_EXAM_VERSION_RE = re.compile(r"^(v[2-9]\.\d+|nutrienv-v\d+\.\d+)-(gold|mini)$")`，同时保证已废弃归档的 `v0.x` 依然严格 Fail-Closed。

### 2.4 全链路公理化重导出与 v2.7-gold 编译（P2）
1. 编写 `scripts/build_v2_7_gold.py`，调用 `plan_windows_for_meal` 全链路重新导出 `adr20-comp-5050`（patty 85.0g）与 `adr20-comp-5034`（piece 35.0g），修正 `adr26-eval-1304` 白米饭为 158.0g；
2. 验证生成的 128 题通过 `load_split`、可达性测试（0 unreachable）与全量 1400 项回归测试；
3. 正式冻结并落盘为 `data/splits/v2.7-gold.json` 与对外镜像 `data/splits/nutrienv-gold.json`。

---

## 3. 验证结果
- `pytest`: **1400 passed, 0 failed, 0 error**
- `check_achievable(v2.7-gold)`: **128/128 solvable, 0 unreachable**
- 题型配额严格维持：Update 5, Log 14, Evaluate 39, Recommend 23, Composite 47（共 128 题）。
