# NutriEnv 独立架构审查

审查基线：`HEAD=12d3817`，2026-08-17。审查对象为 `src/nutrienv/`、`scripts/`、`tests/`、`pyproject.toml`，以及用于确认项目契约的 `AGENTS.md`、`docs/llm-generated-exam-data.md` 和代码内 README。结论来自本次对代码的独立阅读；未把已有审查报告当作证据或结论来源。本阶段未改动源码、数据或测试。

## 结论摘要

核心 world → actions → env 的方向总体干净：actions 只依赖 world，env 只依赖 actions/world；Scorer 也确实只比较结束状态与 Oracle，没有在 harness 中复制评分规则。当前最危险的架构问题发生在冻结考试的入口：代码公开的 `GOLD_SPLIT_PATH` 和默认 ReAct 命令仍指向 40 题 `v0-gold.json`，而项目契约认定的考试是 240 题 `v0.5-gold.json`；同时 split 中虽然写有 `catalog_sha256`，运行时 loader 却完全不校验它。也就是说，“冻结 split + 冻结 catalog”目前不是一个由代码强制绑定的发布物。

第二组问题是 LLM 基础设施没有独立 seam：bench 的 gate 反向借用 harness 的 URL 与 dotenv，ReAct 和 judge 又各自实现 urllib/retry/响应拆包。第三组问题是造题域模型过度集中在 `generator.py` / `realizations.py`，validator 通过 query 原文反查表行、materializer 大量调用私有 helper，造成接口浅、调用者知识多、未来 LLM 候选接入容易绕过检查。

严重度定义：

- **高**：可让实际考试对象、Oracle 锚点或冻结数据在正常入口中发生静默偏差，或让关键 gate 形同未接入。
- **中**：当前测试下通常不改变结果，但使规则存在两份以上实现、形成循环依赖或显著放大后续改动风险。
- **低**：主要影响可维护性、可发现性、打包与静态检查，短期不改变考试语义。

## 1. 依赖方向与分层

### F1（高）：默认公开的 “gold split” 不是项目声明的 240 题考试

证据：

- `src/nutrienv/bench/split.py:17-18` 把 `GOLD_SPLIT_PATH` 固定为 `data/splits/v0-gold.json`。
- `src/nutrienv/bench/split.py:21-31` 的无参 `load_split()` 使用该常量。
- `scripts/run_react.py:29-32` 默认同样使用该常量，帮助文本还明确写着 `v0-gold.json`。
- `tests/test_split.py:17-20` 将这个默认文件锁定为 38–42 题，实际是在保护 40 题校准集。
- `tests/test_v05_split.py:20-30` 另行证明 `v0.5-gold.json` 才有 240 题及目标 family 配额，但没有断言它就是 `GOLD_SPLIT_PATH`。

理由：调用公开接口或默认 CLI 的人会在没有警告的情况下评测 40 题，而不是 charter 所称的 240 题。manifest 只记录传入路径（`harness/runner.py:132-150`），不会指出这只是 calibration。测试反而固化了这种分叉。这是发布物身份错误，不只是命名问题。

### F2（高）：split 与 catalog 的冻结关系只被写入，未在运行时验证

证据：

- `scripts/materialize_split.py:700-706` 在 split 中写入 catalog 路径和 SHA-256。
- `src/nutrienv/bench/split.py:21-31` 读取 JSON 后只取 `items`，随后调用 `load_catalog()`；没有读取或比较 `catalog` / `catalog_sha256`。
- `src/nutrienv/world/catalog_store.py:19-30` 在目标不存在或不是 `.sqlite` 时静默退回 15-food demo fixture。
- `tests/test_catalog.py:16-27` 允许无快照时退回 fixture；仅当文件存在才检查 USDA 规模。
- `tests/test_v05_split.py:23-25` 只检查相邻 split 继承相同 hash，没有检查当前磁盘 catalog 的 hash；review sheet 自己另做校验（`scripts/build_review_sheet.py:491-500`），说明该校验尚未成为 loader 的接口不变量。

