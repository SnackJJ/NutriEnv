# NutriEnv 架构优化提案

配套审查：`reports/architecture-review.md`。
约束与审查相同：本提案每一步都必须是 **可独立落地的保行为重构**，除非该步明确标成「需要后续裁决」。冻结 split、catalog、判分规则、`_SYSTEM_V1_TAIL` 语义一律不动。

零漂移证明（每步完成后都跑，缺一不可）：

```text
.venv/bin/python -m pytest -q          # 现行 271 passed
.venv/bin/python scripts/landing_verify.py   # RESULT: PASS
git diff --stat -- data/splits/v0.5-gold.json data/fdc/catalog.sqlite
# 必须为空
```

`landing_verify` 覆盖：gold 25 食物、old-key 0 漂移、phrase replay、240 题 `validate_draft`、oz/oz_yield 拆分。它是 catalog / 语法 / 造题门的尺子，不是「可选手测」。

排序键：**价值 / 风险**（高价值低风险在前）。同档按「漂移是否已登记」再排。

---

## 目标分层（所有步骤的北极星）

```
nutrienv/
  io/            # 新建叶子：dotenv + HTTP chat。无向上依赖
  world/         # 不变：物理、catalog、portions
  actions/       # 不变：schemas + dispatch
  env/           # 不变
  bench/
    portion_table.py   # 新建：matches_portion_table 唯一实现
    grams_gate.py      # 只依赖 world + io + portion_table；禁止 import harness
    realizations/      # 包：类型 / 表 / assert；禁止懒导入 validator
    generator.py       # 继续拥有 Oracle/Task 与 _*_from_row
    validator.py       # 工厂门；公开 unsatisfiable 谓词
    scorer.py / split.py
  harness/
    protocol.py        # Harness + HarnessView
    react.py           # 手册 + act；dotenv/HTTP 来自 io
    script.py
    runner.py          # 唯一 composition root：可依赖 env + bench + harness
```

谁依赖谁：Harness 不得改 gates / 算术；Bench 不得依赖 Harness；Runner 可以同时看见两边。

---

## 步骤清单

### 步骤 1 — 抽出 `_matches_portion_table` 单点

| | |
|---|---|
| 价值 × 风险 | 高 / 低 |
| 类型 | **纯机械重构** |
| 为何先做 | 已在 `docs/followups-review.md` 登记。白名单是「表内跳过 LLM」的边界；双份是下一次纪律事故的形状。 |

**改什么**

- 新建 `src/nutrienv/bench/portion_table.py`：
  - 公开 `matches_portion_table(food_id, grams, catalog) -> bool`
  - 把 `validator.py:165-175` 原样搬过来（含 `2 * OUNCE_GRAMS` 与 `{0.5,1,1.5,2}`）
- `validator.py`、`grams_gate.py` 删除各自副本，改为导入该函数
- **不要** 把函数放进 `world/`（那是考试作者规则，不是 Env 物理）
- **不要** 让 `grams_gate` 改去 import `validator`（那会把 gate 绑上 draft factory，正是当初复制的原因）

**加什么测试**

- 把 `tests/test_validator_grams.py` 与 `tests/test_grams_gate.py` 里已有用例保留
- 新增 `tests/test_portion_table.py`：同一 catalog 上两处调用方曾经覆盖的例子（steak 160、omelet 55、2 oz = 56.7、非数 / bool 档位忽略）都只测公开函数
- 可选：断言 `validator` 与 `grams_gate` 源码不再定义 `_matches_portion_table`

**零漂移**

- 全量 pytest + landing_verify
- 本步不碰 split / catalog / react 手册

**完成标准**：两处调用同一函数；表白名单行为与 `HEAD` 逐测一致。

---

### 步骤 2 — 叶子模块承接 dotenv + HTTP；切断 bench→harness

| | |
|---|---|
| 价值 × 风险 | 高 / 低 |
| 类型 | **纯机械重构**（搬函数，不改重试集合、不改 payload） |
| 依赖 | 可与步骤 1 并行；建议紧接，避免后续有人把 `grams_gate` 加进 `bench/__init__` 造成环 |

**改什么**

- 新建 `src/nutrienv/io/dotenv.py`：把 `react.py:92-104` `load_dotenv_keys` 原样搬入
- 新建 `src/nutrienv/io/chat.py`：
  - `DEEPSEEK_CHAT_URL`、`DASHSCOPE_CHAT_URL`（从 `react.py:181-185` 搬）
  - `post_chat_completion(url, payload, api_key, timeout, retries=3)`：只做 POST + 读 `choices[0].message.content`
  - **两套 retry 不要合成**：ReAct 继续只捕 `IncompleteRead/URLError/TimeoutError/OSError`；judge 继续捕 `Exception`。用参数 `retry_on=` 区分，默认值分别对准现有两边
