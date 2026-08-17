# NutriEnv 架构审查

审查对象：`HEAD=12d3817`（`Finish follow-ups: mutex-modifier tests, judge grams gate, oz-dry refusal`），工作树干净。
范围：`src/nutrienv/`（29 个 `.py`，约 7000 行）、`scripts/`（13 个脚本）、`tests/`、`pyproject.toml`、charter / CONTEXT / ADR。本阶段只读，不改源码、数据或测试。

硬纪律（审查时当作不可违反的不变量，不作为优化对象）：

- 克数锚点 = FNDDS 表值 / QNS；LLM 产出永远是候选。
- 冻结 split `data/splits/v0.5-gold.json`（240 题）与判分规则 `Pass ⇔ end state == Oracle` 不许动。
- catalog `data/fdc/catalog.sqlite` 不许动。
- agent 手册 `harness/react.py::_SYSTEM_V1_TAIL` 语义不许变。
- 任何重构必须保持行为不变，以全量 pytest + `scripts/landing_verify.py` PASS 为证。

严重度约定（与既有审查文档一致）：

| 级 | 含义 |
|---|---|
| **阻断** | 已违反硬纪律，或现在就会改冻结 split / Oracle / 判分 / catalog / 手册语义。本审查未发现此类项。 |
| **判断** | 真实设计债：分层倒置、双份实现、漂移已登记。值得做，但不阻断当前考试路。 |
| **非阻断** | 卫生、命名、死代码、文档沉积。可做，不做也不伤冻结考试。 |

下文每条都标「保行为重构」或「行为变更」。保行为重构可以按提案清单独立落地；行为变更必须另开裁决，不得混进机械重构。

---

## 0. 当前架构（对照 charter）

CONTEXT 与 ADR 0005 给出的依赖方向：

```
world（catalog / profile / ledger / portions）
  ↑
actions（schemas + dispatch）
  ↑
env（NutriEnv.reset / step）
  ↑
bench（factory + oracle + scorer + gates）     ← 不得改 Env 物理
  ↑
harness.runner（composition root）             ← 唯一把 Env × Bench × Harness 绑在一起的地方
  ↑
harness.{protocol, script, react}             ← 可改措辞，不得改 gates / 算术 / Oracle
```

CHARTER.md 仍写「No harness implementation」，但 ADR 0005 已接受 Runner，代码里 `src/nutrienv/harness/` 已落地。以 ADR + CONTEXT 为准：Harness 存在是合法的；**bench 依赖 harness 不合法**。

包内行数（实现，不含测试）：

| 模块 | 行数 | 角色 |
|---|---:|---|
| `bench/realizations.py` | 2518 | 造题表 + 行级断言 |
| `bench/validator.py` | 812 | 工厂门（不是 Scorer） |
| `bench/generator.py` | 597 | 工厂 + Oracle/Task 定义 |
| `world/portions.py` | 379 | 份量语法（Env 运行时不调用） |
| `harness/react.py` | 324 | 手册 + dotenv + HTTP + ReAct |
| `actions/dispatch.py` | 312 | 动作处理 |
| `world/catalog.py` | 283 | FoodCatalog + FTS |
| `harness/runner.py` | 280 | composition root |
| 其余 `src/` | <230 | 较深、接口较小 |

整体不是 Big Ball of Mud。Env / actions / world 方向干净；主要债集中在 **bench ↔ harness 缝**、**bench 内部三件套耦合**、**realizations 单体**。

---

## 1. 分层与依赖方向

### 1.1 bench → harness：分层倒置

**严重度：判断。** 类型：保行为重构。

证据：

```19:20:src/nutrienv/bench/grams_gate.py
from nutrienv.harness.react import DEEPSEEK_CHAT_URL, load_dotenv_keys
from nutrienv.world.portions import OUNCE_GRAMS
```

`grams_gate` 是造题流水线的 plausibility 过滤器（CONTEXT：Harness 不得改 gates / 算术 / Oracle）。它却从 `harness/react.py` 拿 URL 和 dotenv。结果：

