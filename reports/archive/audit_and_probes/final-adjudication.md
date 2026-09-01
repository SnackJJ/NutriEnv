# NutriEnv 架构 review + 优化：终审裁决

> **最终结论：允许合并。阻断项 0 个。**

裁决者：claude Opus（深度裁决，本流程唯一一次终审）。
裁决范围：`12d3817..HEAD`（HEAD = `5bd26d6`，11 个 `arch:` commit = 9 主体 + 2 修复）。
方法：**不采信任何一方的自述结论**。所有结论由本次在当前工作树上重新读源码、重新复算哈希、独立故障注入、重新执行测试与 landing verifier 得出。grok 报告、codex 两轮报告、主 agent 提案均只作为「待验证的主张」处理。

---

## 0. 阅读的五份文档

| 文档 | 作者 | 本次采用方式 |
|---|---|---|
| `reports/architecture-review.md` | grok | 主张来源，逐条复核；其 §5.1「保行为做法：加 `EXAM_SPLIT_PATH`，不改默认」是决策点 1 的被覆盖方 |
| `reports/architecture-review-independent.md` | codex | 主张来源；其 F1/F2「默认公开 gold split 不是 240 题、split↔catalog 只写不验」是决策点 1/2 的动因 |
| `reports/architecture-proposal.md` | 主 agent | 步骤 1–9 与延后项 A–G 的范围界定，用于核对「延后项未混入」 |
| `reports/implementation-review.md`（含复审节） | codex | 两轮实施复核；本次逐条重跑其关键断言 |
| `docs/agent-orchestration.md` | 固化约定 | 分工与纪律基线（claude 只在收尾用一次、catalog 重建须过 dry-run+审查+裁决） |

两轨审查的分歧点只有一个实质项：**默认入口是否改指 240 题**。grok 判为「行为变更，不要在卫生步骤里做」，codex 判为「发布物身份错误，必须封」。主 agent 裁决站在 codex 一侧。见 §3.1。

---

## 1. 硬纪律抽查（违反 = 一票否决）

全部**通过**。逐条独立证据：

| # | 纪律 | 裁决 | 独立证据 |
|---|---|---|---|
| 1 | `data/` 零漂移 | **通过** | `git diff 12d3817..HEAD -- data/` = `data/splits/v0.5-gold.json \| 2 +-`，唯一改动行是 `catalog_sha256` |
| 2 | v0.1–v0.4 与 catalog.sqlite 零 diff | **通过** | 逐字节断言 old/HEAD bytes 相等：v0 38,899 / v0.1 71,272 / v0.2 113,793 / v0.3 166,340 / v0.4 208,211 / catalog.sqlite 5,771,264 bytes，全部 `equal: True` |
| 3 | v0.5 items 逐字节相同 | **通过** | 文件总长 old/new 均 242,220 bytes；自 `"items"` 起的原始切片 241,304 bytes 逐字节相等，SHA-256 `51d107bb…`；JSON 解析后 240 项 `==` 成立；键集合相同，除 `catalog_sha256` 外无字段差异 |
| 4 | `Scorer.score` 合同不动 | **通过** | `git diff 12d3817..HEAD -- src/nutrienv/bench/scorer.py` **为空** |
| 5 | `_SYSTEM_V1_TAIL` 语义不动 | **通过** | AST 取常量复算：old/new 长度均 1,096，SHA-256 均 `c67b0232…`。react.py 的 diff 显示该常量**未被触碰**（连位置都没移动），改动只在 import 段、`_OPS` 与 `_complete` |
| 6 | `resolve_portion` 克数不动 | **通过** | `git diff 12d3817..HEAD -- src/nutrienv/world/portions.py` **为空** |
| 7 | judge 采样合同不动 | **通过** | AST 复算：`DEFAULT_K=5`、`DEFAULT_THRESHOLD=0.6`、`TEMPERATURE=0.7`、`MAX_TOKENS=512`、`MODEL`（17 字节）、`JUDGE_SYSTEM`（688 字节，SHA-256 `9aab633b…`）old/new 全部相等 |
| 8 | 克数锚点 = 表值/QNS，LLM 只是候选 | **通过** | 白名单单点后仍是「表内先过，off-table 才问 judge」：`plausibility_gate` 第一步就是 `matches_portion_table`；`_matches_portion_table` 私有副本在 `src/`、`scripts/`、`tests/` 全仓 0 命中 |