- `react.py` 从 `io` 导入；删除本地 dotenv / URL 常量
- `grams_gate.py` 改为 `from nutrienv.io...`，**删除** `from nutrienv.harness.react import ...`
- `scripts/run_react.py`、`gray_zone_probe.py`、`portion_judge_probe.py` 改为从 `io` 或从 `grams_gate` 拿 dotenv（脚本可以依赖 io；不要再依赖 react 只为了读 `.env`）
- `react.py` 的 `__all__` 可暂时继续导出 `load_dotenv_keys` 作薄转出，以免外部脚本漏改。下一步再删转出

**不要做**

- 不要统一 ReAct `temperature=0.0` 与 judge `0.7`
- 不要改手册文本
- 不要引入 httpx / openai SDK（现依赖为空，保持）

**加什么测试**

- `tests/test_react.py` 现有解析 / 手册测试必须绿
- 新增：`load_dotenv_keys` 从新路径导入，行为与旧测试相同（不覆盖已有 env）
- 静态断言：`bench/grams_gate.py` 源码不含 `nutrienv.harness`

**零漂移**：pytest + landing_verify。本步无网络测试；judge 路径继续靠注入 `judge=`。

**完成标准**：`grams_gate` 不再 import harness；ReAct 与 gate 的 HTTP 行为各自与搬迁前一致。

---

### 步骤 3 — judge 采样合同单点；probe 改为调用方

| | |
|---|---|
| 价值 × 风险 | 高 / 低–中 |
| 类型 | 主体 **纯机械**；有一处已登记的非严格等价，对齐时需明示 |
| 依赖 | 步骤 2（共享 HTTP 之后再收采样） |

**改什么**

- 在 `grams_gate.py` 抽出 `sample_verdicts(food, grams, *, judge, k, parse_retries) -> list[str]`（含 `parse_fail`）和 `accept_from_verdicts(verdicts, threshold) -> bool`
- `plausibility_gate` 用这两函数
- `scripts/gray_zone_probe.py` 的 `run_case` 改为调 `sample_verdicts` + `accept_from_verdicts`，自己只负责抽 reason、打印
- `scripts/portion_judge_probe.py` 删除本地 `call_judge` / `JUDGE_SYSTEM` / `parse_verdict`，改调 `grams_gate.call_judge` / `parse_verdict`

**需要明示的行为点（小裁决，不必开大评审）**

1. probe 的 `max_tokens=120` vs gate 的 `512`。灰区已证明 120 会 `finish_reason=length`。建议 probe 跟随 gate 的 512——这是 **有意对齐**，写进该步提交说明。若要求 15/15 脚本字节级不变，则让 probe 继续传 `max_tokens=120`。
2. 裸 `ok`/`suspect`：gate 已接受，probe 尚未。建议 probe 跟随 `parse_verdict`（followups-review 已标非阻断）。

**不要做**

- 不要改 `DEFAULT_K=5` / `DEFAULT_THRESHOLD=0.6`（改阈值是行为变更，且必须先过灰区用例 sandwich 1.5× / lasagna 1.2× / omelet 2.0×）
- 不要改 `JUDGE_SYSTEM` 措辞

**加什么测试**

- 扩展 `tests/test_grams_gate.py`：部分样本 `parse_fail` 后分母是有效 verdict 数；`k` 次调用次数；全 `parse_fail` 拒绝（followups-review 非阻断项 2）
- `gray_zone_probe` 的 catalog guard（piece/qns 三对）保持在脚本里，不必搬进包

**零漂移**：pytest + landing_verify。联网 probe **不是** 落地许可条件（与 followups-review 一致）。

**完成标准**：K / 阈值 / 分母只在 `grams_gate` 定义一次；两脚本是调用方。

---

### 步骤 4 — 公开不可满足谓词，切断 realizations↔validator 环

| | |
|---|---|
| 价值 × 风险 | 中高 / 低 |
| 类型 | **纯机械重构** |
| 依赖 | 无；可与 1–3 并行 |

**改什么**