理由：冻结题目的 Oracle 克数依赖 catalog。当前可替换 catalog、删掉 catalog，甚至传入一个非 sqlite 路径而不在 loader seam 失败；最坏情况下直到某些 food id 被访问才报错，或在小 fixture 上产生不同工厂行为。“文件都冻结”不等于“二者绑定冻结”。考试模式必须 fail closed；demo fallback 只能是显式开发模式。

### F3（中）：bench → harness 的反向依赖破坏了单向层次，LLM transport/config 没有自己的 seam

证据：

- 正常的顶层组合方向是 `harness/runner.py:10-15` 依赖 bench、env 和 harness protocol；这符合“runner 是 Env/Harness/Model 汇合点”的声明。
- 反向边出现在 `bench/grams_gate.py:19`：bench 从 `harness/react.py` 借 `DEEPSEEK_CHAT_URL` 与 `load_dotenv_keys`。
- `harness/react.py:14-15` 又从 runner 借 `DEFAULT_MAX_STEPS`，让具体 ReAct adapter 依赖执行编排模块。
- `harness/react.py:181-185` 的 endpoint 常量并未列入该模块 `__all__`（`react.py:17-24`），bench 和 probe 实际依赖的是未公开实现细节。
- `bench/grams_gate.py:93-123` 在领域 gate 内直接读取环境变量、加载 dotenv、构造 HTTP 请求和重试，默认依赖不是注入进来的。

理由：runner 向下依赖 bench 本身不是问题；问题是 bench 又向上依赖一个具体 presentation adapter，于是依赖方向变成双向。删除 harness 后，bench 的 plausibility gate 也不能导入。LLM 是 true-external dependency，应有一个小的 client port 和生产 HTTP adapter；bench 只拥有 prompt、采样与接受策略，harness 只拥有消息呈现，dotenv 只应由 CLI composition root 加载。

### F4（中）：Harness interface 没有完整表达 runner 实际需要的生命周期，且混入非 Env action

证据：

- `harness/protocol.py:27-36` 只声明 `act()` 与 `clone()`，没有声明 runner 实际探测并调用的 `reset()`。
- `harness/runner.py:183-189` 通过 `getattr`/`callable` 隐式发现 `reset`；并发时则依赖 `clone()` 返回 episode-local 实例。
- protocol 声称 harness “emit a single legal Env action”（`protocol.py:27-31`），但 ReAct 手册包含 `finish`（`react.py:26-37`），`finish` 不在 Env 的 action schemas（`actions/schemas.py:14-26`），由 runner 在 `runner.py:240-253` 截获。
- `HarnessView` 的 Oracle/S0 隔离是有效设计：`protocol.py:16-24` 提供窄 view，`runner.py:158-167` 构造它，`tests/test_runner.py:61-103` 覆盖默认不泄漏与显式诊断泄漏。

理由：当前 seam 的安全属性主要靠 runner 的 duck typing 和约定，而不是接口本身。新增 harness 很容易不知道 reset 是 episode 隔离所必需，或误以为所有返回值都会交给 Env。建议把 `reset(view)`、`clone()`、`act()` 和 runner control action 的语义写进同一 interface；保留现有 `HarnessView` 这一正确的窄接口。

## 2. 重复代码与漂移风险

### F5（高）：portion anchor 白名单有两份生产实现，且它决定 Oracle 是否可冻结

证据：

- `bench/validator.py:165-175` 定义 `_matches_portion_table`。
- `bench/grams_gate.py:62-77` 逐行复制相同候选集合，并在 docstring 中承认复制来源。
- 两者都硬编码 `{0.5, 1.0, 1.5, 2.0}` 倍表值和固定 `2 oz`，所以新增合法倍数或改变 ounce 规则必须同步修改两处。
- `validate_oracle_grams()` 在 `validator.py:178-203` 使用第一份；LLM whitelist-first gate 在 `grams_gate.py:160-191` 使用第二份。
- 冻结入口 `materialize_split.py:663-672` 调用 validator 版本，因此两份漂移时可能出现“冻结 gate 拒绝、judge gate 直通”或相反结论。