附加的独立零漂移复算（超出要求，用于封住「拆包/搬函数」这类高体积改动）：

- **realizations 拆包数据**：以 dataclass `repr()` 逐行比对新旧十张表，`CONSTRAIN_ROWS 42 / EVALUATE_ROWS 55 / FUZZY_ROWS 34 / LEDGER_GAP_ROWS 5 / LEFTOVER_ROWS 27 / MULTI_ITEM_LOG_ROWS 9 / NEAR_SYNONYM_ROWS 7 / RECOMMEND_ROWS 40 / UNIT_CONVERT_ROWS 8 / UPDATE_ROWS 40`，每张表逐行 SHA-256 全等；`__all__` 38 名排序后完全相等，逐名类型（`kinds`）亦相等，无新增/丢失。方法：`git archive 12d3817` 展开旧树，两个子进程分别以旧/新 `PYTHONPATH` 导出后比对。
- **unsatisfiable 谓词搬迁**：`bench/windows.py` 的 `windows_unsatisfiable` / `any_pair_unsatisfiable` 与 `12d3817` 的 `validator._windows_unsatisfiable` / `_any_pair_unsatisfiable` **逐行相同**（含零 kcal 食物 1.0 g 阈值与 Atwater cap 注释）；`KCAL_RATIO_CAP` 值相同；`windows._tag_set` 与 `validator._tag_set` 实现同一行 `set(normalize_tags(list(values or [])))`。这是 constrain 家族可达性算术，逐行等价即行为等价。
- **`canonical_food_id` 收编**：新公开函数与 `split._canonical_food_id`（旧）逐行相同（只交换参数顺序）；`Generator._food_id` 旧实现同样含 `food_id in s0.catalog` 前置检查，等价；`dispatch._resolve_food` 旧实现在成员检查**之后**才 canonical，新实现多做一次已成立的成员检查，结果相同。三处语义等价。
- **分层断环**：`src/nutrienv/bench/` 中 `nutrienv.harness` 0 命中；`src/nutrienv/bench/realizations/` 中 `validator` 0 命中；`src/nutrienv/io/` 无任何 `nutrienv.*` 向上 import；全 `src/nutrienv/` 中 import harness 的模块数为 0（harness 内部相对 import 除外）。

---

## 2. 独立验证

在当前工作树亲自执行，不复用任何一方的输出：

```
.venv/bin/python -m pytest -q
→ 296 passed in 135.42s   (exit 0)

.venv/bin/python scripts/landing_verify.py
→ gold foods: 25
  old-key drifts: 0
  phrase replay: 178 equal, 0 differ, 145 items unmatched/no phrase
  validate_draft: 240 items, 0 failing
  oz/oz_yield conflicts in FNDDS: 42; unsplitting: 0
  RESULT: PASS
```

与 codex 复审报告的 296 / PASS 一致。工作树已跟踪文件干净（仅 4 个 untracked report，含本文件的前置报告）。

---

## 3. 三个关键决策点

### 3.1 默认入口改指 240 题考试 —— **允许**

主 agent 用 codex F1 覆盖了 grok「不改默认」的建议。裁决：**成立**。

**与项目契约一致。** `CLAUDE.md` 硬纪律第 5 条与 `docs/llm-generated-exam-data.md` 都把考试定义为冻结 split v0.5-gold 240 题。改动前 `load_split()` 裸默认与 `run_react --split` 默认都指向 40 题 v0 校准集，而 `tests/test_split.py` 反而把这个分叉钉死。这不是命名问题，是**发布物身份错误**：任何人调公开默认入口都会在无警告的情况下评 40 题。grok 的顾虑（「改默认 = 行为变更」）事实正确，但它把「行为变更」当成了不可做，而契约恰恰要求这个变更。codex 的定性更贴合契约，主 agent 的覆盖正确。

