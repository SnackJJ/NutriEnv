# LLM 造题流水线方案总结（NutriEnv 数据生成）

> 目标：让 LLM 参与考题生成以获得"真实用户表述"的多样性，同时保证 Oracle 克数零风险
> （判分铁律：`Pass ⇔ end state == Oracle`，克数精确匹配，无宽容判分）。

---

## 0. 现状：考题是怎么造的

```
bench/realizations.py（267 个手写 dataclass Row，10 张表）
        ↓ materialize_split.py 按 seed_id 招收增量（谁进谁不进由人定，附理由）
data/splits/v0.5-gold.json（240 条冻结考试题）
```

- 增量：v0.1=64 → v0.2=100 → v0.3=156 → v0.4=207 → v0.5=240（ADR 0009 配额：
  log 48 / update 36 / recommend 72 / constrain 36 / evaluate 48）。
- JSON 不手写，每条的 query/oracle 由 `Generator._*_from_row` helper 从 Row + live catalog 推导；
  克数在 materialize 时算好烤进 JSON。
- Generator 是"工厂"（ADR 0006：seed 不是考试）：考试路复用其 helper，工厂路（`sample()`）
  仅供测试/开发。运行时 `run_split --split` 只读冻结 JSON，不调 `sample()`。
- split 里只出现 25 种食物——是手写 Row 的引用集合，不是抽样抽窄。

## 1. 核心风险：Oracle 克数谁说了算

- `resolve_portion`（`src/nutrienv/world/portions.py`）：bench 侧确定性语法解析器。
  **不在 env 运行时**——`log_meal`/`submit_plan` 只收 grams；agent 自己根据
  `get_food` 返回的 portions 表 + 手册（react.py v1：cup/tbsp/tsp/slice/piece 五种量具）
  做换算。
- 克数锚点 = FNDDS `food_portion.csv`（survey.zip，22046 行）。

### 关键发现 1：牛排 30g bug 的完整因果链

- catalog 里 `Beef, steak, NFS` 只有 `{slice: 30, cup: 135}`；
- `resolve_portion("a serving of steak")` 走本地发明的回退 `piece→slice→cup` → **30g**；
- 但 FNDDS 原始数据里（survey.zip 实测，每食物 8 行，sr_legacy 无）牛排有：
  **regular=160、QNS=160、thick=240、thin=120、cup=135、piece/slice=30、oz yields=20、
  cubic inch=17**（"16 行"是初稿误数：把两个 fdc_id 的行合在一起了，单食物是 8 行）；
- 是 `build_fdc_catalog.py` 的 `_portion_key` 把 thick/thin/regular/oz 等全部过滤掉了
  （只保留 cup/tbsp/tsp/slice/piece/can 六种 pattern，first-wins），QNS 被显式丢弃
  （`blob.startswith("quantity not")`）。

**结论：克数错误的根因在"数据过滤 + 本地回退逻辑"，不在 LLM。**

### 关键发现 2：QNS 是 FNDDS 内建字段，不是外部数据集

- QNS = **"Quantity not specified"**（modifier 90000）：USDA 官方定义的
  "用户没说清份量时该食物默认多少克"。
- 分布：22046 行份量数据中 5326 行是 QNS；有份量数据的 5395 个食物里 ~99% 都有。
- 已验证：steak QNS=160g、fried egg QNS=55g、banana QNS=126g。
- **修正（Claude 审查后撤回初稿说法）**：`v0-log-banana-001`（"a banana"→126g）**不是
  手写、也不是隐式 QNS**——`realizations.py:279` 存的是
  `FuzzyRow("fz-banana-piece", "banana", "a piece", …)`，克数由
  `resolve_portion("banana", "a piece")`=126.0 从 FNDDS 的 **piece 条目**算出
  （banana portions=`{piece:126, cup:150, slice:6}`）；QNS 恰好同为 126 是巧合。
  `Grams are never stored` 铁律未破坏。

### 关键发现 3：realizations 早已把"克数锚点"和"措辞"分成两列

Claude 审查时发现（比初稿的点 3 更进一步）：`realizations.py` 的每一行本来就把
`phrase`（机器可解析、决定克数、由代码从 catalog 挑）和 `query`（自然语言、给 agent 看）
分开了——**这正是"点 3 多样性"想要的机制，架构已支持，不需要新设计映射层**。LLM 的活
变得非常窄且安全：给定 (food_id, phrase, family)，只写 query 那一句，克数从头到尾不经过
LLM。这也解释了 review sheet 上那 31 条"推导等价"（phrase 用 piece、query 说 "a banana"）
是正常条目，不是缺陷。

## 2. 方案：四层架构（每个克数锚定 FNDDS/QNS）

