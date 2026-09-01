# catalog-v2 重建裁决（claude / Opus）

裁决日期：2026-08-25　裁决人：claude (Opus)　依据：AGENTS.md 硬纪律 2
待裁事项：把 9 个食物专属计数单位（wing / drummette / scoop / patty / pat / packet /
pouch / bar / stick）追加为 FNDDS 提取的 catalog key，重建 `data/fdc/catalog-v2.sqlite`。

本裁决只读：未改代码、未重建 catalog、未改任何 `data/` 文件。所有验证产物写在
session scratchpad，仓库内只新增本文件。

---

## 结论：**APPROVE-WITH-CONDITIONS**

**Q1 裁决：不阻断。** beverage 判定的残留 fail-closed 漏判与本轮 catalog 重建
**正交** —— 我已证明重建前后 `_is_beverage_name` 的判定结果逐食物完全一致（翻转
0 例）。重建既不能改善也不能恶化这个问题，因此它不构成本轮的落地闸门。

**Q2 处置：采纳 (a)，记为 backlog**，用显式饮料 id 清单替换名称启发式；候选池是
已界定的 194 行，不是开放式词表扩张。**不采纳 (b)**。

条件见文末「落地条件」一节 —— 有一项是 codex 五轮未覆盖的真实副作用。

---

## 一、我独立核验了什么

不轻信交接材料，逐条复算：

| # | 主张 | 我的核验方式 | 结果 |
|---|---|---|---|
| 1 | dry-run 报告与当前代码一致 | 重跑 `--dry-run --report <scratchpad>`，与仓库报告逐字节 diff | **IDENTICAL** |
| 2 | 462 / 487 / removed 0 / changed 0 | 同上，报告内数字 | 复现 |
| 3 | 两脚本 parity、5395 有份量食物 | 同上（builder scan vs 独立 raw scan） | `portion_map_diffs = 0` |
| 4 | beverage 判定 437 True / 194 fl_oz-but-False | 直接在现有 catalog-v2 上跑 `_is_beverage_name` | **437 / 194**，与 codex R5 完全一致 |
| 5 | 固体假阳性已清零 | lollipop / coffee cake / irish soda bread / cocktail sauce / frozen juice bar / freezer pop 逐个探针 | 全部 `None` |
| 6 | 真饮料漏判确实存在 | Kefir / Brandy / Apricot nectar / Wine cooler | 全部 `None`（漏判属实） |
| 7 | 真饮料主干未坏 | Milk whole=244 / Soft drink cola=372 / Coffee brewed=360 / Orange juice=248 | 正常解析 |
| 8 | v0.5-gold 零漂移 | 读 split 的 `catalog` + `catalog_sha256`，实测文件 sha | 绑 `archive/catalog.sqlite`，sha `ff2f2632…` **匹配** |
| 9 | 测试 1371 passed + 1 待重建 | `pytest -q` 全量 | **1371 passed, 1 failed**，唯一失败是 `test_handbook_matches_resolve_portion_on_catalog_v2`（`two chicken wings` 需要重建后才有的 `wing` 键） |

另外两项**交接材料里没有、我自己补的**验证，见第二、三节。

---

## 二、Q1 裁决：不阻断

### 2.1 先更正一条事实前提

裁决请求里写「beverage 判定是**存量功能**（handoff 前已存在），不是本轮引入」。
这条不成立：

```
git show HEAD:src/nutrienv/world/portions.py | grep -E '"glass"|_is_beverage_name'  → 无
git log -S '"glass": "serving"'  -- src/nutrienv/world/portions.py                  → 无提交
git log -S '_is_beverage_name'   -- src/nutrienv/world/portions.py                  → 无提交
```

`glass/mug/bottle → serving`、`_BEVERAGE_CONTAINER_UNITS`、`_is_beverage_name`
全部只存在于**未提交的工作树**，且 `react.py` 手册里那行 "a glass / a mug / a bottle
of X" 也在同一份 diff 里新增。它相对本轮 review 是存量，相对 `main` 不是 ——
它和 catalog-v2 的改动会进同一个 commit。

所以「存量功能可以带病共存」这条理由**我不采纳**。放行的理由必须更硬，是下面这条。

### 2.2 决定性理由：正交性（已证明，非推断）

本轮重建追加的 9 个 key 与 `_is_beverage_name` 的两个输入信号（食物名 head 末 token、
`portions.fl_oz` 是否存在）**完全不相交**。我没有停在「看起来不相交」，而是把重建后的
份量图算出来，逐食物比对：