- 把 `validator._any_pair_unsatisfiable`（及它需要的 `_windows_unsatisfiable` / `_KCAL_RATIO_CAP`）升到公开名，或挪到 `bench/windows.py`
- `realizations.py:2474` 删除函数内 `from nutrienv.bench.validator import _any_pair_unsatisfiable`，改为模块顶导入公开函数
- `tests/test_realizations.py` / `test_validator_gates.py` 已直接 import `_any_pair_unsatisfiable`：改成公开名

**不要做**

- 不要改 Atwater cap、零 kcal 食物阈值（`validator.py:580-605`）。那是造题可达性算术，动了就是行为变更。

**加什么测试**

- 现有不可满足窗口测试改 import 即可
- 断言 `realizations` 模块源码不再出现 `import ... validator`

**零漂移**：pytest + landing_verify（conflict 题依赖此谓词）。

**完成标准**：realizations 不再懒导入 validator；谓词行为不变。

---

### 步骤 5 — `realizations` 拆成包：表与逻辑分离

| | |
|---|---|
| 价值 × 风险 | 高 / 中（体积大，但是再导出可保 import 路径） |
| 类型 | **纯机械重构** |
| 依赖 | 步骤 4（assert_constrain 不再懒导入） |

**改什么**

```
src/nutrienv/bench/realizations.py          → 删除单文件
src/nutrienv/bench/realizations/
  __init__.py     # 再导出今日 __all__ 全部名字（调用方零改）
  types.py        # dataclass、*_key、evaluate_windows
  checks.py       # assert_*、禁配集合（合并 _BANNED_* 为一份）
  tables/
    fuzzy.py
    multi_item.py
    unit_convert.py
    near_synonym.py
    ledger_gap.py
    leftover.py
    update.py
    recommend.py
    constrain.py
    evaluate.py
```

表文件只含 `*_ROWS` 字面量。逻辑不进表文件。

**不要做**

- 不要改任何 Row 字段、seed_id、query、phrase
- 不要把表外置为 JSON（会破坏「Grams are never stored」的 import 时 assert）
- 不要 formatter 重排表（人读的对齐是合同的一部分）
- 不要改 `tests/test_realizations.py` 里 `inspect.getsource(Generator._build_...)` 所依赖的常量名

**加什么测试**

- 现有 `test_realizations.py` 应从 `nutrienv.bench.realizations` 原路径继续绿
- 新增：`from nutrienv.bench.realizations import FUZZY_ROWS, ...` 的公开名清单与旧 `__all__` 一致
- `scripts/landing_verify.py` / `materialize_split.py` 不应需要改 import（仍从包根拿表）

**零漂移**：pytest + landing_verify。phrase replay 必须 178 equal / 0 differ（或与当时 landing 报告同一数字）。

**完成标准**：单文件消失；公开 import 稳定；240 题 validate_draft 仍 0 failing。

---

### 步骤 6 — Generator / split 把冻结路径用的 helper 变成稳定缝

| | |
|---|---|
| 价值 × 风险 | 中 / 中 |
| 类型 | **纯机械**（先升公开，不改算法） |
| 依赖 | 步骤 5 之后更干净，但可独立做 |

**改什么**

- `Generator._*_from_row` 是 materialize 的真实接口。升为公开方法或模块级函数（例如 `bench/materialize.py`），文档写清：「考试路与工厂路共用；`sample()` 仍不是发表数字」
- `split._item` 被 `materialize_split.py:38` 当库用。升为 `split.item_from_payload` 或等价公开名
- `scripts/materialize_split.py` 改为只用公开 API
- `Oracle` 继续留在 `generator.py`（或挪到 `bench/task.py` 并让 `generator` / `oracle` / `scorer` 再导出）。**不要** 在这一步合并 `ledger` 与 `ledger_tail`（见步骤 C）

**加什么测试**

- `test_materialize_gate.py`、`test_realizations.py` 对 `_from_row` 的调用改公开名
- 锁定：同一 Row + live catalog → 与当前冻结 JSON 中对应 id 的 query/oracle 字段一致（可只抽 3–5 个 id 做快照，不必 240 全比；全量仍靠 landing_verify）

**零漂移**：pytest + landing_verify。本步禁止跑 `materialize_split.py v0.5` 写回文件。

**完成标准**：脚本不再 import 私有 `_item` / 未文档化的 `_from_row`；冻结文件哈希不变。

---

### 步骤 7 — 卫生：死代码、`__all__`、GOLD 命名、类型谎言

| | |
|---|---|
| 价值 × 风险 | 中 / 低 |
| 类型 | **纯机械**为主；改 `run_react` 默认 split 除外 |
| 依赖 | 无 |

**改什么（保行为）**