```
点1 数据锚点     完整 FNDDS 接入：修 _portion_key，保留 thick/thin/regular/oz + QNS
点2 默认值锚点   serving 回退改用 QNS（替代本地 piece→slice→cup）
                  + 差距审计：解析结果 vs QNS 差距过大 → 列出 → 人工只审少数异常
点3 多样性       LLM 扩写真实用户表述（"一块厚切牛排"），映射到有锚点的档位（thick→240）
点4 审查自动化   LLM review harness：多 LLM 子代理评审 + 汇总（一致性/自然度/蕴含）
```

分工铁律：**LLM 的产出永远是"候选"，不是"事实"；克数锚点 = FNDDS 表值/QNS；
LLM 审查 = 一致性/plausibility/自然度；人审范围缩到"差距异常条目 + 新档位入库"。**

## 3. 实验验证：LLM 能否判断份量 plausibility

脚本：`scripts/portion_judge_probe.py`（可复跑）。

- 设计：15 用例（牛排 30/120/160/240/500g 判别梯度 + 鸡蛋/香蕉/牛奶/橄榄油/米饭好坏对照），
  ground truth 锚定 FNDDS QNS；每用例独立调用 LLM K=5 次（temp 0.7），ok 比例 ≥ 0.6 接受。
- 模型：deepseek-v4-flash。

| 用例 | 克数 | 期望 | ok 比例 | 判定 |
|---|---|---|---|---|
| steak-030 | 30g | BAD | 0.00 | 拒绝 ✓ |
| steak-120 | 120g | ok | 0.80 | 接受 ✓ |
| steak-160 | 160g | ok | 1.00 | 接受 ✓ |
| steak-240 | 240g | ok | 1.00 | 接受 ✓ |
| steak-500 | 500g | BAD | 0.20 | 拒绝 ✓ |
| egg-055 / egg-005 | 55g / 5g | ok / BAD | 1.00 / 0.00 | ✓ / ✓ |
| banana-126 / banana-010 | 126g / 10g | ok / BAD | 0.80 / 0.00 | ✓ / ✓ |
| milk-122 / milk-1500 | 122g / 1500g | ok / BAD | 0.80 / 0.00 | ✓ / ✓ |
| oil-014 / oil-100 | 14g / 100g | ok / BAD | 1.00 / 0.00 | ✓ / ✓ |
| rice-300 / rice-2000 | 300g / 2000g | ok / BAD | 1.00 / 0.00 | ✓ / ✓ |

**结果：15/15 全中；known-good 8/8 接受，known-bad 7/7 拒绝。
决定性判据通过：30g 牛排 5/5 拒绝，160g 牛排 5/5 接受。**
判别间隙干净（bad 组 0.00–0.20，good 组 0.80–1.00，中间为空），重复采样 + 阈值必要。

**证明范围要收窄（Claude 审查指出）**：这 15 个用例全是极端对照——steak 30 vs 160
（5.3×）、egg 5 vs 55（11×）、banana 10 vs 126（12.6×）、milk 122 vs 1500（12×）、
rice 300 vs 2000（6.7×）、oil 14 vs 100（7×）。而真实造题的错误落在灰区（实测）：
sandwich piece 175 vs QNS 115（1.5×）、lasagna piece 206 vs QNS 250（1.2×）、
omelet piece 55 vs QNS 110（2.0×）。**"判别间隙干净"是用例设计得极端造成的，不能外推
到 1.2–2.0× 的真实误差；judge 封 gate 之前必须补一组灰区用例（就用上面三对，
ground truth 已知）。**

LLM 用的是真实世界份量常识：30g → "约一盎司，远小于正常单人份"（自己发现了 oz/g 混写模式）；
160g → "typical single-serving portion"（恰好对齐 FNDDS QNS=160）；
240g → "约 8.5 盎司"（对齐 FNDDS thick=240）。相当于一个"没查表的 QNS 代理"。

### 边界（诚实校准风险）

- LLM 常识是"世界平均"，个别食物的 FNDDS QNS 若偏离常识可能被误杀——
  但误杀 = 丢弃候选（丢多样性），不会产生错误 Oracle，可接受。
- LLM judge 是**过滤器**不是**答案定义者**：160g 仍由 FNDDS QNS 定义，judge 只是认可它。

## 4. 完整流水线形态（已定稿，逆向采样 + LLM 组餐）

```
Sampler（代码）  从 FNDDS 抽超量食物池（含 PortionFact 备选），batch seed 可复现
Expander（LLM）  从池中组合理的一餐 + 写自然语言 query（多模型轮换增多样性）
Resolver（代码） 每个食物表达反解回 PortionFact；任一失败 → 拒（fail-closed）
                 + 包含性 / 泄漏 / 手册对称 / 近重（食物 id 多集哈希）检查
Judge（LLM 小模型） plausibility：白名单先过，表外 K=5/0.6 采样（灰区验收后封门）
validate_draft（代码） 漏题/可达/过敏原；query↔Row 反解强制（查不到即拒）
Review harness（LLM）  多子代理评审（一致性/自然度/蕴含）+ 汇总，人只审异常
Freezer（代码）  冻结 v1.0-gold.json（绑定 catalog-v1 sha），EXAM_SPLIT_PATH 改指
```