```
重建前后 _is_beverage_name 判定翻转的食物数: 0
重建前后 fl_oz 键/值不同的食物数:            0
本轮新增 key 是否触及 fl_oz:                False
现有 catalog 带这 9 个 key 的食物:           各 0（全新键，无覆盖面）
```

即：**这次重建对 beverage 判定的输出是逐位恒等的**。Kefir 在重建前留 `None`，
重建后仍留 `None`；一个真饮料都不会因为重建而多漏或少漏。

一个既不能被本轮改善、也不能被本轮恶化的缺陷，不是本轮的验收闸门。把它设成闸门，
等于用一个无关变量卡住一批已经验证干净的改动 —— 这正是 codex R5 自己给出的判断
（「名称启发式分类器的本质极限」）所指向的结论：它是一条独立的工程债，不是本轮的
回归。

### 2.3 安全方向：漏判是 fail-closed，不产生错误克数

resolver 的契约是「`None` = ask for grams，不是 zero」，语法「故意小而全，宁可拒绝」。
代码里 beverage 门是**硬拒绝**而非跳过：

```python
if token in _BEVERAGE_CONTAINER_UNITS and not _is_beverage_name(entry):
    return None            # 不是 continue —— 不会漏到 dish-noun 兜底路径
```

因此漏判的最坏后果是「一杯 kefir」不被解析，**永远不会算出一个错的克数**。
对照 R1–R4 修掉的方向：那时是 fail-open（`a glass of lollipop` → 10 g、
`a glass of coffee cake` → 57 g、`a glass of freezer pop` → 50 g），那种才是硬违规，
因为它会把错误克数写进 Oracle。本轮已把方向从「误解析固体」翻到「拒解析部分真饮料」。
**这两类错误在判分体系里不等价**：前者污染尺子，后者只是尺子上少了一格。

### 2.4 影响面：漏判在造题期已有兜底通道

同批的 `resolver.py` 引入了 `GramAnchor`：`resolve_portion` 返回 `None` 时，允许一次
LLM 克数提议，且**只有命中该食物 portion-table 白名单才被接受**，随后写成规范化的
`"<n> g"` 表达。我核对了漏判食物的 portions：

```
2705394 Kefir           {"cup": 244.0, "fl_oz": 30.5, "qns": 244.0}
2709341 Apricot nectar  {"qns": 248.0, "fl_oz": 31.0}
2710694 Wine cooler     {"fl_oz": 30.0, "can": 330.0, "qns": 135.0}
```

`matches_portion_table` 的白名单是「每个 portion 值 × {0.5, 1, 1.5, 2}」，所以
Kefir 的 244 g、nectar 的 248 g 都在白名单内 —— 这些漏判食物**在造题期本来就能通过
表值受控的 anchor 通道回收**，anchor 未挂载时则退化为 `Rejected("unresolvable")`，
候选被丢弃，同样不进考卷。

再加一条：我 grep 过 `bench/pipeline/`，**expander 侧目前没有任何生成 glass/mug/bottle
表达的生产者**。漏判当前只影响 live expander 自由口语可能撞上的极少数措辞，
损失是造题产出率，不是判分正确性。

### 2.5 核心验收不依赖 beverage

catalog 重建的三条验收 —— 新 key 提取、零旧 key 漂移、gold 零漂移 —— 走的是
`build_fdc_catalog.py` 的 FNDDS 扫描路径。builder 只在 dry-run 报告里为了印证
staple 锚点才 `from nutrienv.world.portions import resolve_portion`（1 处），
写库路径完全不碰 resolver，更不碰 `_is_beverage_name`。

**Q1 结论：不阻断。**

---

## 三、我补的第二项验证：resolver 层前后漂移扫描

零漂移在 codex 那里是「catalog key 层面」的（removed 0 / changed 0）。但真正该关心的
是**下游语义层面**：新增 9 个单位词进 `UNIT_SYNONYMS` 后，会不会让一条**原本就能解析**
的表达悄悄换成另一个克数？（resolve_portion 是从左到右扫 token 的，新单位词理论上
可能抢在原来命中的单位之前。）交接材料没有覆盖这一层，我补跑了全量对照：

27 条探针（`a serving` / `a cup` / `one` / `a piece` / `a slice` / `a can` /
`an ounce` / `half a cup` / `a bowl` / `150 g` / `a bar` / `two sticks` / `a patty` /
`a glass` …）× 5431 个食物，用「现有 portions」与「重建后 portions」各解析一遍：