- 改 ReAct 客户端（重试、URL、key 加载）可能牵动 judge gate。
- `bench/__init__.py` 今天不 re-export `grams_gate`。一旦有人把它加进 `bench/__init__`，会形成运行时环：

  `grams_gate → react → runner → bench/__init__ → grams_gate`

当前不是运行时环（`bench/__init__.py:1-17` 只导出 Generator / Scorer / split），但是一处等着踩的缝。

对照 charter：gate 属于 Bench；Harness 是受试对象。Bench 依赖 Harness = 尺子依赖考生。

### 1.2 harness.runner → bench：符合 charter

**严重度：无问题（记录以免误修）。**

证据：

```10:15:src/nutrienv/harness/runner.py
from nutrienv import __version__
from nutrienv.bench import Generator, Scorer, load_split
from nutrienv.env import NutriEnv

from .protocol import Harness, HarnessView
```

CONTEXT：**Runner** = composition root，把冻结 Env + split 绑到一个 Harness 和一个 Model。`runner.py` 依赖 bench / env / protocol 是正确方向。不要为了「打破双向」把 Scorer 抽走或让 bench 反向调用 runner。

`react.py:15` 从 runner 只拿 `DEFAULT_MAX_STEPS`，这是 harness 内部依赖，可接受；若抽步数预算常量，只为减少 react↔runner 耦合，不是分层问题。

### 1.3 谁依赖谁才符合 charter

| 模块 | 可以依赖 | 不可以依赖 |
|---|---|---|
| `world/` | 无向上依赖 | env / actions / bench / harness |
| `actions/` | world | bench / harness |
| `env/` | world, actions | bench / harness |
| `bench/` | world（算术、catalog、portions） | **harness**（尤其 react） |
| `harness/protocol` | 无 | env / bench |
| `harness/script`, `harness/react` | protocol；叶子工具（dotenv / HTTP） | bench gates、world 算术 |
| `harness/runner` | env + bench + harness.* | —（这是唯一汇合点） |
| `scripts/` | 任意（薄 CLI） | 不应成为第二份库实现 |

LLM 客户端与 dotenv **应当抽到中立叶子模块**（建议名 `nutrienv/io/` 或 `nutrienv/util/`，不是 `world`，也不是 `bench`）。理由：

- 它不是营养世界物理，也不是考试尺子。
- 两个真实调用方已经存在（ReAct 考试路、judge 造题路）→ codebase-design：两个 adapter 才构成真实缝。
- 抽完之后：`grams_gate` 与 `react` 都只向下依赖叶子；bench 不再看见 harness。

### 1.4 CHARTER 与代码的沉积差

**严重度：非阻断。** 类型：文档，不是代码。

- CHARTER「No harness implementation」已被 ADR 0005 取代；代码已有 harness。
- CHARTER 动作表含 `query_nutrients`；`actions/schemas.py:14-24` 无此 op。这是 charter 未改，不是缺实现。
- CHARTER 包布局未列 `harness/`。以 CONTEXT「Runner / Harness」为准。

不要为了对齐 charter 新增 `query_nutrients` 或删掉 harness。那是行为变更，且不在本审查范围。

---

## 2. 重复与漂移风险

### 2.1 `_matches_portion_table` 双份（已登记）

**严重度：判断。** 类型：保行为重构。已在 `docs/followups-review.md:13` / `:82` 登记。

两处实现逐行相同：

```165:175:src/nutrienv/bench/validator.py
def _matches_portion_table(food_id: str, grams: float, catalog) -> bool:
    entry = catalog.get(food_id)
    if not isinstance(entry, dict):
        return False
    portions = entry.get("portions") or {}
    candidates = {round(2.0 * OUNCE_GRAMS, 2)}
    for one in portions.values():
        if isinstance(one, (int, float)) and not isinstance(one, bool):
            for quantity in (0.5, 1.0, 1.5, 2.0):
                candidates.add(round(quantity * float(one), 2))
    return round(float(grams), 2) in candidates
```

```62:77:src/nutrienv/bench/grams_gate.py
def _matches_portion_table(food_id: str, grams: float, catalog) -> bool:
    """Same candidate set as ``validator._matches_portion_table``.
    ...
    Copied so this module does not import the draft factory.
    """
```

