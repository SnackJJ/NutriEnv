# 架构优化落地终审复核

> 当前状态（复审）：**允许合并，阻断项 0 个。** 文首“需修复”为第一轮历史裁决，已由文末复审结果取代。

审查范围：`12d3817..HEAD`（HEAD `0f71b3f`，共 9 个 `arch:` commit）。本报告不采用实现者提交说明中的通过结论，所有结果均由当前工作树重新读取、执行或故障注入得出。

## 总结

- **Standards 轴：不通过。** 冻结数据和判分纪律没有漂移，分层、白名单、拆包及卫生项基本达标；但严格考试入口存在两条完整性缺口。
- **Spec 轴：不通过。** A1/A2 没有在默认 ReAct 调用链上闭合，且 `load_exam` 校验的 catalog 不一定是实际装载的 catalog。B3 仍有一处“单点合同”未完全收口。
- **最终裁决：需修复。** 唯一阻断项共 **2 项**，合并前必须清零。

## 独立复算结果

| 项目 | 独立结果 | 证据 |
|---|---|---|
| commit / diff 范围 | 9 个 `arch:` commit，diff 非空 | `git log 12d3817..HEAD --oneline`；`git diff 12d3817...HEAD` |
| 初始工作树 | 已跟踪文件干净，但有 3 个既存 untracked report | `git status --short` |
| pytest | **290 passed，0 failed**，140.75s | `.venv/bin/python -m pytest -q` |
| landing verifier | **RESULT: PASS** | 240 items / 0 failing；178 equal / 0 differ；old-key drifts 0 |
| data diff | 只有 `data/splits/v0.5-gold.json` 变更，且只有 `catalog_sha256` 一行 | `git diff 12d3817..HEAD -- data/` |
| v0.5 items 原始字节 | **完全相同**；从 `"items"` 值起共 241,295 bytes，SHA-256 `d1b6e90a…18b59` | 对 `git show 12d3817:...` 与 `git show HEAD:...` 的原始 bytes 作断言；JSON 解析后亦断言 240 项相等 |
| v0.1–v0.4 | **逐字节相同** | 四文件分别作 old/HEAD bytes 断言；SHA-256 为 `913b7d6f…2492f`、`84fd3e93…ee4cc9`、`bcdfd061…10a5b`、`d4f366fa…92946d` |
| catalog.sqlite | **逐字节相同**；5,771,264 bytes | old/HEAD bytes 断言相等 |
| A3 catalog SHA | 实测与 v0.5 记录均为 `ff2f26325cc0cc71c3230f82060997afaeefcad0051b09989c662ac0b0fa2d90` | `hashlib.sha256(data/fdc/catalog.sqlite)` 与 manifest 字段比较 |
| 默认 split / 配额 | `load_split()` = 240；log 48 / recommend 72 / evaluate 48 / update 36 / constrain 36 | `src/nutrienv/bench/split.py:25-35`；独立 Counter |
| fail-closed 基础路径 | 缺 items/catalog/SHA、错误 version、SHA mismatch、catalog 文件不存在均 raise | `src/nutrienv/bench/split.py:45-72`；独立临时 manifest 故障注入 |
| 白名单 | steak 160=True；omelet 55=True；2 oz/56.7=True；steak 30=False | `src/nutrienv/bench/portion_table.py:15-25`；独立调用 |
| v0.5 行为抽查 | 前两题 `validate_draft == []`；全量 verifier 为 240/0 failing | `src/nutrienv/bench/validator.py:187-200`；独立调用及 landing verifier |
| gray-zone catalog guard | sandwich 175/115=`1.52x`；lasagna 206/250=`1.21x`；omelet 55/110=`2.00x` | `scripts/gray_zone_probe.py:46-110`；独立执行 `confirm_catalog()` |
| 依赖/冻结合同 | Scorer、`resolve_portion`、pyproject/lock 均零 diff；无新依赖 | `src/nutrienv/bench/scorer.py`；`src/nutrienv/world/portions.py:122`；`pyproject.toml` |
| `_SYSTEM_V1_TAIL` | old/HEAD 值长度均 1,096，SHA-256 均 `c67b0232…150c4` | `src/nutrienv/harness/react.py` AST 常量复算 |

## Standards 轴：架构、纪律与漂移

### S-B1【阻断】默认 ReAct 绕过严格考试入口

`run_split()` 只有在 `split_path is None` 时调用 `load_exam()`；只要传入路径便调用宽松的 `load_split()`（`src/nutrienv/harness/runner.py:83-86`）。但 `run_react` 把 `--split` 默认值设为 `EXAM_SPLIT_PATH`（`scripts/run_react.py:27-30`），随后默认分支总是把该非空字符串传给 runner（`scripts/run_react.py:83-95,113-119`）；使用 `--limit` 时还会提前宽松装载（`scripts/run_react.py:99-103`）。