**回归面已实测封住。** 本次逐点枚举调用图：

- 全仓**只有一个**裸 `load_split()` 调用点，即新增的 `tests/test_split.py:18`（钉 240）。生产代码、脚本、其余 54 处 `load_split(...)` 全部显式传路径 → 默认值变更的实际爆破半径为零。
- `GOLD_SPLIT_PATH` 仍指 v0 且加了 `# v0 calibration set, not the published 240-item exam.` 注释；`test_gold_split_exists_and_loads` 仍钉 38–42 题；`test_runner.py` / `test_id_normalize.py` / `test_v01_split.py` 共 30+ 处仍绑 v0 且全绿 → v0 校准路径未被破坏。
- 严格性落在正确位置：`run_react.main` 在**构造 `ReActHarness` 之前**完成 `load_exam()`，`--limit` 复用同一批已严格加载的 Task；显式 `--split` 仍走宽松 `load_split`（保留历史/custom split 能力）。
- 测试非自证：`tests/test_exam_entry.py:141-172` 把 `EXAM_SPLIT_PATH` 指到坏 SHA manifest 并用哨兵替换 `ReActHarness`，断言 `ValueError: catalog sha256 mismatch` 且哨兵**从未被调用**（`created == []`）。旧实现（默认走宽松 loader）会让这两条测试失败。`test_load_exam_attaches_the_validated_catalog` 用独立 tiny sqlite 做正负双向身份断言（`probe_only_food` 在、`milk_whole` 不在、search 命中/不命中）。这不是 happy-path。

**引入回归：未发现。** 296 项全绿 + landing PASS + 上述调用图枚举。

**条件（非阻断，登记为 O6/O8）**：`split.py` 现在同时存在「`GOLD_SPLIT_PATH` = v0」与「`load_split()` 裸默认 = v0.5」两种默认语义，同模块内两个「默认」不再指同一文件。建议在 `bench/README.md` 或 `load_split` docstring 写明一句，避免下一个人把 `load_split()` 读成 `load_split(GOLD_SPLIT_PATH)`。

### 3.2 A3 改写冻结 split 的 `catalog_sha256` —— **允许**（元数据修正，证明充分）

这是本次最需要独立取证的一项：直接编辑冻结考试文件，形式上触及「考试是冻结 split 文件」的纪律。**证明链本次完整独立重建**：

| 事实 | 独立证据 |
|---|---|
| 旧值 `e1ffbb1a…` = FNDDS 安全 overlay 重建**之前**的 catalog | `git show 2c639e8~1:data/fdc/catalog.sqlite \| sha256sum` = `e1ffbb1a…` |
| 新值 `ff2f2632…` = 重建**之后**的 catalog = 当前磁盘文件 | `git show 2c639e8:data/fdc/catalog.sqlite \| sha256sum` = `ff2f2632…`；`sha256(data/fdc/catalog.sqlite)` = `ff2f2632…` |
| v0.5 冻结于 catalog 重建**之前** | v0.5 freeze = `8be5938`（2026-08-15），catalog 重建 = `2c639e8`（2026-08-16） |
| 重建自称零漂移且已过项目纪律 | commit `2c639e8` = "Land FNDDS safe-overlay catalog rebuild (zero drift on frozen split)"，其 dry-run/审查/裁决产物见 `reports/dry-run-*`、`b7dc8a2` |
| catalog 在本批范围内未被动 | 12d3817..HEAD 逐字节相等，5,771,264 bytes |
| 题目本体未被动 | items 241,304 bytes 逐字节相等 |
| 新 catalog 下 Oracle 仍可复现 | landing_verify：240 items / 0 failing、178 phrase equal / 0 differ、old-key drifts 0 |

**结论**：`e1ffbb1a…` 是 2026-08-16 catalog 重建时**漏改**留下的过期字段——它指向一个磁盘上已不存在的 artifact。A3 不是「改数据迁就代码」，而是把 manifest 从「记录一个不存在的文件」修正为「记录考试实际运行的那个文件」。在 A2 把该字段升级为运行时 fail-closed 门之后，不修它的结果是默认考试入口**永远无法启动**。改法最小（单字段、items 逐字节不变），证据充分。**允许。**