- 保留规则：组餐有组合多样性 → 每池保留 ≤3 条；素材固定（单食物）→ 择优 1 题。
- Profile：代码按 persona 生成 S0（数值代码定），LLM 只润色人设文本；gym 人设
  混报克数 + PortionFact，仅重度健身全克数。
- 复合题（ADR 0012）：240 基础配额之外另加，多 Oracle 判分。
- 试点 20 题 = 8 单食物 log（择优）+ 6 多食物 log 一餐（保留多条）+ 6 evaluate 一餐，
  覆盖 qns/thick/thin/fl_oz/cup/slice 各 ≥1 + gym explicit-grams 混报。
- 实施细节与验收标准见 `reports/v1.0-candidate-pipeline-roadmap.md`。

## 5. 必须同步处理的三处隐患

1. **validate_draft 反解检查只在 query 匹配到 Row 时生效**（`validator.py:631` 按 query
   原文找 Row）——LLM 生成的 query 匹配不到，检查被静默跳过。需抽成独立函数直接调用。
2. **agent 手册对称性**：serving 回退（piece→slice→cup）和菜名语法（DISH_NOUNS）当前
   **对 agent 不可见**（手册只列 5 种量具）。这类表达进题前必须先写进手册，否则
   agent 按手册无法复现 Oracle，比克数错更隐蔽。
3. **catalog rebuild 会红 split 测试**（v0.3 起的设计：宁可红也不要静默漂移）——
   完整 FNDDS 接入后 validate 重解析可能红，属预期行为。

## 6. 与现有约束的关系

- ADR 0005："an LLM may paraphrase the query once and the result is frozen——
  **never used as judge**"。本方案不违反：LLM 审查做一致性/plausibility，不做
  事实判定（事实由 FNDDS/QNS 锚定）。
- CHARTER：判分规则一字不动，`Pass ⇔ end state == Oracle` 保留。
- ADR 0006：考试仍是冻结 split 文件；LLM 产物必须先冻结再上报，不 live 生成。

## 7. 执行顺序（v1.0 路线，详见 roadmap 报告）

1. **D4 + 公开 realize 缝**：query↔Row 反解改强制；Generator 推导抽为公开 `realize()`；
   Generator 退役归档
2. **完整 FNDDS catalog 重建**：dry-run（`scripts/fndds_dry_run.py`）→ codex 审查 →
   主 agent 裁决 → 构建为**新文件** `catalog-v1.sqlite`（不覆盖旧文件，v0.5 回归不破）
3. **Sampler + Expander + Resolver**：逆向采样与组餐管线（多模型路由，百炼平台）
4. **judge 换模型 + 灰区重验**：deepseek-v4-flash-0731 / qwen3.7-flash-2026-07-15，
   sandwich 1.5× / lasagna 1.2× / omelet 2.0× 三对重跑
5. **试点 20 题**：全链（含 LLM review harness）→ 人审 → 冻结 v1.0-gold.json
6. **扩量 + 复合题配额**（ADR 0012）

## 8. 自然口语与 Multi-Agent Vote 兜底机制（ADR 0019）

为解决 LLM 造题过程中机械照抄 FNDDS 数据库列名（产生 `a cup of burger patty` / `a cup of roast beef` 等生硬表达）的问题，确立以下规则：

1. **松绑逐字照抄（Verbatim）约束**：LLM 提示词不再强制要求“必须逐字使用列表词汇”，让 LLM 专注于写地道餐桌口语（piece/slice/patty/bowl/plate/tbsp 等）。
2. **两级解析架构（Two-Tier Portion Resolution）**：
   - **Tier 1（确定性查表）**：优先由 `resolve_portion` 规则解析器进行零漂移查表；
   - **Tier 2（Multi-Agent 投票兜底）**：当遇到未在规则中的生僻口语量词或分数表达（如 "a slice and a half", "a generous portion"），启动多 Agent 投票，将食物的 FNDDS 参考表输入给模型，由模型判断 `(base_unit, multiplier)` 并计算 `grams = base_unit_grams * multiplier`。
3. **人工审核辅助（Human-in-the-loop）**：
   - 投票结果产出置信度与共识比例（Consensus），呈现在 Review 看板中辅助人工高效裁决；
   - 审核通过的表达同步沉淀进 `portions.py` 和 `react.py` 手册，形成闭环。