独立故障注入把临时 v0.5 manifest 的 SHA 改成全零后，`run_split(split_path=bad_manifest, task_ids=[])` 仍成功返回，而直接 `load_exam(bad_manifest)` 会 raise。故默认 CLI 没有落实 A2 的 fail-closed 完整性门，违反“默认考试入口绑定冻结 artifact”的架构纪律。

### S-B2【阻断】`load_exam` 校验 A，却装载固定默认 B

`load_exam()` 根据 manifest 的 `catalog` 字段解析路径并计算 SHA（`src/nutrienv/bench/split.py:57-72`），但通过后调用 `load_split(target)`（`src/nutrienv/bench/split.py:73`）；后者无条件调用无参 `load_catalog()`（`src/nutrienv/bench/split.py:30-35`），最终使用固定 `GOLD_CATALOG_PATH`（`src/nutrienv/world/catalog_store.py:19-29`）。

独立故障注入创建一个内容为 `not a sqlite catalog` 的临时 `.sqlite`，在 manifest 写入其正确 SHA；`load_exam()` 仍返回 240 题，证明该文件只被哈希、从未被装载。当前正式 manifest 恰好指向默认 catalog，所以正常测试未暴露问题；严格入口的“校验对象 = 运行对象”合同仍未成立。

### S-J1【判断】judge 聚合合同仍有第二份语义

生产 gate 的有效 verdict 分母集中在 `accept_from_verdicts()`（`src/nutrienv/bench/grams_gate.py:147-155`），gray-zone probe 已调用共享采样和接受函数（`scripts/gray_zone_probe.py:146-171`）。但旧 `portion_judge_probe` 仍自行维护 K 次循环，并以全部 K（含 `parse_fail`）作分母（`scripts/portion_judge_probe.py:31-32,54-72`）。这与“采样合同单点、probe 变调用方”的完成标准不完全一致，并保留了 F6 已指出的分母漂移。其 HTTP/prompt/parser 与 512 token 已成功统一，因此此项不单独定为阻断。

### S-N1【非阻断】初始工作树不完全干净

审查开始时 `git status --short` 显示 3 个既存未跟踪文件：`reports/architecture-proposal.md`、`reports/architecture-review-independent.md`、`reports/architecture-review.md`；已跟踪文件无修改。这不污染 `12d3817..HEAD`，也不是本批实现漂移，但与“工作树应干净”的预期不符。

### Standards 通过项

- 判分与克数纪律：`src/nutrienv/bench/scorer.py`、`src/nutrienv/world/portions.py` 相对固定点零 diff；catalog、v0.1–v0.4 零漂移；v0.5 只有 SHA 字段变化。
- 分层：bench 源码没有 `nutrienv.harness` import；realizations 源码没有 validator import；`src/nutrienv/io/chat.py:1-64` 与 `src/nutrienv/io/dotenv.py:1-22` 不向上依赖；在 `src/nutrienv` 中只有 runner 同时汇合 bench、Env 与 harness protocol（`src/nutrienv/harness/runner.py:10-15`）。
- 白名单单点：validator 与 gate 都只调用 `matches_portion_table`（`src/nutrienv/bench/validator.py:15-18,179-182`；`src/nutrienv/bench/grams_gate.py:20,181-182`），不存在 `_matches_portion_table`。
- realizations 断环：公开谓词位于 `src/nutrienv/bench/windows.py:7-88`；checks 顶层依赖该公开名（`src/nutrienv/bench/realizations/checks.py:5`）。
- 卫生：`Generator.generate` 保留（`src/nutrienv/bench/generator.py:155-171`）；`SNAPSHOT_PATH` 保持导出（`src/nutrienv/world/catalog_store.py:11-16`）；运行时断言 `_OPS == frozenset(OPS) | FINISH_OPS`，源码见 `src/nutrienv/harness/react.py:9-30`；`WorldState.catalog` 为 Mapping（`src/nutrienv/world/types.py:57-68`），共享 canonicalizer 位于 `src/nutrienv/world/catalog.py:27-32`。

## Spec 轴：裁决内容落地情况