- 删除或折叠零引用：`bench/oracle.py::derive_oracle`、`TIRED_KCAL_DELTA`、`bench/seed.py`（先 grep 确认测试未动态 import）
- `NUTRIENT_KEYS`：删或让 fixture / generator 共用一份
- `world/__init__.py` 补 `ImplausibleQuantity`、`MAX_ITEM_GRAMS`；或从 types `__all__` 收窄并在 dispatch 保持直接 import
- `schemas.__all__` 补 `as_nonempty_str` / `as_dict` / `as_list`
- `react._OPS` 改为 `frozenset(OPS) | FINISH_OPS`，消灭手写名单
- `script.py` 的 `_OUNCE_G` 改为 `OUNCE_GRAMS`（数值相同，行为不变）
- 增加 `EXAM_SPLIT_PATH = data/splits/v0.5-gold.json`；`GOLD_SPLIT_PATH` 保持指向 v0，并在 `split.py` / `bench/README.md` 写明「GOLD = v0 校准，不是现行 240 题」

**不要在本步做**

- 不要把 `scripts/run_react.py` 默认 split 改成 v0.5（那是行为变更：今天默认 40 题）
- 不要删除 `ingest_usda.py` / `build_catalog_from_local.py`，除非另开「清理旧管线」裁决（可能仍被人手动用）
- 不要改 `WorldState.catalog` 运行时形状

**加什么测试**

- 现有 split / runner 测试继续用 `GOLD_SPLIT_PATH`（v0）必须绿
- 新增：`EXAM_SPLIT_PATH` 存在且 `load_split` 得 240 条
- `_OPS` 与 `OPS ∪ FINISH_OPS` 相等

**零漂移**：pytest + landing_verify。

**完成标准**：死符号消失或明确 deprecated；v0 与 v0.5 路径在名字上不再能混。

---

### 步骤 8 — `WorldState.catalog` 类型与最小 lint 基线

| | |
|---|---|
| 价值 × 风险 | 中 / 中 |
| 类型 | 类型是保行为；启用 mypy 严格模式是后续 |
| 依赖 | 步骤 7 |

**改什么**

- `WorldState.catalog` 改为 `Mapping[str, dict]`（`collections.abc`），与 `FoodCatalog` 和夹具 dict 都兼容
- `canonical_id` 探测收成 `world` 上的一个小函数 `canonical_food_id(catalog, food_id)`，替换 `generator` / `split` / `dispatch` 三处 `getattr`
- `pyproject.toml` 加 `[tool.ruff]`：先 `select = ["E", "F"]`，`src` + `tests`；**排除** `src/nutrienv/bench/realizations/**` 的格式规则
- 可选：`mypy` `ignore_missing_imports`、只检查 `nutrienv.env` / `actions` / `world.types` 三块先过

**不要做**

- 不要一次打开 ruff format 全仓库
- 不要为 mypy 引入 `Any` 别名海洋

**加什么测试**

- `canonical_food_id` 对 FoodCatalog 与普通 dict 各一条
- CI 若尚无 workflow，本步只加本地 `dev` extra：`ruff>=0.6`；不强制新 CI

**零漂移**：pytest + landing_verify。ruff 零新错误（基线内）。

---

### 步骤 9 — `materialize_split` 减薄（可选，仍保行为）

| | |
|---|---|
| 价值 × 风险 | 中 / 中 |
| 类型 | **纯机械**，但 719 行脚本，diff 大 |
| 依赖 | 步骤 6 |

**改什么**

- 把 `INCREMENTS` 配方与 `*_from_row` 编排挪到 `bench/materialize.py`
- 脚本只留 argparse + 写文件 + 打印
- `landing_verify` 继续独立（它是验证器，不是生成器）

**不要做**

- 不要改变任何 increment 的 seed 招收名单
- 不要重跑并写回 `v0.5-gold.json`

**加什么测试**：现有 `test_materialize_gate.py` 改为 import 包内函数。

**零漂移**：pytest + landing_verify + 冻结文件不动。

---

## 需要后续裁决（不要混进上面任一步）

下面每条都会碰到硬纪律或改变可观察行为。提案记录方向，**本阶段不做**。

### A. 改 `load_catalog` 静默回退

`catalog_store.py:25-30` 在缺 sqlite 时落到 15 食物夹具。考试路应失败。夹具路径应显式（`load_catalog(fixture=True)` 或 `demo_state()`）。