```
None -> 有值（新单位启用，预期收益）: 695
有值 -> None（丢解析）:                  0
有值 -> 不同值（静默改克数）:            0
```

**下游语义零漂移，与 catalog key 层零漂移一致。** 这是我给 APPROVE 的第二个独立支点。

新 key 的取值也抽查过，语义正确且 fail-closed：

| 单位 | 命中食物示例 | 表达 | 结果 | 无此 key 的食物 |
|---|---|---|---|---|
| wing | Chicken wing, NS as to cooking method | `two chicken wings` | 70.0 | Milk, NFS → `None` |
| drummette | Chicken wing… | `two drummettes` | 44.0 | → `None` |
| patty | Meat, ground, NFS | `a patty` | 85.0 | → `None` |
| pat | Table fat, NFS | `a pat` | 7.0 | → `None` |
| bar | Frozen yogurt bar, vanilla | `a bar` | 65.0 | → `None` |
| stick | Cheese, NFS | `two sticks` | 56.0 | → `None` |

---

## 四、Q2 处置：采纳 (a)，明确不采纳 (b)

**(a) 记为 backlog，下个 session 用显式饮料 id 清单替换名称启发式。**

理由：

1. **codex R5 的根因判断成立。** FNDDS 的真实饮料名并不总以通用饮料词结尾 ——
   品牌括号（`Energy drink (Full Throttle)` → `throttle`）、配料结构
   （`Fruit juice blend, citrus, 100% juice` → `blend`）、专有名词
   （`Bloody Mary` → `mary`、`Pina Colada` → `colada`）。这不是词表不够长，
   是「最后一个 token」这个表示本身承载不了领域分类。再长的词表也只是把
   194 个漏判换成另一批漏判 + 新的假阳性。
2. **(b) 的风险有实测记录。** R1→R5 五轮里，每一次扩大词表/放宽匹配都引入了新的
   固体假阳性：子串 → `steak`/`kale`；后缀 → `lollipop`/`swine`；整名整词 →
   `coffee cake`/`irish soda bread`/`cocktail sauce`；纯 `fl_oz` →
   `frozen juice bar`/`freezer pop`。而假阳性是**会污染 Oracle 的那一类错误**。
   用一个高风险手段去修一个零风险缺陷，方向是反的。
3. **候选池是有界的，不是开放式工作。** 我已经界定：`portions.fl_oz` 存在但
   `_is_beverage_name=False` 的食物恰好 **194** 个（现有 catalog 带 fl_oz 的共 631 个）。
   这 194 行是一次性人工/检索分诊的全部范围 —— 其中一部分（frozen dessert、cream）
   本来就该拒绝，剩下的成为显式饮料 id 白名单。这是可穷尽的一次性成本，且**不会随
   catalog 重建变化**（见 2.2：重建后这 194 项恒等）。
4. 落地形态建议：以 FDC id 为准的显式清单（可由 AGY 检索 + codex 复核），
   `_is_beverage_name` 退化为「查表」，名称启发式只作为清单缺失时的
   fail-closed 兜底。同时清掉 codex 标注的两个低优先项：未使用的
   `_BEVERAGE_NAME_WORDS` 重复词表，以及 `_BEVERAGE_HEAD_WORDS` 里
   **不可达成员 `"root beer"`**（它是双 token 字符串，永远不等于单个 `last` token）。

**不采纳 (b)**（继续扩词表）：理由见上第 2 点。
**不采纳「先修好再重建」**：理由见 2.2 正交性 —— 两件事没有先后依赖。

---

## 五、落地条件

APPROVE 的前提是下面 3 条一并执行。**条件 2 是 codex 五轮未覆盖的真实副作用，
不做会导致后续冻结出的 split 无法加载。**

### 条件 1（可执行）：重建

允许执行：

```
.venv/bin/python scripts/build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite
```

接受闸门（已在 dry-run 预验）：`removed == 0` 且 `changed == 0`。

重建完成后必须补跑并全绿：

```
.venv/bin/python -m pytest -q
```

预期从当前的 `1371 passed, 1 failed` 变为 **1372 passed** ——
`test_handbook_matches_resolve_portion_on_catalog_v2` 是唯一因缺 `wing` 键而失败的
测试，重建正是它的前置条件。**若重建后仍有任何一条失败，本 APPROVE 作废，退回 codex。**

### 条件 2（必做）：重新盖章 phase6 产物