理由：这是同一业务事实的双实现，而且位于 Oracle 锚点的安全路径。应抽成 bench 内的纯函数/小模块，返回结构化 anchor（key、factor、grams）而非只返回 bool，使 validator、review sheet 和 judge gate 共用一份事实解释。

### F6（中）：LLM HTTP、prompt、解析、采样/阈值分散，已经出现语义差异

证据：

- ReAct HTTP：`harness/react.py:272-298`；judge HTTP：`bench/grams_gate.py:93-123`；旧 probe 又复制一份：`scripts/portion_judge_probe.py:67-100`。
- judge prompt 同时存在于 `grams_gate.py:43-57` 和 `portion_judge_probe.py:33-45`；前者注释明确承认复制。
- `grams_gate.py:126-148` 负责 parse retry，`grams_gate.py:184-191` 负责 K 次采样和阈值。
- `scripts/gray_zone_probe.py:145-169` 又维护 K 次采样、parse-fail 过滤和阈值；其 `K=5/threshold=0.6` 在 `gray_zone_probe.py:41-43` 再次声明。
- 旧 probe 用全部回复作分母（`portion_judge_probe.py:107-121`），而 gate/gray-zone 只用可解析回复作分母（`grams_gate.py:189-191`、`gray_zone_probe.py:161-168`）；旧 probe 的 `max_tokens=120`（`portion_judge_probe.py:67-76`）与 gate 的 512（`grams_gate.py:37-41`）也已漂移。
- ReAct 与 judge 的异常策略不同：ReAct 只重试列举的网络异常（`react.py:289-298`），judge 捕获所有 Exception（`grams_gate.py:114-123`），因此代码错误也会被当作网络噪声重试。

理由：HTTP transport 可以共享，但 ReAct action parser 与 judge verdict parser 是不同领域逻辑，不应强行合并。真正应集中的是 OpenAI-compatible request/response/retry adapter，以及一次完整的 judge aggregation。probe 应调用生产 aggregation 并只负责定义 case/reporting。

### F7（中）：dotenv 只有一份 parser，却在错误层级重复触发并带有机器路径

证据：

- dotenv parser 位于 presentation 模块 `harness/react.py:92-103`，并直接修改 process-global `os.environ`。
- `grams_gate.py:93-110` 每次默认 judge 请求前都加载仓库 `.env.local`。
- `portion_judge_probe.py:24-26`、`gray_zone_probe.py:33-36`、`run_react.py:76-82` 各自再次加载。
- `run_react.py:78-82` 还硬编码两个仓库外绝对路径 `/home/jzq/Projects/NutriBuddy/...` 与 `/home/jzq/Projects/NutriMind/...`。

理由：问题不是 dotenv parser 有多份，而是配置发现策略散落且库函数产生全局副作用。wheel 用户、CI 和其他开发机无法复现这些路径。CLI 应显式加载选定文件并把 key/base URL/client 注入模块；库代码只验证缺失配置，不自行搜文件。

### F8（中）：`plausibility_gate` 当前没有进入造题或冻结调用图

证据：

- `plausibility_gate` 定义在 `grams_gate.py:160-191`。
- 仓库内调用只见 `tests/test_grams_gate.py:28-74`；`materialize_split.py` 的冻结路径只调用 `validate_oracle_grams`（`materialize_split.py:663-672`）。
- `tests/test_grams_gate.py` 对 table bypass、K、threshold 和 parse retry 有单元覆盖，但没有一项从候选生成一路走到 `freeze_split()` 并证明 judge gate 被执行。