- 行为变更：无 sqlite 的新克隆，现有「还能跑 smoke」会变成报错。
- 裁决问题：CI / 本地是否保证永远带 `data/fdc/catalog.sqlite`（现在仓库里有）。
- 若做：先加测试钉「缺文件 → FileNotFoundError」，再改实现。

### B. 合并 FNDDS 份量键解析

`build_fdc_catalog._portion_key` / `_overlay_keys` 与 `fndds_dry_run._portion_keys`。动 = catalog 重建。

必须走项目纪律：dry-run 列克数变化 → GPT 审查 → 主 agent 裁决 → 冻结 split 零漂移才落地。**禁止**当机械重构。

### C. 合并 `Oracle.ledger` 与 `ledger_tail`

`generator.py:79-81` 已标兼容。Scorer 两条都判（`scorer.py:53-65`）。改合同会红冻结 JSON 形状与全部 split 测试。

若做：新增量只写 `ledger_tail`；读路径继续认 `ledger`。需要独立 ADR，不是卫生。

### D. `validate_evaluate` 的 query↔Row 反解

`validator.py:659` 按 query 原文找 `EVALUATE_ROWS`。LLM 新 query 会静默跳过。`validate_oracle_grams` 已是正确方向。

把反解改成「必须通过、不依赖 query 相等」会让一批草稿从绿变红。这是门变严，需要造题流水线一起改，不是零漂移重构。

### E. 改 judge 阈值 / K / prompt；改手册

灰区用例（sandwich 1.5× / lasagna 1.2× / omelet 2.0×）是封门前提。手册 `_SYSTEM_V1_TAIL` 语义冻结。任一改动都不是架构清理。

### F. 删除 lookup 工厂 / 旧 USDA 脚本 / CHARTER 对齐

- 删 `Generator._build_lookup`：只影响工厂路，不影响 240 题，但仍是行为变更。
- 删 `ingest_usda.py`：确认无人用旧 JSON 后再做。
- CHARTER 补上 harness、删掉 `query_nutrients`：文档裁决，顺手可做，不要夹在代码 PR 里以免审查面糊掉。

### G. `FoodCatalog` 连接生命周期 / 不全量加载

性能，不是正确性。当前规模不必做。做了要测 search 排序与 alias promote 不变。

---

## 明确不在范围内

- 不改 `data/splits/v0.5-gold.json`、不改 `data/fdc/catalog.sqlite`
- 不改 `Scorer.score` 合同、不改 Pass 定义
- 不改 `_SYSTEM_V1_TAIL` 可解析表达
- 不把 `resolve_portion` 推进 Env Action
- 不把 ScriptHarness 修成第二个 Oracle
- 不引入 LangChain / 新 HTTP SDK / 训练环
- 本阶段不 commit

---

## 建议落地节奏

```
第 1 个 PR：步骤 1（白名单单点）
第 2 个 PR：步骤 2（io 叶子 + 切断 bench→harness）
第 3 个 PR：步骤 3（采样合同；probe 调用方）
第 4 个 PR：步骤 4 + 5（断环 + realizations 拆包）
第 5 个 PR：步骤 6 + 7（公开冻结缝 + 卫生）
第 6 个 PR：步骤 8（类型 + ruff 基线）
可选：     步骤 9（减薄 materialize 脚本）
之后：     只在有明确造题需求时走裁决 A–G
```

每 PR 必须自带：pytest 全绿、landing_verify PASS、冻结文件 `git diff` 为空。审查主力（codex）优先核：步骤 1 白名单集合、步骤 2 不再出现 `bench → harness`、步骤 5 公开名稳定。

---

## 步骤对照表

| # | 一步一句话 | 机械? | 价值 | 风险 |
|---|---|---|---|---|
| 1 | 白名单单点 `matches_portion_table` | 是 | 高 | 低 |
| 2 | `io/` 叶子，切断 bench→harness | 是 | 高 | 低 |
| 3 | judge 采样单点，probe 变调用方 | 基本是 | 高 | 低–中 |
| 4 | 公开 unsatisfiable，断环 | 是 | 中高 | 低 |
| 5 | realizations 拆包再导出 | 是 | 高 | 中 |
| 6 | 冻结路径公开 helper | 是 | 中 | 中 |
| 7 | 死代码 / 命名 / `__all__` | 是 | 中 | 低 |
| 8 | catalog 类型 + ruff 基线 | 是 | 中 | 中 |
| 9 | 减薄 materialize 脚本 | 是 | 中 | 中 |
| A–G | 回退策略、catalog 键、Oracle 字段、门变严… | **否，裁决** | 视项 | 高 |