`GOLD_CATALOG_PATH` 现在指向 `data/fdc/catalog-v2.sqlite`（不再是 handoff-ship-04
里写的 `archive/catalog.sqlite`）。重建会改变它的 sha256：

- 新增 487 个 key-食物对；
- 并且 builder 现在用 `json.dumps(value, sort_keys=True)` 写 cell，而现有
  catalog-v2 的 cell 是**未排序**的（我实测：7809 个 cell 键序不同，字节长度差 0，
  取值差 0）—— 这是 issue 13「catalog 构建可复现」的修复，属于预期内的
  **仅序列化变化**。

而 `split.py::load_split` 会硬校验 `sha256(catalog bytes) == catalog_sha256`，不匹配
直接 `raise`。当前有 **17 个 phase6 产物**钉死旧 sha `eb822b69…`：

```
reports/phase6/candidates.json、candidates-pass1.json、manifest.json、manifest-pass1.json
reports/phase6/.phase6-slots/*.json（13 个）
```

其中 `candidates*.json` 已是 split 形态（带 `version` / `catalog` / `catalog_sha256` /
`items`）。**重建后必须重跑或重新盖章 phase6，否则由它冻结出的 split 会被
`load_split` 拒绝加载。** 好消息是这批产物很小（每个 1 item，13 个 slot），
重跑成本低。

**不受影响、无需处理**（我已逐个实测确认）：

| 冻结物 | 绑定 | 重建后 |
|---|---|---|
| `v0.5-gold.json`（240 题） | `archive/catalog.sqlite`，sha `ff2f2632…` 实测匹配 | 结构性免疫（不同文件） |
| `v1.0-gold.json` / `v1.0-composite-sample.json` | `archive/catalog-v1.sqlite`，sha 实测匹配 | 不受影响 |
| `v0`–`v0.4-gold.json` | `archive/catalog.sqlite` | 不受影响 |
| 测试里的 sha 常量 | 只钉 `_LIVE_SHA256`（archive/catalog）与 `_V1_SHA256` | 两个文件都不被写 |

**没有任何测试钉死 catalog-v2 的 sha**（`test_catalog_v2_fndds_only` /
`test_catalog_build_reproducible` 是运行时 before/after 自比对，用来断言「不写这些库」，
不是常量 pin）——已 grep 确认。

### 条件 3（纪律 4，手册对称性）：已满足，但要连带提交

`react.py` 的 `_SYSTEM_V1_TAIL` 已在同一份 diff 里补上 9 个新单位与
glass/mug/bottle 那一行，`test_handbook_matches_resolve_portion_on_catalog_v2`
会在重建后强制校验二者一致。**要求：`portions.py` / `react.py` / `build_fdc_catalog.py`
与重建后的 catalog 必须进同一个 commit** —— 它们现在都还在同一个未提交工作树里，
拆开提交会出现「手册说有 wing、catalog 没有 wing」的中间态。

---

## 六、本次裁决**不**覆盖的范围

下面这些在同一份工作树里，但不属于「catalog 重建能否落地」，不在本裁决内，
需要各自的门禁：

1. **`_bare_food_noun_grams` 的 cut-noun 放宽**（`a chicken breast`：`None` → 105.0）。
   codex R2 已标为「范围蔓延｜中」，指出 round-2 规格没有给出该语义变化的依据。
   本轮 dry-run 报告已把它写进「ticket 02 仍成立」一节 —— 但那是**记录**，不是**批准**。
   它改的是判分语义，应当单独走 ticket 02 的门禁确认。
2. `expander.py` / `run_batch.py` / `GramAnchor` 的造题期改动。
3. `v2.0-gold` 是否正式切换（commit `30a63ef` 明确 revert 过一次，等 40-item review）。

---

## 裁决签署

| 项 | 裁决 |
|---|---|
| **总结论** | **APPROVE-WITH-CONDITIONS** |
| Q1 beverage 残留漏判是否阻断 | **不阻断**（正交性已证明：判定翻转 0；且 fail-closed 不产生错误克数） |
| Q2 处置 | **(a) backlog + 显式饮料 id 清单**；候选池已界定为 194 行；不采纳 (b) 扩词表 |
| 条件 1 | 重建后 `pytest -q` 必须 1372 passed；任一失败则本 APPROVE 作废 |
| 条件 2 | 重新盖章 / 重跑 17 个 phase6 产物（旧 sha `eb822b69…`） |
| 条件 3 | 代码 + 手册 + 重建后 catalog 进同一 commit |

claude (Opus)，2026-08-25