**条件（非阻断，登记为 O6）**：v0.1–v0.4 仍记 `e1ffbb1a…`。于是同名字段现在有两种语义——父 split 记「冻结当时的 catalog」，v0.5 记「当前已验证的 catalog」；同时 `tests/test_v05_split.py` 把原有的「子 split 继承父 sha」不变量换成了「等于磁盘 sha」，父子链一致性已无任何测试守。这不影响运行（`load_exam` 只认 `version == "v0.5-gold"`，历史 split 走不校验的 `load_split`），但应写进 ADR 或 `bench/README.md`，否则下一次 catalog 重建会重犯同一个漏改。

### 3.3 probe `max_tokens` 120→512 对齐 + 分母收敛 —— **允许**（有意且无害）

- **有意**：`reports/architecture-proposal.md` 步骤 3「需要明示的行为点」第 1 条已预先书面裁决（灰区已实证 120 会 `finish_reason=length` 截断，建议跟随 gate 的 512 并写进提交说明）；第 2 条同样预先明示 probe 跟随 gate 的 `parse_verdict`（接受裸 `ok`/`suspect`）。两项都不是实施中临时起意。
- **无害**：`portion_judge_probe.py` 是离线实验脚本，不在造题/冻结调用图内（`materialize_split` 冻结路径只调 `validate_oracle_grams`）。分母从「全部 K 次（含 `parse_fail`）」收敛为「有效 verdict」是**向 gate 与 gray-zone 对齐**，方向是收紧一致性，不放宽任何门。
- **gate 侧一字未改**：`DEFAULT_K=5`、`DEFAULT_THRESHOLD=0.6`、`JUDGE_SYSTEM`（688 字节 SHA 相同）、`TEMPERATURE=0.7`、`MAX_TOKENS=512` 全部字节级复算相等；`accept_from_verdicts` 的「`parse_fail` 不入分母、无有效 verdict 即拒」与旧 `plausibility_gate` 内联逻辑逐行等价；`sample_verdicts` 的 K 次循环与旧循环逐行等价。灰区三对用例（sandwich 1.52× / lasagna 1.21× / omelet 2.00×）由 gray_zone_probe 的 catalog guard 保持，脚本仍可编译运行。

**允许。** 附一处需登记的副作用见 O5（采样节奏）。

---

## 4. 实施与裁决范围的一致性

逐项独立复核 A1–A3 / B1–B5 / C，全部**已实现**（证据分散在 §1–§3，不重复）。额外确认两点：

**延后项 A–G 确实未混入**（`reports/architecture-proposal.md`「需要后续裁决」全项实测）：

| 延后项 | 实测状态 |
|---|---|
| A 改 `load_catalog` 静默回退 | 未动：`catalog_store.py:29` 仍 `FoodCatalog.from_mapping(demo_catalog())` |
| B 合并 FNDDS 份量键 | 未动：`build_fdc_catalog._portion_key` / `_overlay_keys` / `fndds_dry_run._portion_keys` 三份仍在 |
| C 合并 `Oracle.ledger` 与 `ledger_tail` | 未动：`generator.py:79,82` 两字段并存 |
| D `validate_evaluate` query↔Row 反解 | 未动：`validator.py:398,471,571` 仍 `item.query == task.query` |
| E 改 judge 阈值 / prompt / 手册 | 未动：见 §1 第 5、7 条 |
| F 删 lookup 工厂 / 旧 USDA 脚本 | 未动：`generator._build_lookup` 在；`scripts/ingest_usda.py`、`build_catalog_from_local.py` 在 |
| G FoodCatalog 连接生命周期 | 未动 |

**提案步骤 6 / 8-lint / 9 未实施**，与本批裁决范围（A/B/C）一致，但需显式登记为待办（O8）：`materialize_split.py:38` 仍 `from nutrienv.bench.split import _item`（步骤 6 未做）；`pyproject.toml` 零 diff、无 ruff/mypy（步骤 8 的 lint 基线未做，只做了类型部分）；`materialize_split.py` 未减薄（步骤 9 未做）。