复制原因正当：避免 `grams_gate` 导入整份 draft factory。但规则本身（档位 × `{0.5,1,1.5,2}` + 固定 `2 oz = 56.7 g`）是造题白名单，不是 Env 物理。只改一处就会让 `validate_oracle_grams` 与 `plausibility_gate` 接受不同克数——这是硬纪律敏感面：LLM 仍是候选，但「表内跳过 judge」的集合必须唯一。

正确缝：抽到 **不依赖 Task / Generator 的 bench 叶子**（例如 `bench/portion_table.py`），不要放进 `world/`。world 不应长出考试作者规则。

### 2.2 LLM HTTP 调用三份

**严重度：判断。** 类型：抽共享循环是保行为；对齐 max_tokens / 异常集合是行为变更，需单列。

| 位置 | 模型 / 温度 / max_tokens | 重试 |
|---|---|---|
| `harness/react.py:272-298` `_complete` | 考试模型，`temperature=0.0`，无 max_tokens | `IncompleteRead` / `URLError` / `TimeoutError` / `OSError`，3 次 |
| `bench/grams_gate.py:93-123` `call_judge` | `deepseek-v4-flash`，0.7，512 | 裸 `except Exception`，3 次 |
| `scripts/portion_judge_probe.py:67-95` `call_judge` | 同上模型 / 0.7，**120** | 裸 `except Exception`，3 次 |

共同点：`urllib.request.Request` + Bearer + `json.dumps` + 三次指数退避。不同点必须保留：ReAct 是确定性考试环（temp 0），judge 是随机采样（temp 0.7）。不要合成一个「万能 chat」。

`portion_judge_probe.py:33-45` 的 `JUDGE_SYSTEM` 与 `grams_gate.py:45-57` 逐字重复；`grams_gate.py:43-44` 自己注明「脚本不是库所以复制」。`parse_verdict` 也分叉：gate 接受裸 `ok`/`suspect`（`grams_gate.py:88-90`），probe 只认 JSON（`portion_judge_probe.py:98-100`）。followups-review 已标为非严格等价。

### 2.3 judge 采样 / 阈值双份

**严重度：判断。** 类型：保行为重构（语义已对齐）。已在 `docs/followups-review.md:14` 登记。

`plausibility_gate`（`grams_gate.py:184-191`）与 `gray_zone_probe.run_case`（`scripts/gray_zone_probe.py:145-169`）各自维护：

- `K=5`
- `threshold=0.6`
- `parse_fail` 过滤
- `ok_frac = ok / n_valid`（无有效 verdict 则 0）

`gray_zone_probe.py:27-32` 已复用 `judge_once` / `MODEL` / `TEMPERATURE` / `MAX_TOKENS`，但 **K 次循环与阈值仍在脚本里**。`PARSE_RETRIES=2`（脚本）对 `judge_once(..., parse_retries=1)`（gate 默认）也不对称。报告用脚本需要逐样本 verdict / reason，所以不能只调 `plausibility_gate`；应抽「采样 + 计票」返回明细，probe 打印、gate 只看 `(accepted, source)`。

### 2.4 dotenv 散落

**严重度：非阻断（与 1.1 一并修则升为判断的一部分）。** 类型：保行为重构。

`load_dotenv_keys` 定义在 `harness/react.py:92-104`，却被当作基础设施：

- `bench/grams_gate.py:19,95`
- `scripts/gray_zone_probe.py:33,36`
- `scripts/portion_judge_probe.py:24,26`
- `scripts/run_react.py:18,78`

这是「Harness 模块里藏着 IO 工具」。抽到叶子后，react 只保留手册与 act 循环。

### 2.5 FNDDS 份量键解析多份（触及 catalog，不可当机械重构）

**严重度：判断。** 类型：**行为变更 / 需裁决**。动它等于动 catalog 重建路径。

- `scripts/build_fdc_catalog.py:194-203` `_portion_key`（旧过滤，丢 QNS）
- `scripts/build_fdc_catalog.py:245+` `_overlay_keys`（安全 overlay，含 QNS / thick / oz 拆分）
- `scripts/fndds_dry_run.py:136-167` `_portion_keys`（dry-run 模拟完整 FNDDS）