理由：现有 v0.5 不因此改变，但模块名称容易让维护者误以为 gate 已封入流水线。按项目纪律，灰区验收完成前不应偷偷接入；完成后则必须由一个明确的 candidate-admission interface 调用，不能停留在测试孤岛。

## 3. 模块职责与 seam

### F9（高）：validator 仍通过 query 原文反查 realization row，独立候选会绕过部分强检查

证据：

- validator 直接导入具体表 `EVALUATE_ROWS, UPDATE_ROWS`（`validator.py:15-16`）。
- update 校验分别在 `validator.py:417-425`、`validator.py:486-518` 通过 `item.query == task.query` 找 row；找不到时部分声明式校验无法执行。
- evaluate 校验在 `validator.py:647-670` 同样只在原文命中 row 时，才逐项用 row phrase 反解 grams。
- 好的一面是 `validate_oracle_grams()` 已直接读 Oracle，不依赖 query-row 命中（`validator.py:178-203`），`tests/test_validator_grams.py:21-27` 专门锁住这一点。

理由：LLM paraphrase 的核心就是 query 文本变化；以 query 当外键会使恰好需要最严格审查的新候选进入较弱路径。Task 应携带稳定 `realization_id` 或结构化 intent/anchor specification，validator 对该结构验证，query 只做 entailment/evidence 检查。不能把 LLM 文本本身当作 join key。

### F10（中）：Task/Oracle 被放在 Generator 实现中，造成 bench 内多模块依赖具体工厂

证据：

- `Oracle`、`Task` 定义于 `generator.py:62-96`。
- scorer 从 generator 导入 Oracle（`scorer.py:7-10`），split 从 generator 导入 FAMILIES/Oracle/Task（`split.py:9-13`），validator 从 generator 导入 Task（`validator.py:12-16`）。
- `bench/oracle.py:1-12` 只是对 generator 中 canonical Oracle 的兼容导入，表明概念位置与文件名已分叉。
- `Generator` 同时负责选择、S0 建造、row realization 与 Oracle 推导（`generator.py:99-152` 及后续多个 `_..._from_row`）。

理由：Task/Oracle 是 bench 的核心 domain model，不是随机工厂的实现细节。把它们移到 `bench/models.py` 可切断 scorer/split/validator 对工厂的无谓依赖，并让 frozen loader 与 candidate pipeline 共用稳定模型接口。

### F11（中）：`realizations.py` 的大体量本身可接受，但数据、key 规则和验证逻辑混在一起，已形成私有循环

证据：

- 文件共 2518 行；row schema/key/evaluate arithmetic 位于 `realizations.py:58-267`，大段数据位于约 `270-2337`，assertion 逻辑又位于 `2340-2518`。
- `assert_constrain_rows()` 在 `realizations.py:2474-2477` 运行时从 validator 导入私有 `_any_pair_unsatisfiable`；validator 顶层又导入 realization tables（`validator.py:15-16`）。这是延迟执行掩盖的双向依赖。
- `__all__` 同时公开 10 种 row 类型、10 张表、10 个 key 函数、计算函数和 7 个 assertion（`realizations.py:16-55`），接口面积接近实现分类，属于浅模块。

理由：把 2000 多行声明式数据放在 Python 中不必然错误，尤其它需要 code review 和 deterministic materialization；不合理的是数据文件还拥有跨 validator 的校验职责。建议按 family 拆为 data modules，schema/key 放一个稳定 registry，所有 admission checks 归 validator。这样修改一张表不会触碰验证实现，也不再需要循环私有 import。

### F12（中）：materializer 是关键生产入口，却依赖大量私有实现

证据：

- `scripts/materialize_split.py:38` 导入 `bench.split._item`。
- 同一脚本在 `296`、`334`、`368`、`399`、`467`、`483`、`497`、`512`、`528`、`548`、`588-591` 等处调用 `Generator._...` 私有 helper。
- 测试也大量直接调用这些 helper，例如 `tests/test_realizations.py:150-155`、`187-192`、`231-284`。

