# FNDDS 安全叠加落地报告

按 `docs/adjudication-report.md` 第 4 节验收清单实施。本报告对应落地审查（`docs/landing-review.md`）之后的修复重建：`fl_oz` 锚定为 `1 fl oz` 单位行、本轮不写 `serving`、review sheet SHA 默认失败。catalog 重建是本次唯一数据变更；gold JSON、`realizations.py`、`portions.py`、`validator.py` 均未改。

复跑：

```
.venv/bin/python scripts/build_fdc_catalog.py
.venv/bin/python scripts/landing_verify.py
.venv/bin/python -m pytest -q
```

## 实现策略：陷阱 A 严格版 (a)

`scripts/build_fdc_catalog.py` 分两段写 `portions`：

1. **冻结旧键** — 原 `_collect_portions` / `_portion_key` 一字未改（zip 文件序、first-wins）。`cup` / `tbsp` / `tsp` / `slice` / `piece` / `can` 的值与落地前 catalog 相同。
2. **只追加新键** — `_apply_safe_overlay` 按 `(fdc_id, seq_num, portion id)` 稳定排序后 first-wins。`_merge_portion` 对已有键是 no-op。

普通 overlay 行**不得**为缺失的旧类目键新增值。`_overlay_keys` 一旦看到 household 单位（cup/tbsp/tsp/slice/piece/can）立即返回空；`_apply_safe_overlay` 再用断言兜底：旧类目键除下面这条例外外一律拒绝写入。

相对 dry-run 里更宽的 `setdefault(任意键)`，这是裁决要求的严格版 (a)，不是 (b)。

## 复合 `piece/slice` 双写（唯一旧键例外）

仅当 **FNDDS 原行** `portion_description` 同时含 piece 词与 slice 词（典型 `"1 piece/slice, any size"`）时，该行双写 `piece` 与 `slice`，且 **不得覆盖** 已有值。

- 当前 builder 因 `_UNIT_PATTERNS` 里 slice 在 piece 前，复合行只落成 slice。
- 落地后：slice 保持原值；缺失的 piece 用同一克数补上。
- 已审查 `docs/review-fndds-ingestion.md` §2 的顾虑：双写限定为「原行本身就是复合描述」+ first-wins 不覆盖；不是把独立 `1 piece` 行和复合行捏成假等价。

实测：104 个食物因此补上 `piece`（全是复合行、落地前没有 piece）。gold 25 种不在其中。牛排 `2705824`：`{slice: 30, cup: 135}` 冻结，补 `piece=30`。

## oz / oz_yield 拆分（陷阱 B）

描述以 `1 oz` 起头的行：

| 条件 | 键 | 例子 |
|---|---|---|
| 含 `yield` | `oz_yield` | `1 oz yields`、`1 oz, raw (yield after cooking)`、`1 oz, dry, yields` |
| 不含 `yield` | `oz` | `1 oz, cooked`（28.35 g）、`1 oz`、`1 oz, NFS` |
| 描述以 `1 fl oz` 开头 | `fl_oz` | 液体盎司单位行，与重量 oz 分开 |
| `1 Snickers bar (2 fl oz)` / `1 soda (10 fl oz)` | 不入库 | 整份容器总重，不是每 fl_oz 克数。审查中的 3 个错误 winner（`2705640` fl_oz=50、`2705656`/`2705657` fl_oz=240）已消失 |
| `1 meal (11 oz)` / `1 6 oz container` 等 | 不入库 | 包装/餐重里的 oz 字样 |

专项检查：survey.zip 里 **42** 个食物同时有物理盎司行和得率行。落地后这 42 个全部同时带 `oz` 与 `oz_yield`，零混装。例 `2705856`：`oz=28.35`、`oz_yield=9.0`。

pasta（gold）只有 `1 oz, dry, yields=80` → 只追加 `oz_yield=80`，没有假 `oz`。

`resolve_portion` 的口语 `oz` 仍走固定 `28.35 g`，不读 catalog 的 `oz` / `oz_yield`（本轮不改 `portions.py`）。

## 新键清单

写入 catalog、**尚未**接入 `UNIT_SYNONYMS` / `react.py` 手册（验收 5；语法是后续独立变更）：