**未登记的行为变更审查**：逐个 diff 走完 `actions/`、`world/`、`bench/`、`harness/`、`scripts/`、`tests/`，未发现范围外的隐藏行为变更。唯一一处「文档缺口而非行为漂移」的是 dotenv：`run_react.py` 删掉了两条仓库外硬编码路径（`/home/jzq/Projects/NutriBuddy/.env.local`、`/home/jzq/Projects/NutriMind/.env`），改由环境变量 `NUTRIENV_DOTENV` 提供。本次实测**本机运行不受影响**——仓库 `.env.local` 已同时含 `DEEPSEEK_API_KEY` 与 `DASHSCOPE_API_KEY`，且 `load_dotenv_keys` 不覆盖已存在的键（那两条仓外路径本来只是后备）。但 `NUTRIENV_DOTENV` 在 `--help`、README、docs 中零记载（O7）。

---

## 5. 非阻断观察登记

均**不阻断合并**。按建议优先级排序。

### O1（建议优先修，一行）`load_exam` 的「校验即装载」契约有残留缺口

`load_exam` 校验 manifest `catalog` 字段所指文件的 SHA-256 后调用 `load_catalog(catalog_path)`，而 `load_catalog` 只在 `suffix == ".sqlite"` 时真装载，否则**静默**回退 15 食物夹具。因此当 manifest 的 catalog 字段指向一个 SHA 正确但后缀非 `.sqlite` 的文件时，`load_exam` 会哈希校验通过、装载夹具、返回 240 题且**不报错**。

本次实测（把真 catalog 原样复制为 `catalog.db`，SHA 与 manifest 完全一致）：

```
sha matches live: True
load_exam succeeded, tasks: 240
catalog size: 15          ← 夹具，不是 13k 行的 USDA catalog
has USDA id 171477: False
has fixture-only key peanut_butter: True
```

**这不重开 codex 的 S-B2**：S-B2 的缺陷用**合法 manifest** 即可触发（校验 A 装载固定默认 B），已真正修好；本项需要**篡改冻结 manifest** 才可达，且触及的是既存的 `load_catalog` 静默回退（延后项 A）。`load_exam` 的 docstring 声明「The verified catalog file is the one attached to every Task」目前略强于实际交付。

建议：`load_exam` 在哈希校验旁加一句后缀断言（或对返回 catalog 做规模/来源 sanity 断言），配一条注入测试；延后项 A 落地后本项自动完全关闭。

### O2 默认 ReAct 路双重装载（TOCTOU 面）

为满足「构造 harness 前失败关闭」，`scripts/run_react.py:103-125` 先 `load_exam()` 一次，`harness/runner.py:86` 随后再 `load_exam()` 一次。两次都走严格入口，不重开阻断；实测单次 `load_exam` 仅 0.19 s（240 题），成本可忽略，问题是重复与两次读盘之间的 TOCTOU 窗口。建议未来给 `run_split` 一个接受「已加载 tasks」的窄接口消除。

### O3 `grams_gate` 注释已过期

- `src/nutrienv/bench/grams_gate.py:45-46`：「Duplicated here because that script is not a library and is outside this change's file list」——`portion_judge_probe` 现已导入共享合同，本地副本已删，该注释描述的事实不再成立。
- 模块 docstring 第 5–6 行只提 `gray_zone_probe`，现在两个 probe 都是调用方。

纯文字卫生，但它正是「注释与代码漂移」的教科书形状，建议随手清。

### O4 `validator.py` 空行丢失（PEP8 E302）

B4 删除 `_KCAL_RATIO_CAP` 时连带吃掉了两个空行：现在 `_CLAUSE_SPLIT = re.compile(...)` 的收尾 `)` 与 `def semantic_key` 之间是**零空行**（`src/nutrienv/bench/validator.py:53-54`）。两轨审查都未捕获。建议补回两个空行——同时说明为什么 O8 的 ruff 基线值得尽早落地。