理由：按 deletion test，Generator 的复杂度会重新散落到 materializer 与测试；当前所谓“同一 helper 保证不漂移”是真的，但它没有稳定接口保护。应把 “realize(row, s0) -> Task” 和 “deserialize_task(raw, catalog) -> Task” 提升为明确 public interface，而不是复制逻辑；这会保留 locality，同时让重构不必同步修改几十个私有调用点。

### F13（中）：catalog 三模块职责基本合理，但 loader 策略命名和严格度不足

证据：

- `world/catalog.py:27-87` 提供统一 `FoodCatalog` mapping/search interface，并有 sqlite 与 memory 两种真实 adapter；这符合“两种 adapter 才值得一个 seam”。
- `world/catalog_store.py:19-30` 负责选择冻结 artifact 或 fixture；`world/catalog_fixture.py:135-154` 只构造 demo catalog/profile/state。
- 混淆主要来自 `catalog.py` 同时含 interface、SQLite I/O、FTS search 和 copy-on-write 实现，而 `catalog_store` 名称像存储实现，实际却是加载策略。

理由：不建议仅因“三兄弟”就机械合并。更有价值的调整是把 `catalog_store` 改成明确的 artifact loader，并区分 `load_gold_catalog_strict()` 与 `load_demo_catalog()`；FoodCatalog 可继续作为深模块隐藏 SQLite/memory 差异。如果以后 SQLite 与 in-memory 行为继续分化，再把它们变成两个 adapter，而不是现在先加无收益抽象。

## 4. 测试覆盖与打包卫生

### F14（中）：271 项测试对结果规则很强，但没有保护架构与发布入口

已确认 pytest 收集 271 项。强覆盖包括：

- end-state/Scorer：`tests/test_scorer.py:8-47`、`tests/test_pass_endstate.py:31-123`。
- runner 的 Oracle redaction、并发 clone 与停止条件：`tests/test_runner.py:61-152`、`173-253`。
- v0.5 的 240 数量、配额、逐题 validate 与可达性：`tests/test_v05_split.py:20-37`、`94-122`。
- 冻结前 portion anchor：`tests/test_materialize_gate.py:47-78`。
- agent 手册与 portion grammar 对称性：`tests/test_portions.py:236-264`。
- judge 白名单、采样阈值、parse retry：`tests/test_grams_gate.py:28-75`。

覆盖缺口：

- 没有测试断言公开 `GOLD_SPLIT_PATH` 等于 v0.5 且默认 runner 评 240 题；现有测试反而断言其约 40 题（`tests/test_split.py:17-20`）。
- 没有 loader 测试验证 split 的 `catalog_sha256` 与磁盘文件一致，也没有考试模式缺 catalog 时 fail closed 的测试。
- 没有 import-direction/acyclicity 测试，因此 bench → harness 和 realizations ↔ validator 可长期存在。
- ReAct 测试通过替换 `_complete` 测 presentation（`tests/test_react.py:122-150`），没有 fake transport 上的请求 payload、retry、HTTP/JSON error contract 测试；dotenv 也无测试。
- grams gate 只有单元测试，没有 candidate → gate → materialize 的集成测试；gray-zone probe 不是 pytest gate。
- catalog 构建与 dry-run 规则位于 scripts，没有对应 builder parity 测试；`build_fdc_catalog.py` 与 `fndds_dry_run.py` 各自维护 zip/row-sort/portion-key 规则（例如前者 `161-212`，后者 `121-182`）。

理由：测试数量主要覆盖行为叶子与冻结文件内容，却没有覆盖决定“运行的是哪份考试、搭配哪份 catalog”的入口 seam。应优先补发布契约测试，而不是继续增加 realization 行级测试。