| 裁决项 | 结论 | 证据 |
|---|---|---|
| A1 默认 v0.5 / 240 | **部分实现**：常量、`load_split()`、裸 `run_split()` 正确；默认 ReAct 严格性未跟随 | `src/nutrienv/bench/split.py:19-27`；`src/nutrienv/harness/runner.py:63-86`；阻断 S-B1 |
| A2 严格 `load_exam` | **未完整实现**：基础错误能关闭，但默认 CLI 绕过，且校验/装载 catalog 可分离 | `src/nutrienv/bench/split.py:38-73`；阻断 S-B1、S-B2 |
| A3 v0.5 SHA 修复 | **实现**：只改一行，items 原始字节不变，实测 SHA 一致 | `data/splits/v0.5-gold.json:4` |
| B1 白名单单点 | **实现** | `src/nutrienv/bench/portion_table.py:15-25`；两调用方证据见上 |
| B2 io 叶子 / 断反向依赖 | **实现**；`run_react` 无机器绝对路径 | `src/nutrienv/io/chat.py:1-64`；`src/nutrienv/io/dotenv.py:1-22`；`scripts/run_react.py:76-81` |
| B3 judge 合同单点 | **部分实现**：gate 与 gray-zone 已统一，portion probe 分母仍自管；K=5、threshold=.6、temp=.7、max_tokens=512 均未违规 | `src/nutrienv/bench/grams_gate.py:39-43,125-155,191-192`；`scripts/portion_judge_probe.py:31-32,54-72` |
| B4 公开 unsatisfiable / 断环 | **实现** | `src/nutrienv/bench/windows.py:7-88`；`src/nutrienv/bench/realizations/checks.py:5` |
| B5 realizations 拆包稳定 | **实现**：旧/新 `__all__` 均 38 名且完全相等，逐名 getattr 成功 | `src/nutrienv/bench/realizations/__init__.py:8-92` |
| C 卫生 | **实现** | `src/nutrienv/bench/generator.py:155-171`；`src/nutrienv/world/catalog_store.py:11-16`；`src/nutrienv/harness/react.py:9-30`；`src/nutrienv/world/types.py:57-68` |

拆包未迫使关键脚本变化：`scripts/materialize_split.py` 与 `scripts/landing_verify.py` 相对 `12d3817` 均为零 diff，仍通过稳定的 `nutrienv.bench.realizations` 导入（`scripts/materialize_split.py:25-37`；`scripts/landing_verify.py:24-38`）。

`tests/test_exam_entry.py:24-55` 覆盖默认数量/配额、缺 catalog、SHA mismatch 与错误 version，但没有覆盖“默认 run_react 必须走 `load_exam`”或“实际装载 manifest 指定 catalog”。这正是两个阻断缺口能在 290 项测试全绿时存在的原因；修复时应补相应故障注入回归。

## 最终裁决

**需修复。阻断项 2 个：**

1. 默认 `run_react` 必须在未显式选择历史/custom split 时走 `load_exam()`，包括 `--limit` 路径，错误 SHA 必须在创建 harness/运行任务前失败。
2. `load_exam` 必须把已校验的 catalog 路径用于 Task 构造，或严格拒绝任何不是唯一预期 catalog 的 manifest；不能校验一个文件再装载另一个文件。

完成这两项并加入回归后，重新运行本报告中的冻结字节断言、290 项测试（届时数量可增加）与 landing verifier；阻断清零前不允许合并。

---

## 复审结果（d3cebaa、5bd26d6）

复审固定点为上一轮 HEAD `0f71b3f`，修复范围为 `0f71b3f..5bd26d6`。本节重新执行故障注入，不以两个修复 commit 的说明作为证据。

### 逐项复测

#### S-B1【已清零】默认 ReAct 严格失败关闭

实现现把 `--split` 默认值设为 `None`（`scripts/run_react.py:27-31`），`load_react_tasks(None)` 调用 `load_exam()`、显式路径才调用 `load_split()`（`scripts/run_react.py:74-78`）。非 factory 分支在构造 `ReActHarness` 前完成该加载，`--limit` 也复用同一批已严格加载的 Task（`scripts/run_react.py:103-125`）。

独立注入方法与结果：

- 复制 v0.5 manifest 到临时目录，把 `catalog_sha256` 改成 64 个 `0`；把默认 `EXAM_SPLIT_PATH` 指向该文件，并把 `ReActHarness`、`run_split` 都替换为记录调用后立即失败的哨兵。
- `run_react.main([])` 抛出 `ValueError: catalog sha256 mismatch`，事件列表为 `[]`。
- `run_react.main(["--limit", "1"])` 同样抛 mismatch，事件列表为 `[]`。
- `load_react_tasks(bad_manifest)` 显式传路径仍由宽松入口成功加载 **240** 题，保留裁决要求的 historical/custom split 行为。

新增测试不是 happy-path 自证：`tests/test_exam_entry.py:141-168` 对默认及 `--limit` 真正注入坏 SHA，并以 harness 哨兵证明失败发生在构造前；`tests/test_exam_entry.py:171-178` 分别钉住显式宽松路径和 parser 的 `None` 默认值。若换回上一轮实现，默认 parser 已捕获原 `EXAM_SPLIT_PATH` 且会走宽松 loader，这两条坏 SHA 测试不会得到预期的 `ValueError`。

#### S-B2【已清零】校验与装载使用同一 catalog