### O5 `portion_judge_probe` 采样节奏改变 + 残留 sleep

原实现在 K 次 judge 调用**之间**各 `sleep(0.15)`；现在 K 次由 `sample_verdicts` 连续发出（其 `retry_sleep` 只作用于 parse 重试），而那句 `time.sleep(0.15)` 被搬进了调用完成后的 reason 提取循环，成为无效残留。只影响离线 probe 的限速节奏（并且现在与 gray_zone_probe 一致），不影响任何 gate。建议删掉残留 sleep，或把 pacing 作为 `sample_verdicts` 的显式参数。

### O6 catalog_sha256 字段的双语义 + 父子链不变量失守

见 §3.2 的条件段。建议：写一句进 `bench/README.md` 或新开 ADR，说明「v0.1–v0.4 记冻结当时的 catalog（`e1ffbb1a…`，2026-08-16 重建前）；v0.5 记当前已验证的 catalog（`ff2f2632…`）；今后 catalog 重建必须同步更新在用 split 的该字段」。

### O7 `NUTRIENV_DOTENV` 未文档化

新的 dotenv 注入点只存在于 `scripts/run_react.py:85`，`--help` 文本、README、docs 均无记载。建议加进 `--split` 同级的 help 或 README 一行。

### O8 提案步骤 6 / 8-lint / 9 应显式挂待办

见 §4。这三项**未实施**是本批范围裁决的结果，不是遗漏；但它们目前只活在提案文档里，建议登记到 followups，避免后续被误读为「架构优化已全部完成」。

### O9（既存，非本批引入）`qns_gap_audit.py` 的名字陷阱

`scripts/qns_gap_audit.py:19` 定义脚本局部 `GOLD_SPLIT_PATH = ROOT/"data/splits/v0.5-gold.json"`，与包级 `GOLD_SPLIT_PATH`（v0）同名反义。该脚本本批零 diff，是既存债；但既然 A1 的目的正是消灭 v0/v0.5 的名字混淆，顺手改名为 `EXAM_SPLIT_PATH` 才算把这条纪律收干净。

---

## 6. 逐条裁决汇总

| 裁决对象 | 结论 |
|---|---|
| 硬纪律 1–8（data 零漂移 / 冻结字节 / Scorer / 手册 / 克数 / judge 合同 / 锚点） | **全部允许**，无一违反 |
| 独立验证（pytest 296 passed、landing_verify PASS） | **通过**，本次亲自复现 |
| 决策点 1：默认入口 = 240 题考试 | **允许**（契约一致；回归面实测为零；fail-closed 测试非自证）。条件：登记 O6 的默认语义分叉说明 |
| 决策点 2：A3 改写 v0.5 `catalog_sha256` | **允许**（元数据修正而非数据迁就；证明链独立重建完整）。条件：登记 O6 的双语义与父子链说明 |
| 决策点 3：probe `max_tokens` 120→512 + 分母收敛 | **允许**（提案已预先书面明示；probe 非 gate；gate 侧字节未变）。附 O5 |
| A1–A3 / B1–B5 / C 实施完整性 | **成立**，逐项独立复核 |
| 延后项 A–G 未混入 | **确认**，七项逐条实测未动 |
| 未登记的行为变更 | **未发现**；dotenv 一处为文档缺口（O7），实测不影响本机运行 |
| 非阻断观察 | 登记 O1–O9，其中 O1 建议优先修（一行 + 一测），O4 建议随手补 |

**阻断项：0 个。**

---

## 最终结论

**允许合并。** 冻结数据、判分合同、agent 手册与克数锚点在 `12d3817..HEAD` 全部字节级未动，A3 是有完整证据链的元数据修正而非数据改写，两个曾被 codex 判为阻断的严格入口缺口经本次独立故障注入确认已真正关闭，pytest 296 passed 与 landing_verify PASS 均由本次亲自复现；余下 9 项均为非阻断观察，其中 O1（`load_exam` 后缀缺口）与 O4（PEP8 空行）建议在合并后的第一个小 PR 里清掉。
