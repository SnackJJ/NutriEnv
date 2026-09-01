# NutriEnv Reports Directory Structure

本目录用于存放 **NutriEnv Benchmark** 的权威评测榜单、裁决报告与各主流大模型的端到端推演轨迹数据。

---

## 🏆 一、 当前活跃核心报告（Active Golden Artifacts）

| 文件名称 | 类型 | 说明 |
|---|:---:|---|
| [`v2.2-gold-master-leaderboard.md`](./v2.2-gold-master-leaderboard.md) | 👑 总榜 | **全景天梯总榜**：火山引擎全明星大模型 100 题百分制得分与各能力维度雷达表 |
| [`v2.2-gold-claude-opus-final-ruling.md`](./v2.2-gold-claude-opus-final-ruling.md) | ⚖️ 裁决 | **Claude Opus 深度裁决书**：对数据绑定、离散容差与评测公允性的最终仲裁 |
| [`v2.2-gold-fairness-and-false-negative-audit.md`](./v2.2-gold-fairness-and-false-negative-audit.md) | 🔍 审计 | **假阴性全量治理报告**：500 条大模型轨迹的地毯式分析与归因 |
| [`v2.2-gold-review.html`](./v2.2-gold-review.html) | 🖥️ 可视化 | **100 题金标审查页**：支持交互式查看每道题的 S0 初始状态、Oracle 真值与约束 |

---

## 📊 二、 当前有效 Benchmark 评测轨迹数据（Active Datasets）

- `benchmark_ark_glm-5.3.json` — 智谱 GLM-5.3 旗舰（56.0% 👑 综合冠军）
- `benchmark_ark_deepseek-v4-flash.json` — DeepSeek-V4-Flash（55.0% ⚡️ 单项三冠王）
- `benchmark_ark_deepseek-v4-pro.json` — DeepSeek-V4-Pro 旗舰推理（52.0% 🎯 运筹大师）
- `benchmark_ark_glm-5.3-flash.json` — GLM-5.3-Flash（50.0% ⚡️ 背包规划冠军）
- `benchmark_ark_kimi-k3.json` — 月之暗面 Kimi-K3（40.0% 🌙）
- `benchmark_dashscope_qwen3.8-27b.json` — 通义千问 Qwen 3.8 27B（39.0%）

---

## 📦 三、 历史归档区（`reports/archive/`）

过期的历史中间物、早期样本与研发阶段演进文档已完整归档至子目录：

- `archive/v2.1_and_earlier/` — v2.1、v2.0、v0.x 早期样本评审与试点报告；
- `archive/pipeline_specs_and_impls/` — 历史流水线规格说明（Spec）、实现记录（Impl）与评审纪要（Review）；
- `archive/legacy_benchmarks/` — 早期非统一通道或废弃网关的 Benchmark 原始跑测数据；
- `archive/audit_and_probes/` — 历史 Dry-run 零漂移比对、Gray-zone 灰区探针与 QNS 差距审计；
- `archive/phase6/` — 历史阶段 6 候选槽位与清单。