硬纪律：catalog 重建必须先 dry-run 列「哪些食物克数会变」→ 审查 → 确认冻结 split 零漂移才落地。本审查 **禁止** 把这三处合成一步「清理」。最多在提案里标为后续裁决。

### 2.6 其它双份（非阻断）

| 重复 | 位置 | 风险 |
|---|---|---|
| `_catalog_tags` | `realizations.py:2340` 与 `validator.py:269` | 低；断言与门各自扫 allergen |
| `_BANNED_LOG_PAIRS` ≡ `_BANNED_EVALUATE_PAIRS` | `realizations.py:2348` 与 `:2487` | 低；同一禁配写两次 |
| `_TOKEN` 分词 | `world/catalog.py:20` 与 `actions/dispatch.py:96` | 低；dispatch 只服务 dict catalog 回退 |
| `_OUNCE_G = 28.35` | `harness/script.py:33` vs `world/portions.py:40` `OUNCE_GRAMS` | 低；ScriptHarness 是启发式受试者，不是尺子 |
| `_NUTRIENTS` vs `NUTRIENT_KEYS` | `generator.py:42` vs `catalog_fixture.py:24` | 低；后者无人引用 |
| `semantic_key` vs `*_key` | `validator.py:60-162` vs `realizations.py:168-245` | 中；形状相近但输入不同（Task vs Row），不要强行合成 |

---

## 3. `realizations.py`（2518 行）单体

**严重度：判断。** 类型：保行为重构（若 `__init__` 再导出全部公开名）。

结构：

| 区段 | 行 | 内容 |
|---|---|---|
| 类型 + 键 + `evaluate_windows` | 1–269 | 逻辑 / 接口 |
| 十张表 | 272–2338 | 约 2067 行数据 |
| `assert_*` + 禁配 | 2340–2518 | 行级不变量 |

`__all__`（`realizations.py:16-55`）把 Row 类型、十张表、十个 key、六个 assert 全部铺在一个模块上。接口几乎等于实现清单，浅。

循环耦合：

```2474:2476:src/nutrienv/bench/realizations.py
            from nutrienv.bench.validator import _any_pair_unsatisfiable

            if not _any_pair_unsatisfiable(row.windows, catalog, row.allergies):
```

`validator.py:16` 反向导入 `EVALUATE_ROWS, UPDATE_ROWS`，`_validate_evaluate`（`:659`）按 **query 原文** 找回 Row 再反解克数。这是 `docs/llm-generated-exam-data.md` 已点名的隐患：LLM 新 query 匹配不到就静默跳过反解。`validate_oracle_grams`（`:178`）已改成直接读 Oracle，但这条 query↔Row 路径还在。

是否按 family 拆数据、逻辑独立：**是**。推荐形状：

```
bench/realizations/
  __init__.py      # 再导出今日全部公开名，调用方零改
  types.py         # dataclass + *_key + evaluate_windows
  tables/*.py      # 每 family / situation 一张表
  checks.py        # assert_* ；依赖公开的 unsatisfiable 谓词，不懒导入 validator
```

不要把表改成 JSON/CSV。当前「Grams are never stored、phrase 决定克数」靠 Python dataclass + `resolve_portion` 在 import 时就能 assert。外置数据文件会把锚点检查推迟到运行时，且多一层序列化漂移。

拆包时注意：`tests/test_realizations.py:504-511` 用 `inspect.getsource` 断言 Generator 方法体里出现表常量名。只要 Generator 仍写 `FUZZY_ROWS` 等名字，测试不必改。

---

## 4. 模块边界

### 4.1 `world/`：`catalog.py` / `catalog_store.py` / `catalog_fixture.py`

**严重度：判断（静默回退）；命名本身非阻断。**

职责其实清楚：

| 文件 | 实际职责 |
|---|---|
| `catalog.py` | 运行时 `FoodCatalog`（Mapping + FTS5 / 内存搜索） |
| `catalog_store.py` | 冻结路径 + `load_catalog` |
| `catalog_fixture.py` | 15 食物内存夹具，供 smoke / 无 sqlite 的克隆 |