### F15（低）：没有 lint/type/import 规则，`__all__` 与实际跨模块使用不一致

证据：

- `pyproject.toml:8-20` 的 dev 依赖只有 pytest，只配置 pytest；无 Ruff/Flake8、mypy/pyright、import-linter 等。
- `react.py` 的 `DEEPSEEK_CHAT_URL` 被 bench 与 probe 跨模块导入，却不在 `react.py:17-24` 的 `__all__`。
- `split.py:15` 只公开 `GOLD_SPLIT_PATH/load_split`，materializer 却导入 `_item`。
- `generator.py:34` 只公开三种类型，split 却导入 `FAMILIES`；大量脚本/测试直接使用 Generator 私有 helper。
- 多数模块有 `__all__`，但 `catalog_fixture.py` 没有；包级 world/bench/harness 又各自维护另一份导出列表（如 `world/__init__.py:20-42`、`bench/__init__.py:8-17`）。

理由：`__all__` 当前不是可靠的 interface 声明，只是局部文档。先确定真正 public seam，再让 lint/type/import 检查 enforcement；否则补齐列表只会把偶然依赖正式化。

### F16（低）：scripts 已被当作库使用，但没有进入包内稳定接口

证据：

- 测试通过修改 `sys.path` 导入脚本：`tests/test_materialize_gate.py:14-16`、`tests/test_review_sheet.py:14-17`。
- 多个 CLI 自行把 `src` 插入 `sys.path`，例如 `scripts/run_react.py:11-12`、`scripts/run_split.py:10-14`、`scripts/gray_zone_probe.py:24-25`。
- `scripts/landing_verify.py:21-25` 同时把 scripts/src 加入路径并把 `build_fdc_catalog` 当模块导入。
- `scripts/build_fdc_catalog.py` 与 `scripts/fndds_dry_run.py` 重复 zip member、CSV iteration、row sort 和 portion policy；它们的“独立”设计对一次性审计有价值，但长期作为生产规则会漂移。

理由：有测试、有跨脚本调用的函数已经不是纯 CLI glue。把确定性计算上收到 `src/nutrienv/`，scripts 只保留参数解析、文件选择和输出，wheel/CI 才能使用相同实现。需要刻意保留的独立 verifier 可以继续独立，但必须用 fixture parity test 对照生产 builder，而不是静默复制。

## 最值得做的 5 个架构动作

### A1. 把 240 题 split 与 catalog 变成一个严格的 ExamArtifact（风险：高）

建立一个唯一入口，例如 `load_exam()`：默认明确指向 `v0.5-gold.json`，读取并校验 version、题数/配额、catalog 路径、SHA-256，再构造 Task；缺失/不匹配立即失败。另设显式 `load_calibration_split()` 和 `load_demo_catalog()`，不允许 gold 路径静默 fallback。

零漂移证明：

1. 修改前后 `v0.5-gold.json` 与 `catalog.sqlite` 文件 SHA-256 完全不变。
2. 新旧显式 `load_split(V05)` 序列化所得 240 个 Task/Oracle 逐字段相等。
3. 默认 CLI/公开常量测试断言 `n == 240` 和 ADR 0009 配额；calibration 必须显式选择。
4. 对 catalog 改 1 byte、缺文件、hash 缺失分别做 fail-closed 测试。
5. 240 题继续通过 `validate_draft`、Oracle 可达性与现有 Scorer 回归；判分代码不改。

### A2. 抽出唯一 PortionAnchorPolicy（风险：中）

把 whitelist candidate 枚举与匹配放到 bench 的纯模块，validator、grams gate、materializer/review tooling 共用；返回 anchor provenance，明确哪些倍数和固定 ounce 是“可冻结事实”。不要把 LLM 结论并入该模块。

零漂移证明：