`load_exam()` 对 `catalog_path` 计算 SHA 后，明确调用 `load_catalog(catalog_path)`，再把所得对象注入 `load_split(..., catalog=catalog)`（`src/nutrienv/bench/split.py:63-81`）；`load_split` 仅在未注入时才使用默认 catalog（`src/nutrienv/bench/split.py:25-40`）。

独立注入方法与结果：

- 创建结构完整的临时 SQLite catalog，只放入 `round2_probe_food / round two probe aubergine` 及其 FTS/alias；把 manifest 的 catalog 指向它并记录该文件的真实 SHA。
- 包装 `split.load_catalog` 捕获实参：调用恰好一次，实参解析后与临时 SQLite 的绝对路径完全相等。
- `load_exam()` 返回 Task 的 `s0.catalog` 包含并可搜索命中 `round2_probe_food`；不包含且搜索不到默认 catalog 独有的 `milk_whole`。

新增测试 `tests/test_exam_entry.py:60-110` 构造独立 SQLite，`tests/test_exam_entry.py:113-133` 同时断言 probe 食物正命中和默认食物负命中。上一轮“校验 A、装载 B”实现会在这些身份断言上失败，故测试真实覆盖缺口。

#### S-J1【已清零】portion probe 使用共享采样与有效分母

`portion_judge_probe` 现在从 gate 导入 `DEFAULT_K`、`DEFAULT_THRESHOLD`、`sample_verdicts`、`accept_from_verdicts`（`scripts/portion_judge_probe.py:21-33`），主循环调用两共享函数，并只用有效 verdict 计算展示用 `ok_frac`（`scripts/portion_judge_probe.py:59-80`）。

独立注入 `['ok', 'parse_fail', 'ok', 'suspect', 'parse_fail']` 后观察到：

- `sample_verdicts` 收到 `k=5`；`accept_from_verdicts` 收到 threshold `0.6`；
- 打印值为 `ok_frac=0.67`，接受为 YES，证明分母是 3 个有效 verdict，而不是全部 5 次调用；
- 运行时常量为 K=5、threshold=0.6；`TEMPERATURE=0.7` 未变；
- `JUDGE_SYSTEM` 相对 `0f71b3f` 字节相同，长度 688，SHA-256 均为 `9aab633b320a70dd18beb25548494c2218bde50ebf4671a88339d80ce380ab21`。

### 全量、landing 与冻结字节复算

| 检查 | 复审结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **296 passed，0 failed**，142.00s |
| `tests/test_exam_entry.py` 定向 | **10 passed**，0.93s |
| `.venv/bin/python scripts/landing_verify.py` | **RESULT: PASS**；240 items / 0 failing；178 equal / 0 differ；old-key drifts 0 |
| v0.1–v0.4 vs `12d3817` | 四文件逐字节相同 |
| `data/fdc/catalog.sqlite` vs `12d3817` | 5,771,264 bytes 逐字节相同；SHA-256 `ff2f2632…0fa2d90` |
| v0.5 vs `12d3817` | diff 仍只有 `catalog_sha256` 一行 |
| v0.5 items | JSON 解析后 240 项完全相等；沿用上一轮原始 bytes 断言，241,295 bytes、SHA-256 `d1b6e90a…18b59` 完全相同 |
| manifest / catalog | 记录值与 catalog 实测 SHA 完全相等 |

### Standards 轴复审

**通过，0 个阻断。** 修复 diff 只涉及 `scripts/run_react.py`、`scripts/portion_judge_probe.py`、`src/nutrienv/bench/split.py`、`tests/test_exam_entry.py`。相对 `0f71b3f`，Scorer、`resolve_portion`、`react.py`、白名单、realizations、windows、io、依赖文件均零 diff；bench→harness、realizations→validator、io 向上 import 仍为零，冻结纪律和既有卫生项继续成立。

非阻断观察：为满足“创建 harness 前失败”，默认 ReAct 会在 `scripts/run_react.py:103-125` 预载一次，runner 随后在 `src/nutrienv/harness/runner.py:83-86` 再加载一次。这是轻微重复/TOCTOU 面，但两次都走严格 `load_exam`，不重新打开本轮阻断；可在未来通过向 runner 传入已加载 tasks 的窄接口消除。另 `src/nutrienv/bench/grams_gate.py:45-46` 关于 prompt 与旧 probe 重复的注释已经过期，仅属文字卫生。

### Spec 轴复审

**通过，0 个阻断。** S-B1 默认及 `--limit` 严格入口、显式路径宽松合同均按裁决实现；S-B2 已保证已验证 catalog 就是 Task 实际使用的 catalog；S-J1 已统一到共享采样/接受合同且所有冻结参数未变。新增故障注入测试能在旧缺陷实现上失败，未发现范围外行为变更。

### 复审最终裁决

**允许合并。阻断项：0 个。** 上一轮 S-B1、S-B2 均已清零，S-J1 判断项也已关闭。