命名可以更好（`store` 不像 loader），但重命名成本高于收益。真正的缝在 `catalog_store.py:25-30`：目标 sqlite 不存在时 **静默** 落到 `demo_catalog()`。考试路若没带上 `catalog.sqlite`，split 测试会用 15 食物夹具跑，错误形状是「缺食物 / 克数不对」，不是「找不到 catalog」。这不是改 catalog 文件，是改加载失败模式——若要改，属行为变更，需测试钉死「缺文件即失败」。

其它观察：

- `WorldState.catalog` 注解是 `dict`（`types.py:67`），运行时却是 `FoodCatalog`。`generator.py:271` / `split.py:102` / `dispatch.py:87` 都用 `getattr(..., "canonical_id", None)` 探测。类型撒谎，可测试性差。
- `FoodCatalog.from_sqlite`（`catalog.py:60-79`）把全部非 branded 行读进内存；之后每次 `search` / 未命中 lookup 再开一条只读连接（`:111`、`:172`）。对当前 ~13k 行可接受；接口未暴露连接生命周期。
- `SNAPSHOT_PATH`（`catalog_store.py:16`）导出但无人读。`load_catalog` 只认 sqlite，否则 fixture。遗留 JSON `data/catalog-snapshot.json` 与 `scripts/ingest_usda.py`、`scripts/build_catalog_from_local.py` 同属旧管线。
- `NUTRIENT_KEYS`（`catalog_fixture.py:24`）定义后从未引用。

### 4.2 `bench/`：realizations ↔ validator ↔ generator

**严重度：判断。** 类型：大部分是保行为；query↔Row 反解改成强制函数是行为收紧，需裁决。

当前三角：

```
realizations  --(表, assert 懒导入 _any_pair_unsatisfiable)--> validator
validator     --(EVALUATE_ROWS, UPDATE_ROWS, Task)--> generator + realizations
generator     --(全部表, _*_from_row)--> realizations
materialize_split --(私有 gen._*_from_row + split._item)--> 三者
```

Generator 同时拥有：（a）`Oracle` / `Task` 类型；（b）`sample()` 工厂；（c）`_*_from_row` 考试路 helper。ADR 0006 说工厂不是考试；`materialize_split.py:25-38` 却必须摸私有 helper 和 `split._item`。接口把冻结路径需要的东西藏起来了。

`validator.py` 812 行，既是「漏题 / 可达 / 过敏原」门，又内嵌 update 子句解析（`:307-347`）、Atwater 不可满足（`:558-623`）、staple 搜索（`:770-812`）。门本身深，值得保留；问题是它还当 realizations 的库用。

`oracle.py` 整文件是兼容层：`derive_oracle` / `TIRED_KCAL_DELTA` **仓库内零引用**（只在该文件出现）。真正的 `Oracle` 住在 `generator.py:63`。

`seed.py::make_rng` 同样零引用。Generator 直接 `random.Random(seed)`。

### 4.3 `actions/schemas.py` 与 `dispatch.py`

**严重度：非阻断。** 边界已经对。

- schemas：信封、`OPS`、`ActionError`。深：调用方只认 `validate_envelope`。
- dispatch：先校验再变异（`dispatch.py:4-7`），Illegal Action 不半写入。符合 ADR 0004。
- `as_nonempty_str` / `as_dict` / `as_list` 不在 `schemas.__all__`（`:11`），但 dispatch 使用。卫生问题。
- `SEARCH_ALL` 注释打架：`dispatch.py:55-58` 说 `*` 用来发现食物；`:115` 与 `:127` 说 `*` 返回空。行为以代码为准（空），与 `env/README.md:46` 一致。
- dict catalog 回退搜索（`_search_mapping`）与 `FoodCatalog._search_memory` 重复。夹具路径需要它；不要为了去重把 FoodCatalog 硬塞进 dispatch。

### 4.4 `harness/protocol.py` 的 `HarnessView`

**严重度：非阻断（缝是对的）。**