| 键 | 来源 | 本轮覆盖食物数 |
|---|---|---|
| `qns` | modifier 90000 或 description 以 `quantity not` 开头；`gram_weight <= 0` 丢弃 | 5326 |
| `fl_oz` | 仅描述以 `1 fl oz` 开头的单位行；`1 cup (8 fl oz)` 走 household 早退，`1 soda (10 fl oz)` 这类整份总重不写 | 628 |
| `regular` | 独立 `1 regular`，不含 slice/piece | 453 |
| `cubic_inch` | `1 cubic inch` | 382 |
| `oz_yield` | `1 oz` + yield | 304 |
| `oz` | `1 oz` 且非 yield | 242 |
| `thin` | 独立 `1 thin` | 56 |
| `thick` | 独立 `1 thick` | 54 |
| `piece`（复合补缺） | 见上，不是新类目 | 104 |

5393 个 FNDDS 食物至少多了一个键。旧键值变化：**0**。食物数仍是 13224，staple alias 仍是 27。

`1 large or thick slice` 仍只走旧键 slice，不会再写 `thick`。Guideline / mashed / sliced+cup 仍丢弃。

## 新键暂未接入语法（验收 5）

本轮**只做 catalog 数据层**，明确未做：

- `src/nutrienv/world/portions.py` 的 `UNIT_SYNONYMS` 没有 `qns` / `thick` / `thin` / `regular` / `oz_yield` / `fl_oz` / `cubic_inch`
- 口语 `oz` 仍是固定 28.35 g，不读表
- `react.py` 手册仍只列 cup/tbsp/tsp/slice/piece
- 没有新的 phrase→key→grams 测试

本轮**不写** `serving` 键。`UNIT_SYNONYMS` 原本就把 serving/portion/bowl/plate/order 映到 `portions["serving"]`，没有该键时回退 piece→slice→cup；写入 5 个值会立刻改变解析（审查验收 5 FAIL）。已有 5 个食物（`2706445` / `2706468` / `2707537` / `2707538` / `2710613`）的 serving 行留在 FNDDS 原表，不进 catalog。serving 语义接入是后续独立立项：同一变更里同步 `react.py` 手册 + phrase→key→grams 测试。

## 三项交叉检查（验收 6）

脚本：`scripts/landing_verify.py`（验收 3 的真实 phrase 重放，不是 `infer_key` 反推）。

| 检查 | 结果 |
|---|---|
| 240 条 `validate_draft(task) == []` | **240/240 全绿** |
| 25 种 gold 食物旧键 vs 落地前 / vs 遗产 `_collect_portions` 重扫 | **零漂移** |
| 冻结题 phrase 重放，`resolve_portion(food, phrase, 旧表) == resolve_portion(..., 新 catalog)` | **178/178 相等**，0 条不一致。口径：177 次按 query 精确匹配到 Row，1 次按 item id 推导 seed 回退（`v01-log-fz-milk-cup` → `a cup`）；145 条无份量 phrase（update/recommend/constrain/leftover）跳过 |
| 42 个 oz/oz_yield 冲突食物拆分 | **42/42 已拆，0 混装** |
| 全量 pytest | **213 passed, 0 failed**（终审基线 210；多出的 3 条是并行合入的 `validate_oracle_grams` 单测） |

gold 25 种落地后只追加新键，旧键原值未动。例如 apple `piece=200`（没有变成 165）、cheddar `slice=21` / `cup=132`（没有变成 9 / 113）。

## 顺带改动（非 catalog 数据层，但测试需要）

`scripts/build_review_sheet.py`（不在禁止修改名单里）：

1. catalog SHA 与 gold JSON 冻结哈希不一致时，**默认仍 `SystemExit`**，不得无条件降级。仅显式传入 `--allow-catalog-sha-mismatch` 才放行并打印警告。gold JSON 按裁决保持原哈希；专项 review 或 review-sheet 测试必须 opt-in。`tests/test_review_sheet.py` 的导出夹具因此带上该开关，否则恢复默认失败后无法生成 sheet。
2. `explain_grams` 只使用 `resolve_portion` 认识的单位。否则 oats 的新 `qns=10` 会把 60 g 误解释成 `6 x qns`，gloss 变 `None`，`test_grams_explained_is_derived_when_unit_unspoken` 会红。

## 未做（验收 4、7，不在本任务）

- 陷阱 C：`validate_oracle_grams` 接入 `materialize_split` — 由 reviewer 并行处理。
- judge 灰区三对（sandwich 1.5× / lasagna 1.2× / omelet 2.0×）— 仍是 judge 封 gate 的前置条件，本轮未跑。