1. 在当前 catalog 全量食物 × portions × 现有 factors 上比较旧两实现与新实现，接受集合逐项相等。
2. 对 v0.5 的所有 ledger/plan grams 比较 `validate_oracle_grams` issue strings 逐项相等。
3. sandwich/lasagna/omelet 的 piece/qns 灰区 table-bypass 测试继续通过。
4. `freeze_split` 对现有 v0.2–v0.5 payload 的接受结果不变。

### A3. 建立 LLM client port + OpenAI-compatible HTTP adapter，配置只在 CLI composition root 加载（风险：中）

定义最小 `complete(messages, model, temperature, max_tokens) -> str` port。ReAct 与 grams judge 各自保留 prompt/解析/聚合策略，但注入同一个 HTTP adapter；dotenv loader 移出 harness，删除仓库外硬编码路径。把 K 次采样、parse retry、有效分母和 threshold 收成一个 `judge_portion()`，probe 直接调用它。

零漂移证明：

1. fake transport 捕获请求，断言 ReAct 与 judge 的 payload 字段、prompt 字节、temperature/max_tokens 与当前生产值一致。
2. 表驱动覆盖 HTTP error、timeout、malformed JSON、empty content、parse failure，固定 retry 次数与最终异常。
3. 用录制的 verdict 序列证明旧 gate 与新 gate 对 threshold 边界结果相同。
4. gray-zone 六个合法 FNDDS 值和极端 controls 作为接 gate 前的验收；未通过前保持 candidate pipeline 不调用 LLM gate。

### A4. 深化 bench：独立 models/realization/admission seam（风险：高）

把 Task/Oracle 移到 `bench/models.py`；提供公开 `realize(row_id, catalog, s0) -> Task` 与 `deserialize_task()`；row 带稳定 id/结构化 anchor，不再以 query 文本 join。realization data 可按 family 拆文件，schema/registry 集中，所有 assertion/admission 归 validator，消除 realizations ↔ validator 私有循环。materializer 和测试只走公开 interface。

零漂移证明：

1. 对所有 realization row，旧私有 helper 与新 `realize` 产生的 Task 逐字段相等。
2. 重跑 materialization 到临时路径，v0.1–v0.5 的 JSON 与仓库文件逐项相等；父 split 前缀保持 byte-for-byte 相等。
3. 现有 240 题的 `semantic_key`、`validate_draft` issue 列表、Scorer 结果逐项相等。
4. 新增一个 query 已 paraphrase 但 realization_id 不变的测试，证明结构检查不会因文本变化静默跳过。

### A5. 将被复用的 scripts 逻辑上收到包内，并加架构/质量门禁（风险：低）

materialization、review-sheet 核心、FNDDS portion policy 放进 `src/nutrienv` 的稳定模块；scripts 只做 CLI。增加 import-linter（或等价 AST 测试）锁住 `world <- actions <- env`、`bench` 不依赖 harness concrete adapter、realizations/validator 无环；再配置 Ruff 与渐进式类型检查。整理 `__all__`，只公开真实 interface。

零漂移证明：

1. wheel 安装后在仓库外目录运行 CLI smoke，不依赖 `sys.path.insert`。
2. builder 对固定小型 CSV fixture 的 SQLite rows/portion mappings 与旧实现完全相等。
3. 独立 dry-run verifier 与生产 builder 对同一 fixture 结果 parity；故意制造一处 policy 差异时测试必须失败。
4. 全部 271 项测试继续收集并通过，新增 import graph、public import 与 wheel smoke 测试；源码重排不触碰任何 data/split 文件。

## 优先级

建议顺序为 A1 → A2 → A3 → A4 → A5。A1 先封住“到底在考哪 240 题、配哪份 catalog”的发布契约；A2 收敛克数事实；A3 再稳定外部 LLM seam；A4 是收益高但改动面最大的深模块重构；A5 可伴随前四项逐步落地。任何步骤都不应修改 Scorer 的 `Pass ⇔ end state == Oracle` 语义，也不应重写既有 split 数据来适配新代码。