```16:25:src/nutrienv/harness/protocol.py
@dataclass(frozen=True)
class HarnessView:
    """What a harness may see in ``reset``: identity and the query, nothing else."""

    id: str
    family: str
    persona: str
    situations: tuple[str, ...]
    query: str
```

Runner 默认把 View 而不是 Task 传给 `reset`（`runner.py:159-167`），`leak_oracle=True` 才给完整 Task。这守住了「Harness 不得看 Oracle」。

轻微泄漏：`family` / `persona` / `situations` 是考试元数据。CHARTER：难度在 query + S0，不在隐藏工具。ReAct 的 `reset`（`react.py:243-249`）目前忽略这些字段；ScriptHarness 看 query 文本。字段在，等于预留捷径。保持即可，不要让受试 harness 按 family 分支——那会变成教具简化动作空间。

`react.py:26-37` 的 `_OPS` 手写了一份动作名，并加上 `finish`（schemas.OPS 没有 finish，finish 是 runner 协议，`runner.py:29`）。两份名单会漂。保行为做法：`_OPS = frozenset(OPS) | FINISH_OPS`。

---

## 5. 其它

### 5.1 死代码与命名不一致

**严重度：非阻断。**

| 项 | 证据 | 说明 |
|---|---|---|
| `derive_oracle` / `TIRED_KCAL_DELTA` | `bench/oracle.py` 全文件无外部引用 | 早期 tired/shrimp 合同，已被 `_*_from_row` 取代 |
| `make_rng` | `bench/seed.py:10` 无外部引用 | Generator 自建 `Random` |
| `NUTRIENT_KEYS` | 只在 `catalog_fixture.py:24` | 死常量 |
| `SNAPSHOT_PATH` | 导出，从不加载 | 旧 JSON 管线化石 |
| `GOLD_SPLIT_PATH` | `split.py:18` → `v0-gold.json`（40 题） | 考试是 `v0.5-gold.json`（240）。`scripts/run_react.py:31` 默认跑校准集。名字像「现行金标」，实际是 v0 校准。 |
| `Generator.generate` | `generator.py:155` | `sample` 的别名 |
| `lookup` 工厂 | `generator.py:317-324` | query 故意泄漏 `catalog id`；lookup 不在 240 题里 |
| `scripts/ingest_usda.py`、`build_catalog_from_local.py` | 写 `catalog-snapshot.json` / 外仓 `NutriMind` | ADR 0008 之后的死管线 |
| CHARTER `query_nutrients` | 见 §1.4 | 文档沉积 |

`GOLD_SPLIT_PATH` 是高认知成本的非阻断项：新人会把 40 题校准集当成 240 题考试。改默认路径是行为变更（`test_runner.py`、`test_split.py`、`test_id_normalize.py` 都绑 v0）。保行为做法：加 `V05_SPLIT_PATH`（或 `EXAM_SPLIT_PATH`）常量，保留 `GOLD_SPLIT_PATH` 别名并在文档写明。

### 5.2 `__all__` 卫生

**严重度：非阻断。**

- `world/__init__.py` 不转出 `ImplausibleQuantity`、`MAX_ITEM_GRAMS`（`types.py` 有）。
- `actions/__init__.py` 不转出 `SEARCH_ALL`、`MAX_PLAN_GRAMS`、`as_*`。
- `bench/__init__.py` 不转出 `grams_gate`、`validator`、`realizations`——这是对的，别为了「完整」把 gate 拉进包根（见 §1.1 环风险）。
- `grams_gate.__all__` 偏大：把 `MODEL` / `TEMPERATURE` / `MAX_TOKENS` 做成公开合同。probe 需要它们；可以保留，但应视为内部常量。

### 5.3 可测试性

**严重度：判断（类型撒谎）；其余非阻断。**

好的缝（保持）：

- `plausibility_gate(..., judge=)` 可注入（`grams_gate.py:165`）；`tests/test_grams_gate.py` 已钉表白名单不调 LLM。
- `Harness.clone` / `HarnessView` 让并行 runner 可测。
- `resolve_portion` 纯函数，不碰 Env。
- 冻结 split 测试 `test_v0{1-5}_split.py` 锁增量不变量。

弱的缝：

- `materialize_split` / `landing_verify` 走 `sys.path.insert` 当库用；`tests/test_materialize_gate.py` import 脚本模块。脚本里的规则没有包级接口。
- `WorldState.catalog: dict` 迫使到处 `getattr`。
- 大量内部函数无类型（`catalog` 参数、`_judged_profile` 返回值）。
- `test_realizations.py` 的 `inspect.getsource` 把实现字符串当合同，重构易碎。

### 5.4 `pyproject.toml` 无 lint / type 配置

**严重度：非阻断。**

```1:20:pyproject.toml
[project]
name = "nutrienv"
...
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

无 ruff、无 mypy、无 hatch 之外的工具。仓库靠 pytest + `landing_verify` 守行为。加 lint/type 是卫生，必须 `ignore_init` / 基线，避免一次改出噪音 diff。不要让 formatter 碰 `realizations.py` 表格式——那 2000 行表是人读的。

### 5.5 scripts 与 src 的重复

**严重度：判断（judge / 份量键）；其余非阻断。**

| 脚本 | 与 src 的关系 |
|---|---|
| `run_split.py`、`run_react.py` | 薄 CLI，好 |
| `landing_verify.py` | 零漂移门，应保持脚本；逻辑已调 src |
| `materialize_split.py`（719 行） | 增量配方 + S0 几何 + 私有 API。偏厚，但是冻结唯一入口 |
| `gray_zone_probe.py` | 半库化，仍复制采样循环 |
| `portion_judge_probe.py` | 历史 15/15 实验，整份 HTTP + prompt 副本 |
| `build_fdc_catalog.py` / `fndds_dry_run.py` | 份量键逻辑双份；动 = catalog 重建 |
| `qns_gap_audit.py` | 读 catalog + `resolve_portion`，干净 |
| `ingest_usda.py` / `build_catalog_from_local.py` | 旧管线 |

### 5.6 运行时 / 习惯性债（非阻断）

- `grams_gate.call_judge` 与 `portion_judge_probe.call_judge` 裸 `except Exception`（已标 `BLE001`）。
- `FoodCatalog.__eq__`（`catalog.py:237-244`）比较路径与 overlay，不比较 `_base` 内容。
- `Scorer._ScoreResult`（`scorer.py:14`）为早期测试保留属性接口。
- ScriptHarness 把 chicken/rice 的 kcal 写死在注释算术里（`script.py:217-218`），不读 catalog。受试者允许不完美；不要把它「修」成第二个 Oracle。

---

## 6. 什么是健康的（不要拆）

审查不是清单式拆迁。下列模块已经深，接口小，动它们的风险大于收益：

- **Env**：`nutri_env.py` 81 行，不打分、不造题。保持。
- **dispatch 先校验再写**：Illegal Action 世界字节级不变。保持。
- **`resolve_portion` 不进 Action**：`log_meal` 只收 grams。保持。手册对称性继续靠人同步 `_SYSTEM_V1_TAIL`。
- **Scorer 只看终态**：`scorer.py:33`。不要把 validator 逻辑搬进 Scorer。
- **冻结 split + `load_split` 挂 live catalog**：考试文件不含食物营养，catalog 一处变、测试会红。这是故意的（ADR 0006 / 0008）。
- **`validate_draft` 与 Scorer 分离**：工厂门 ≠ 判分。保持。
- **HarnessView 默认藏 Oracle**：保持；`leak_oracle` 必须继续自标识（`runner.py:136`）。
- **judge 只过滤、不定义克数**：`plausibility_gate` 表白名单先过。保持。抽公共函数时不得把 LLM 放进表路径。

---

## 7. 阻断项汇总

本审查 **0 个阻断项**。分层倒置与双份白名单都还没有改冻结考试或判分。它们是判断项，因为下一次只改一处就会变成纪律事故。

判断项应优先处理的三处：§1.1 叶子 IO + 切断 bench→harness、§2.1 白名单单点、§3 realizations 拆数据/逻辑。有序落地步骤见 `reports/architecture-proposal.md`。
