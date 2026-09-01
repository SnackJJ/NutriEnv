# catalog-v1 dry-run 变更清单

只读对照：完整 FNDDS 策略（`scripts/fndds_dry_run.py`）相对**当前已提交**的
`data/fdc/catalog.sqlite`。未写、未改 `catalog.sqlite`、任何 `data/splits/*.json`、
`src/**`，也未 import / 修改 `scripts/build_fdc_catalog.py`（05 的范围）。

本文件是 catalog-v1 **构建决策**用的变更清单。旧报告
`reports/dry-run-summary.md` 保持不动（那份仍按「会破坏冻结 split → 不允许重建」
框定）。完整机器可读 diffs 在 `reports/dry-run-drift.json`（该文件被 `.gitignore`，
用 `.venv/bin/python scripts/fndds_dry_run.py` 复跑生成；约 0.6 MB）。

## 框定

- **catalog-v1 是全新文件**（计划路径 `data/fdc/catalog-v1.sqlite`），不覆盖
  `data/fdc/catalog.sqlite`。
- 当前 catalog 已是 commit `2c639e8` 的 **safe-overlay**（旧键冻结 + 已追加
  qns/fl_oz/cubic_inch/serving/oz_yield 等）。v0.5 冻结 split 绑的是这份 catalog，
  SHA-256 `ff2f26325cc0cc71c3230f82060997afaeefcad0051b09989c662ac0b0fa2d90`。
- 完整策略会对旧键做 seq_num first-wins，**861 处旧键取值变化全部可接受**：
  没有冻结考试依赖 catalog-v1 的旧键。v0.5 catalog 与 `v0.5-gold.json` 零改动。
- v1.0-gold 将对照 catalog-v1 另建，不回写 v0.5。

对照输入：

- survey: `data/fdc/raw/survey.zip`
- 对照 catalog: `data/fdc/catalog.sqlite`（safe-overlay，不上盘）
- 对照 split: `data/splits/v0.5-gold.json`（240 条，version `v0.5-gold`）
- 复跑: `.venv/bin/python scripts/fndds_dry_run.py`

## 策略（与 dry-run 脚本 POLICY 一致）

1. `food_portion.csv` 按 `(fdc_id ASC, seq_num ASC, portion id ASC)` 排序后 first-wins。
2. 每个 `(fdc_id, key)` 保留排序后第一条 `gram_weight > 0`。
3. 描述同时含 piece 与 slice（典型 `1 piece/slice, any size`）时，同一克数双写两键。
4. `modifier == 90000` 或 `portion_description` 以 `quantity not` 开头 → 键 `qns`；
   `gram_weight <= 0` 丢弃（本次丢掉 1 行）。
5. Guideline / mashed / sliced+cup 行仍丢弃。household 单位优先于
   thick/thin/regular/oz（`1 large or thick slice` 仍是 slice）。
6. 新键: `thick`, `thin`, `regular`, `oz`, `fl_oz`, `cubic_inch`, `serving`, `qns`。
   包装行（`5.3 oz container`）不算 oz。

## 食物数对照

| 集合 | 数量 | 说明 |
|---|---:|---|
| catalog 内 `survey_fndds_food` | **5431** | 当前 catalog.sqlite |
| survey 提出份量（完整策略有 ≥1 键） | **5395** | food_portion 映射后 |
| 本次对比食物 | **5395** | catalog FNDDS ∪ proposed，跳过双边空份量 |
| 有任何差异 | 1221 | 相对当前 safe-overlay catalog |
| 完全零漂移 | 4174 | 旧键+新键都已一致 |

5395 vs 5431 的差来自：

- catalog 里 **37** 条 `as ingredient` FNDDS 食物份量为空、survey 也映不出键
  （recipe 组分，如 `Chicken as ingredient in recipes` / `Cheese as ingredient in sandwiches`），
  不进入对比集。
- survey 有 **1** 条 catalog 没有的食物：`2705383` Milk, human（proposed `cup=246`, `fl_oz=30.8`，无 qns）。
- 算式：`5431 − 37 + 1 = 5395`。
- 对比集里恰好零漂移的代表：`2709214` Fruit, pickled（`cup=240`, `slice=30` 已与完整策略一致）。

## 旧键变化（cup/tbsp/tsp/slice/piece/can）

相对当前 catalog，**861 种食物**的旧键取值被改。
无旧键被删除。键级变化 **894** 行（部分食物改了不止一个旧键）。
这 861 种食物的 (fdc_id, key, old→new) 与仓库里原先那份 dry-run JSON 完全一致
——safe-overlay 冻住了旧键，完整策略仍会按 seq_num 重选赢家。

按键：

| 旧键 | 取值被改的食物数 |
|---|---:|
| `cup` | 106 |
| `tbsp` | 0 |
| `tsp` | 0 |
| `slice` | 155 |
| `piece` | 606 |
| `can` | 27 |
| 合计（键级） | 894 |
| 合计（食物级） | 861 |

主因是 **seq_num 排序改变 first-wins 赢家**。典型：

- Cheddar `1 cracker-size slice`（seq 1, 9 g）先于 `1 slice`（seq 2, 21 g）→ `slice` 21→9
- Apple `1 small`（seq 1, 165 g）先于 `1 medium`（seq 2, 200 g）→ `piece` 200→165
  （small/medium/large 仍塌缩为 piece）

另有 **1** 条旧键**新增**（不算进 861）：`2705383` Milk, human 的 `cup=246`（此食物不在当前 catalog）。
safe-overlay 已经写入了复合 `1 piece/slice` 双写的 piece 键（约 104 种牛排/蛋糕/胡萝卜等），完整策略不再补这些 piece。

完整 per-food 取值变化清单见文末附录；机器可读原文在
`reports/dry-run-drift.json` 的 `diffs[].changed`（只读其中属于
cup/tbsp/tsp/slice/piece/can 的键即可复原 894 行）。

## 新键覆盖

- 对比集带 `qns`：**5326** / 5395 ≈ **98.7%**（5326/5395 ≈ 98.7%，与预期 ~99% 一致）。
- 无 `qns`：69 种。其中 67 种是婴儿/幼儿配方奶（只有 `fl_oz`），
  加上 `2705383` Milk, human（`cup`+`fl_oz`）和 `2709214` Fruit, pickled（已有 cup/slice，survey 无 QNS 行）。
- `qns_zero_gram_rows_dropped`: 1。

当前 safe-overlay catalog **已经**写入了绝大部分新键（FNDDS 中 `qns` 5326、
`fl_oz` 628、`cubic_inch` 382、`thick` 54、`thin` 56、`regular` 453 等）。
因此相对**当前** catalog，完整策略不再是「给 4500+ 食物补 qns」，而是：

| 新键 | 相对当前 catalog 新增 | 取值被改 | 被删 |
|---|---:|---:|---:|
| `thick` | 0 | 0 | 0 |
| `thin` | 0 | 0 | 1 |
| `regular` | 0 | 0 | 186 |
| `oz` | 314 | 8 | 0 |
| `fl_oz` | 4 | 0 | 0 |
| `cubic_inch` | 0 | 0 | 0 |
| `serving` | 79 | 0 | 0 |
| `qns` | 0 | 0 | 0 |

其余（非 NEW_KEYS 白名单）值得决策者看见的差异：

- `oz_yield` 被删 **304** 种食物；其中 **262** 种同时新增同克数 `oz`
  （safe-overlay 用了 `oz_yield`，完整策略的键名是 `oz`）。
- 另新增 `oz` **314** 种、`oz` 取值被改 **8** 种（多为 28.35→更具体的 seq_num 赢家）。
- `regular` 被删 186、`thin` 被删 1：household 单位或 piece 塌缩赢了，
  这些尺寸键不再写入。
- 仅新增键、旧键原值不动： **109**
  （serving=60, oz=45, fl_oz=4, cup=1）。

这些新键/键名差异不影响「861 旧键变化可接受」的结论；构建 catalog-v1 时
应按本 dry-run 的键名（`oz` 而非 `oz_yield`）落地。

## Gold 25 食物对照

v0.5-gold 用到 **25** 种食物（16 FNDDS + 9 SR Legacy）。
**2 种旧键会变**（apple、cheddar）；
**14 条 gold 行**（12 道题）的克数会随旧键一起变。
这 14 行漂移对 catalog-v1 **可接受**：v1.0-gold 将按 catalog-v1 重建，
v0.5 split 文件不会改。

### 每种食物（当前 catalog → 完整策略）

| food_id | fdc_id | 类型 | 当前 catalog 键 | 完整策略差异 | QNS |
|---|---|---|---|---|---|
| `almond` | `168592` | sr_legacy_food | cup=144 | 零漂移 | — |
| `apple` | `2709215` | FNDDS | cup=125, piece=200, qns=200, slice=25 | piece 200→165; +serving=34 | 200 |
| `avocado` | `2709223` | FNDDS | cup=150, qns=30, slice=15 | 零漂移 | 30 |
| `banana` | `2709224` | FNDDS | cup=150, piece=126, qns=126, slice=6 | 零漂移 | 126 |
| `beef` | `171793` | sr_legacy_food | — | 零漂移 | — |
| `black_beans` | `173735` | sr_legacy_food | cup=172 | 零漂移 | — |
| `broccoli` | `2709643` | FNDDS | cup=90, piece=10, qns=45 | 零漂移 | 45 |
| `cheddar` | `2705709` | FNDDS | cubic_inch=17, cup=132, qns=21, slice=21 | cup 132→113; slice 21→9 | 21 |
| `chicken_breast` | `171477` | sr_legacy_food | cup=140 | 零漂移 | — |
| `egg` | `2707152` | FNDDS | cup=245, piece=50, qns=50 | 零漂移 | 50 |
| `greek_yogurt` | `2705424` | FNDDS | cup=245, qns=150 | 零漂移 | 150 |
| `milk_whole` | `2705385` | FNDDS | cup=244, fl_oz=30.5, qns=244 | 零漂移 | 244 |
| `oats` | `2708489` | FNDDS | cup=80, qns=10 | 零漂移 | 10 |
| `olive_oil` | `171413` | sr_legacy_food | cup=216, tbsp=13.5, tsp=4.5 | 零漂移 | — |
| `orange` | `2709171` | FNDDS | cup=180, qns=154, slice=15 | 零漂移 | 154 |
| `pasta` | `2708357` | FNDDS | cup=140, oz_yield=80, qns=140 | +oz=80; -oz_yield=80 | 140 |
| `peanut_butter` | `2707537` | FNDDS | qns=32, tbsp=16 | +serving=45 | 32 |
| `potato` | `2709383` | FNDDS | cup=130, piece=230, qns=285 | 零漂移 | 285 |
| `salmon` | `171998` | sr_legacy_food | — | 零漂移 | — |
| `shrimp` | `175180` | sr_legacy_food | — | 零漂移 | — |
| `soy_milk` | `2705404` | FNDDS | cup=244, fl_oz=30.5, qns=244 | 零漂移 | 244 |
| `spinach` | `2709614` | FNDDS | cup=25, qns=13 | 零漂移 | 13 |
| `tofu` | `172448` | sr_legacy_food | cup=126 | 零漂移 | — |
| `tuna` | `171986` | sr_legacy_food | can=165 | 零漂移 | — |
| `white_rice` | `2708408` | FNDDS | cup=158, qns=118 | 零漂移 | 118 |

### 旧键被改的 gold 食物

| food_id | fdc_id | 变化 |
|---|---|---|
| `apple` | `2709215` | piece 200→165 |
| `cheddar` | `2705709` | cup 132→113; slice 21→9 |

与预期一致：apple `piece` 200→165；cheddar `cup` 132→113 且 `slice` 21→9。

### 相对当前 catalog 仍获得的新键

当前 catalog 已是 safe-overlay，所以旧 dry-run 里的「apple +qns=200」等
**已经在 catalog 里**。完整策略相对*当前* catalog 仍新增的 gold 键：

| food_id | 仍新增 | 备注 |
|---|---|---|
| `apple` | `+serving=34` | `qns=200` 已在当前 catalog |
| `peanut_butter` | `+serving=45` | `qns=32` 已在当前 catalog |
| `pasta` | `+oz=80`；`-oz_yield=80` | 同克数键名从 oz_yield 改为 oz；`qns=140` 已在 |

其余 13 种 FNDDS gold 食物（avocado / banana / broccoli / cheddar / egg /
greek_yogurt / milk_whole / oats / orange / potato / soy_milk / spinach /
white_rice）的新键已在当前 catalog，完整策略不再追加。
9 种 SR Legacy（almond / beef / black_beans / chicken_breast / olive_oil /
salmon / shrimp / tofu / tuna）survey.zip 无行，本策略不动它们。

### Gold 克数会变的 14 条

| item id | 来源 | 食物 | 键 | 旧克数 | 新克数 |
|---|---|---|---|---|---|
| `v01-log-fz-apple-piece` | `oracle.ledger_tail` | `apple` | `piece` × 1 | 200 | 165 |
| `v01-log-fz-cheddar-slice` | `oracle.ledger_tail` | `cheddar` | `slice` × 1 | 21 | 9 |
| `v02-rec-lo-cut-tight` | `s0.ledger` | `apple` | `piece` × 1 | 200 | 165 |
| `v02-rec-lo-late-snack-only` | `s0.ledger` | `apple` | `piece` × 1 | 200 | 165 |
| `v02-rec-lo-milk-allergy` | `s0.ledger` | `apple` | `piece` × 1 | 200 | 165 |
| `v02-rec-lo-potato-lunch` | `s0.ledger` | `cheddar` | `slice` × 2 | 42 | 18 |
| `v02-rec-lo-three-carb-debt` | `s0.ledger` | `apple` | `piece` × 1 | 200 | 165 |
| `v03-eval-long-chicken-potato-fixings` | `oracle.last_plan` | `cheddar` | `slice` × 1 | 21 | 9 |
| `v03-eval-pair-cheddar-apple` | `oracle.last_plan` | `apple` | `piece` × 1 | 200 | 165 |
| `v03-eval-pair-cheddar-apple` | `oracle.last_plan` | `cheddar` | `slice` × 1 | 21 | 9 |
| `v03-eval-pair-yogurt-apple` | `oracle.last_plan` | `apple` | `piece` × 1 | 200 | 165 |
| `v03-eval-single-cheddar-slice` | `oracle.last_plan` | `cheddar` | `slice` × 1 | 21 | 9 |
| `v03-eval-tri-cheddar-apple-yogurt` | `oracle.last_plan` | `apple` | `piece` × 1 | 200 | 165 |
| `v03-eval-tri-cheddar-apple-yogurt` | `oracle.last_plan` | `cheddar` | `slice` × 1 | 21 | 9 |

### Gold QNS vs serving 回退

Gold 25 里来自 FNDDS 的 **16** 种全部有 QNS（**16**）。
QNS 与当前 serving 回退（piece→slice→cup）一致：

- `apple` QNS=200 = piece 200
- `banana` QNS=126 = piece 126
- `cheddar` QNS=21 = slice 21
- `egg` QNS=50 = piece 50
- `milk_whole` QNS=244 = cup 244
- `pasta` QNS=140 = cup 140
- `soy_milk` QNS=244 = cup 244

不一致（日后改 serving 回退时的灰区候选）：

- `avocado` QNS=30 ≠ serving-default slice=15
- `broccoli` QNS=45 ≠ serving-default piece=10
- `greek_yogurt` QNS=150 ≠ serving-default cup=245
- `oats` QNS=10 ≠ serving-default cup=80
- `orange` QNS=154 ≠ serving-default slice=15
- `peanut_butter` QNS=32（无 piece/slice/cup）
- `potato` QNS=285 ≠ serving-default piece=230
- `spinach` QNS=13 ≠ serving-default cup=25
- `white_rice` QNS=118 ≠ serving-default cup=158

## 裁决（本清单的结论，待 codex 审查 + 主 agent 确认）

**catalog-v1 为全新文件，旧键 861 处变化全部可接受；v0.5 catalog.sqlite 与冻结 split 零改动。**

Gold 后果：14 条 v0.5-gold 行的克数在完整策略下会变（apple piece 200→165，
cheddar slice 21→9 / 42→18，cheddar cup 不直接出现在这 14 行里但食物级 cup 132→113）。
这对 v1.0 可接受——v1.0-gold 将对照 catalog-v1 构建，不回写 v0.5。
构建前仍须：codex 独立审查本清单 → 主 agent 裁决 → 才进入 05 写 `catalog-v1.sqlite`。

## 复现性

本次按文档命令复跑了一次 `.venv/bin/python scripts/fndds_dry_run.py`。
`reports/dry-run-drift.json` **不是**字节相同。原因不是脚本非确定，而是
磁盘上原先那份 JSON（gitignored）是对照 **safe-overlay 落地之前** 的 catalog
生成的（当时 `old` 份量还没有 qns/fl_oz/…，所以 diffs=5394、仅新增键=4533）。
当前提交的 catalog 已是 overlay，复跑得到 diffs=1221。
**861 旧键变化的 per-food 清单在两份 JSON 之间集合相等**（894 行逐条相同）。

| 产物 | SHA-256 |
|---|---|
| 复跑前本地 `dry-run-drift.json`（过期对照） | `d244328f88dc32985489b74cc3d6efb5efd6a999920a78d23f80f93fce71f647` |
| 复跑后 `dry-run-drift.json`（对照当前 catalog） | `2cb3c1a20933658316afbb2ba6822c81b2e7d0cc6baecaa41d236e3fd20ce8b0` |
| 复跑前/后 `dry-run-summary.md`（已 checkout 回提交版，未改） | `d9e73ec534f3685b2c967da5328593e36c31d8a7b67502e39b9581f69313501d` |
| 当前 `data/fdc/catalog.sqlite`（未改） | `ff2f26325cc0cc71c3230f82060997afaeefcad0051b09989c662ac0b0fa2d90` |
| 当前 `data/splits/v0.5-gold.json`（未改） | `bb4f246044308670f567c24bc6b099e23f617268b532a088c27187dbda66e520` |

说明：`.gitignore` 忽略 `reports/dry-run-drift.json`，它从未进 git；
「committed dry-run JSON」实际不存在。可复现的是脚本 + 当前 catalog → 上述复跑后哈希。
复跑会改写 `dry-run-summary.md` 的统计段（5394→1221 等）；本任务已把该文件恢复为提交版。

## 附录：861 食物旧键取值变化完整清单

列：食物名、fdc_id、键、当前 catalog 克数 → 完整策略克数。按键分节，节内按 fdc_id。
仅取值变化（861 食物 / 894 行）。Milk, human 的新增 `cup` 不在此列。

### `cup`（106）

| 食物 | fdc_id | 旧 g | 新 g |
|---|---|---:|---:|
| Ice cream, NFS | `2705629` | 120 | 135 |
| Ice cream, vanilla | `2705630` | 360 | 135 |
| Ice cream, vanilla, with additional ingredients | `2705631` | 125 | 140 |
| Ice cream, chocolate | `2705632` | 360 | 135 |
| Ice cream, chocolate, with additional ingredients | `2705633` | 125 | 140 |
| Gelato, vanilla | `2705636` | 160 | 175 |
| Light ice cream, NFS | `2705664` | 240 | 135 |
| Light ice cream, chocolate | `2705666` | 240 | 135 |
| Sherbet, all flavors | `2705677` | 480 | 175 |
| Cheese, Brie | `2705708` | 144 | 240 |
| Cheese, Cheddar | `2705709` | 132 | 113 |
| Cheese, Cheddar, nonfat or fat free | `2705711` | 140 | 113 |
| Cheese, Colby Jack | `2705713` | 244 | 113 |
| Cheese, Fontina | `2705715` | 132 | 108 |
| Cheese, Gruyere | `2705718` | 132 | 108 |
| Cheese, Monterey | `2705720` | 132 | 113 |
| Cheese, Muenster | `2705726` | 132 | 113 |
| Cheese, Port du Salut | `2705732` | 113 | 132 |
| Cheese, Swiss, reduced sodium | `2705736` | 108 | 132 |
| Cheese, Swiss, reduced fat | `2705737` | 108 | 132 |
| Cheese, Swiss, nonfat or fat free | `2705738` | 108 | 132 |
| Cheese, Mexican blend | `2705741` | 244 | 113 |
| Queso Asadero | `2705744` | 113 | 132 |
| Cheese, cottage, dry curd | `2705753` | 210 | 145 |
| Cheese, American | `2705764` | 140 | 113 |
| Cheese, American, nonfat or fat free | `2705766` | 132 | 113 |
| Cheese, American, reduced sodium | `2705767` | 113 | 140 |
| Cheese spread, American or Cheddar cheese base, reduced fat | `2705768` | 113 | 140 |
| Cheese, processed, with vegetables | `2705771` | 113 | 244 |
| Corned beef hash | `2706477` | 190 | 220 |
| Stewed pig's feet, Puerto Rican style | `2706518` | 206 | 184 |
| Stewed rabbit, Puerto Rican style, | `2706661` | 177 | 219 |
| Egg substitute, omelet, scrambled, or fried, with cheese | `2707300` | 55 | 135 |
| Egg substitute, omelet, scrambled, or fried, with meat | `2707301` | 55 | 135 |
| Egg substitute, omelet, scrambled, or fried, with vegetables | `2707302` | 55 | 135 |
| Egg substitute, omelet, scrambled, or fried, with cheese and meat | `2707303` | 55 | 135 |
| Egg substitute, omelet, scrambled, or fried, with cheese and vegetables | `2707304` | 55 | 135 |
| Egg substitute, omelet, scrambled, or fried, with meat and vegetables | `2707305` | 55 | 135 |
| Egg substitute, omelet, scrambled, or fried, with cheese, meat, and vegetables | `2707306` | 55 | 135 |
| Chicken, meatless, breaded, fried | `2707469` | 130 | 168 |
| Peanuts, roasted, unsalted | `2707516` | 51 | 146 |
| Peanuts, dry roasted, lightly salted | `2707518` | 51 | 146 |
| Pistachio nuts, NFS | `2707527` | 58 | 128 |
| Pistachio nuts, unsalted | `2707530` | 58 | 128 |
| Pumpkin seeds, NFS | `2707579` | 46 | 144 |
| Pumpkin seeds, salted | `2707580` | 46 | 144 |
| Sunflower seeds, plain, unsalted | `2707582` | 46 | 144 |
| Sunflower seeds, plain, salted | `2707583` | 46 | 144 |
| Sunflower seeds, flavored | `2707584` | 46 | 144 |
| Bread stuffing | `2707687` | 200 | 228 |
| Cookie, animal | `2707968` | 105 | 64 |
| Crackers, butter, plain | `2708146` | 60 | 50 |
| Crackers, butter (Ritz) | `2708148` | 60 | 50 |
| Crackers, butter, reduced fat | `2708149` | 60 | 50 |
| Crackers, cheese, whole grain | `2708155` | 60 | 50 |
| Popcorn, NFS | `2708216` | 193 | 14 |
| Popcorn, air-popped, no butter added | `2708219` | 135 | 8 |
| Popcorn, popped in oil, no butter added | `2708221` | 177 | 11 |
| Popcorn, popped in oil, with added butter | `2708222` | 193 | 14 |
| Buckwheat groats | `2708362` | 500 | 170 |
| Grits, NFS | `2708363` | 965 | 240 |
| Grits, regular or quick, made with water, no added fat | `2708365` | 965 | 240 |
| Oatmeal, NFS | `2708380` | 485 | 240 |
| Oatmeal, regular or quick, made with water, no added fat | `2708381` | 485 | 240 |
| Oatmeal, regular or quick, made with non-dairy milk, no added fat | `2708385` | 485 | 240 |
| Oatmeal, regular or quick, made with non-dairy milk, fat added | `2708386` | 485 | 240 |
| Oatmeal, instant, plain, made with water, no added fat | `2708387` | 210 | 240 |
| Oatmeal, instant, plain, made with water, fat added | `2708388` | 170 | 240 |
| Oatmeal, instant, plain, made with milk, no added fat | `2708389` | 210 | 240 |
| Oatmeal, instant, plain, made with milk, fat added | `2708390` | 170 | 240 |
| Oatmeal, instant, plain, made with non-dairy milk, no added fat | `2708391` | 210 | 240 |
| Oatmeal, instant, plain, made with non-dairy milk, fat added | `2708392` | 210 | 240 |
| Oatmeal, instant, maple flavored, no added fat | `2708393` | 170 | 240 |
| Oatmeal, instant, fruit flavored, no added fat | `2708395` | 170 | 240 |
| Oatmeal, multigrain | `2708398` | 485 | 240 |
| Cream of rice | `2708415` | 815 | 240 |
| Cream of wheat, regular or quick, made with water, no added fat | `2708434` | 965 | 240 |
| Cream of wheat, regular or quick, made with water, fat added | `2708435` | 965 | 240 |
| Cream of wheat, instant, made with water, no added fat | `2708436` | 965 | 240 |
| Cream of wheat, instant, made with water, fat added | `2708437` | 965 | 240 |
| Bulgur, no added fat | `2708438` | 690 | 140 |
| Bulgur, NS as to fat | `2708440` | 690 | 140 |
| Whole wheat cereal, cooked | `2708442` | 705 | 240 |
| Wheat cereal, chocolate flavored, cooked | `2708443` | 705 | 240 |
| Oat bran cereal, cooked | `2708444` | 500 | 240 |
| Pasta with tomato-based sauce, and added vegetables, ready-to-heat | `2708835` | 213 | 250 |
| Pasta with tomato-based sauce and meat, ready-to-heat | `2708839` | 213 | 250 |
| Pasta with tomato-based sauce, meat, and added vegetables, ready-to-heat | `2708842` | 213 | 250 |
| Pasta with tomato-based sauce, poultry, and added vegetables, ready-to-heat | `2708848` | 213 | 250 |
| Pasta with tomato-based sauce and seafood, ready-to-heat | `2708851` | 213 | 250 |
| Pasta with tomato-based sauce, seafood, and added vegetables, ready-to-heat | `2708854` | 213 | 250 |
| Pasta with cream sauce and meat, ready-to-heat | `2708863` | 213 | 250 |
| Pasta with cream sauce, meat, and added vegetables, ready-to-heat | `2708866` | 213 | 250 |
| Pasta with cream sauce and poultry, ready-to-heat | `2708869` | 213 | 250 |
| Pasta with cream sauce, poultry, and added vegetables, ready-to-heat | `2708872` | 213 | 250 |
| Pasta, whole grain, with tomato-based sauce and meat, ready-to-heat | `2708887` | 213 | 250 |
| Pasta, whole grain, with tomato-based sauce, meat, and added vegetables, ready-to-heat | `2708890` | 213 | 250 |
| Pasta, whole grain, with tomato-based sauce and seafood, ready-to-heat | `2708899` | 213 | 250 |
| Pasta, whole grain, with cream sauce, ready-to-heat | `2708905` | 213 | 250 |
| Pasta, whole grain, with cream sauce, and added vegetables, ready-to-heat | `2708908` | 213 | 250 |
| Pasta, whole grain, with cream sauce and meat, ready-to-heat | `2708911` | 213 | 250 |
| Pasta, whole grain, with cream sauce, poultry, and added vegetables, ready-to-heat | `2708920` | 213 | 250 |
| Pasta, whole grain, with cream sauce and seafood, ready-to-heat | `2708923` | 213 | 250 |
| Soupy rice with chicken, Puerto Rican style | `2708974` | 263 | 215 |
| Flavored rice and pasta mixture | `2709082` | 196 | 184 |
| Water, tap | `2710707` | 110 | 240 |

### `tbsp`（0）

无。

### `tsp`（0）

无。

### `slice`（155）

| 食物 | fdc_id | 旧 g | 新 g |
|---|---|---:|---:|
| Cheese, Cheddar | `2705709` | 21 | 9 |
| Cheese, Colby | `2705712` | 21 | 9 |
| Cheese, Gouda or Edam | `2705717` | 21 | 9 |
| Cheese, Monterey, reduced fat | `2705721` | 21 | 9 |
| Cheese, Mozzarella, NFS | `2705722` | 21 | 9 |
| Cheese, Mozzarella, part skim | `2705723` | 21 | 9 |
| Cheese, Mozzarella, nonfat or fat free | `2705725` | 21 | 9 |
| Cheese, Provolone | `2705733` | 21 | 9 |
| Cheese, Swiss | `2705735` | 21 | 9 |
| Cheese, Swiss, reduced fat | `2705737` | 21 | 9 |
| Cheese, Swiss, nonfat or fat free | `2705738` | 21 | 9 |
| Cheese, Cheddar, reduced sodium | `2705739` | 21 | 9 |
| Queso Asadero | `2705744` | 21 | 9 |
| Queso Fresco | `2705745` | 21 | 9 |
| Cheese, American and Swiss blends | `2705763` | 21 | 9 |
| Cheese, American | `2705764` | 21 | 9 |
| Cheese, American, reduced fat | `2705765` | 21 | 9 |
| Cheese, American, nonfat or fat free | `2705766` | 21 | 9 |
| Cheese, processed, with vegetables | `2705771` | 21 | 9 |
| Ham | `2705878` | 90 | 60 |
| Pork, roast | `2705882` | 90 | 60 |
| Bacon, NS as to type of meat, cooked | `2705885` | 8 | 5 |
| Pork bacon, NS as to fresh, smoked or cured, cooked | `2705887` | 8 | 5 |
| Pork bacon, NS as to fresh, smoked or cured, reduced sodium, cooked | `2705888` | 8 | 5 |
| Pork bacon, smoked or cured, cooked | `2705889` | 12 | 5 |
| Pork bacon, smoked or cured, reduced sodium, cooked | `2705891` | 12 | 5 |
| Fat back, cooked | `2705892` | 47 | 26 |
| Chicken breast, NS as to cooking method, skin eaten | `2705953` | 60 | 30 |
| Chicken breast, NS as to cooking method, skin not eaten | `2705954` | 60 | 30 |
| Chicken breast, baked, broiled, or roasted, skin eaten, from raw | `2705955` | 60 | 30 |
| Chicken breast, baked, broiled, or roasted, skin not eaten, from raw | `2705956` | 85 | 30 |
| Chicken breast, baked or broiled, skin not eaten, from pre-cooked | `2705958` | 60 | 30 |
| Chicken breast, baked or broiled, skin not eaten, from fast food / restaurant | `2705960` | 85 | 30 |
| Chicken breast, baked, broiled, or roasted with marinade, skin eaten, from raw | `2705961` | 85 | 30 |
| Chicken breast, baked, broiled, or roasted with marinade, skin not eaten, from raw | `2705962` | 60 | 30 |
| Chicken breast, rotisserie, skin eaten | `2705963` | 85 | 30 |
| Chicken breast, stewed, skin eaten | `2705965` | 85 | 30 |
| Chicken breast, stewed, skin not eaten | `2705966` | 85 | 30 |
| Chicken breast, grilled without sauce, skin eaten | `2705967` | 85 | 30 |
| Chicken breast, grilled without sauce, skin not eaten | `2705968` | 85 | 30 |
| Chicken breast, grilled with sauce, skin eaten | `2705969` | 60 | 30 |
| Chicken breast, grilled with sauce, skin not eaten | `2705970` | 85 | 30 |
| Chicken breast, sauteed, skin eaten | `2705971` | 60 | 30 |
| Chicken breast, fried, coated, skin / coating eaten, from raw | `2705973` | 85 | 30 |
| Chicken breast, fried, coated, skin / coating not eaten, from raw | `2705974` | 85 | 30 |
| Chicken breast, fried, coated, skin / coating eaten, from pre-cooked | `2705976` | 85 | 30 |
| Chicken breast, fried, coated, skin / coating not eaten, from fast food / restaurant | `2705979` | 85 | 30 |
| Turkey, NFS | `2706104` | 60 | 30 |
| Turkey, light meat, skin not eaten | `2706105` | 85 | 30 |
| Turkey, dark meat, roasted, skin not eaten | `2706111` | 60 | 30 |
| Turkey, dark meat, roasted, skin eaten | `2706112` | 85 | 30 |
| Turkey, light and dark meat, roasted, skin not eaten | `2706113` | 85 | 30 |
| Turkey, light and dark meat, roasted, skin eaten | `2706114` | 85 | 30 |
| Turkey, light or dark meat, fried, coated, skin eaten | `2706116` | 57 | 28 |
| Turkey, light or dark meat, stewed, skin not eaten | `2706117` | 57 | 28 |
| Turkey, light or dark meat, smoked, skin not eaten | `2706120` | 85 | 28 |
| Turkey bacon, cooked | `2706135` | 11 | 8 |
| Turkey bacon, reduced sodium, cooked | `2706136` | 11 | 8 |
| Blood sausage | `2706173` | 25 | 8 |
| Meat loaf made with beef | `2706499` | 144 | 86 |
| Meat loaf made with beef, with tomato-based sauce | `2706500` | 137 | 109 |
| Meat loaf made with chicken or turkey | `2706547` | 108 | 86 |
| Meat loaf made with beef and pork | `2706581` | 144 | 86 |
| Meat loaf made with beef and pork, with tomato-based sauce | `2706583` | 137 | 109 |
| Bread, NS as to major flour | `2707591` | 13 | 24 |
| Bread, NS as to major flour, toasted | `2707592` | 25 | 22 |
| Bread, made from home recipe or purchased at a bakery, NS as to major flour | `2707593` | 44 | 33 |
| Bread, white | `2707598` | 28 | 24 |
| Bread, white, toasted | `2707599` | 25 | 22 |
| Bread, white with whole wheat swirl | `2707602` | 10 | 24 |
| Bread, white with whole wheat swirl, toasted | `2707603` | 25 | 22 |
| Bread, Cuban | `2707604` | 20 | 10 |
| Bread, Cuban, toasted | `2707605` | 27 | 9 |
| Bread, French or Vienna, toasted | `2707611` | 9 | 29 |
| Bread, Italian, Grecian, Armenian | `2707614` | 14 | 24 |
| Bread, Italian, Grecian, Armenian, toasted | `2707615` | 13 | 22 |
| Bread, cheese | `2707618` | 13 | 24 |
| Bread, cheese, toasted | `2707619` | 25 | 22 |
| Bread, cinnamon | `2707620` | 43 | 24 |
| Bread, cornmeal and molasses | `2707622` | 10 | 24 |
| Bread, cornmeal and molasses, toasted | `2707623` | 29 | 22 |
| Bread, egg, Challah, toasted | `2707625` | 28 | 18 |
| Garlic bread, NFS | `2707626` | 41 | 39 |
| Garlic bread, from fast food / restaurant | `2707627` | 111 | 37 |
| Garlic bread, from frozen | `2707628` | 111 | 37 |
| Garlic bread, with parmesan cheese, from fast food / restaurant | `2707629` | 41 | 39 |
| Garlic bread, with melted cheese, from fast food / restaurant | `2707631` | 48 | 44 |
| Garlic bread, with melted cheese, from frozen | `2707632` | 88 | 44 |
| Bread, onion | `2707633` | 43 | 24 |
| Bread, reduced calorie and/or high fiber, white or NFS | `2707635` | 10 | 24 |
| Bread, reduced calorie and/or high fiber, white or NFS, with fruit and/or nuts, toasted | `2707638` | 26 | 22 |
| Bread, high protein, toasted | `2707641` | 9 | 22 |
| Bread, potato | `2707642` | 43 | 26 |
| Bread, potato, toasted | `2707643` | 31 | 24 |
| Bread, raisin | `2707644` | 13 | 24 |
| Bread, raisin, toasted | `2707645` | 39 | 22 |
| Bread, sour dough | `2707646` | 10 | 24 |
| Bread, sour dough, toasted | `2707647` | 9 | 22 |
| Bread, sweet potato | `2707648` | 10 | 24 |
| Bread, sweet potato, toasted | `2707649` | 25 | 22 |
| Bruschetta | `2707652` | 32 | 43 |
| Bread, whole grain white | `2707706` | 10 | 16 |
| Bread, whole grain white, toasted | `2707707` | 22 | 39 |
| Bread, whole wheat | `2707709` | 10 | 24 |
| Bread, whole wheat, made from home recipe or purchased at bakery | `2707711` | 44 | 33 |
| Bread, whole wheat, made from home recipe or purchased at bakery, toasted | `2707712` | 18 | 30 |
| Bread, whole wheat, with raisins | `2707716` | 16 | 43 |
| Bread, whole wheat, with raisins, toasted | `2707717` | 33 | 39 |
| Bread, wheat or cracked wheat | `2707720` | 24 | 43 |
| Bread, wheat or cracked wheat, toasted | `2707721` | 9 | 39 |
| Bread, wheat or cracked wheat, made from home recipe or purchased at bakery | `2707722` | 20 | 33 |
| Bread, wheat or cracked wheat, with raisins | `2707724` | 28 | 43 |
| Bread, wheat or cracked wheat, with raisins, toasted | `2707725` | 12 | 39 |
| Bread, wheat or cracked wheat, reduced calorie and/or high fiber | `2707726` | 10 | 24 |
| Bread, wheat or cracked wheat, reduced calorie and/or high fiber, toasted | `2707727` | 25 | 22 |
| Bread, French or Vienna, whole wheat | `2707728` | 28 | 31 |
| Bread, French or Vienna, whole wheat, toasted | `2707729` | 59 | 28 |
| Bread, rye | `2707755` | 43 | 10 |
| Bread, rye, toasted | `2707756` | 22 | 13.5 |
| Bread, pumpernickel | `2707760` | 32 | 10 |
| Bread, pumpernickel, toasted | `2707761` | 13 | 22 |
| Bread, black | `2707764` | 10 | 24 |
| Bread, black, toasted | `2707765` | 25 | 22 |
| Bread, oatmeal | `2707768` | 25 | 43 |
| Bread, oatmeal, toasted | `2707769` | 25 | 39 |
| Bread, oat bran | `2707770` | 24 | 43 |
| Bread, oat bran, toasted | `2707771` | 22 | 39 |
| Bread, multigrain, toasted | `2707776` | 39 | 15 |
| Bread, multigrain | `2707777` | 24 | 16 |
| Bread, multigrain, with raisins | `2707778` | 43 | 24 |
| Bread, multigrain, reduced calorie and/or high fiber | `2707780` | 43 | 24 |
| Bread, multigrain, reduced calorie and/or high fiber, toasted | `2707781` | 9 | 22 |
| Bread, barley, toasted | `2707789` | 25 | 22 |
| Bread, soy | `2707790` | 43 | 24 |
| Bread, soy, toasted | `2707791` | 9 | 22 |
| Bread, sunflower meal | `2707792` | 43 | 24 |
| Bread, sunflower meal, toasted | `2707793` | 25 | 22 |
| Bread, rice | `2707794` | 28 | 24 |
| Bread, rice, toasted | `2707795` | 9 | 22 |
| Cake or cupcake, chocolate with white icing, bakery | `2707864` | 170 | 115 |
| Cake or cupcake, chocolate with white icing, from mix | `2707865` | 225 | 100 |
| Cake or cupcake, chocolate with chocolate icing, bakery | `2707866` | 170 | 115 |
| Cake or cupcake, chocolate with chocolate icing, from mix | `2707867` | 150 | 100 |
| Cake or cupcake, chocolate, no icing | `2707868` | 100 | 65 |
| Cake or cupcake, white with white icing, bakery | `2707891` | 170 | 115 |
| Cake or cupcake, white with white icing, from mix | `2707892` | 225 | 100 |
| Cake or cupcake, white with chocolate icing, bakery | `2707893` | 260 | 115 |
| Cake or cupcake, white with chocolate icing, from mix | `2707894` | 150 | 100 |
| Cake or cupcake, white, no icing | `2707895` | 100 | 65 |
| Pie, blueberry | `2707998` | 250 | 75 |
| Pie, cherry | `2707999` | 250 | 75 |
| Pie, peach | `2708002` | 150 | 75 |
| Pie, pumpkin | `2708011` | 250 | 75 |
| Pie, sweet potato | `2708012` | 150 | 75 |
| Pie, pecan | `2708015` | 250 | 75 |

### `piece`（606）

| 食物 | fdc_id | 旧 g | 新 g |
|---|---|---:|---:|
| Milk shake, fast food, chocolate | `2705508` | 690 | 405 |
| Milk shake, fast food, flavors other than chocolate | `2705509` | 690 | 405 |
| Fruit smoothie juice drink, with dairy | `2705516` | 864 | 540 |
| Beef, ground, patty | `2705855` | 120 | 65 |
| Chicken breast, baked, broiled, or roasted, skin eaten, from raw | `2705955` | 145 | 110 |
| Chicken breast, baked, broiled, or roasted, skin not eaten, from raw | `2705956` | 135 | 105 |
| Chicken breast, baked or broiled, skin eaten, from pre-cooked | `2705957` | 145 | 110 |
| Chicken breast, baked or broiled, skin not eaten, from pre-cooked | `2705958` | 120 | 105 |
| Chicken breast, grilled without sauce, skin eaten | `2705967` | 145 | 110 |
| Chicken breast, grilled with sauce, skin eaten | `2705969` | 175 | 150 |
| Chicken breast, grilled with sauce, skin not eaten | `2705970` | 185 | 140 |
| Chicken breast, sauteed, skin not eaten | `2705972` | 135 | 105 |
| Chicken breast, fried, coated, skin / coating eaten, from raw | `2705973` | 175 | 150 |
| Chicken breast, fried, coated, skin / coating not eaten, from raw | `2705974` | 120 | 105 |
| Chicken breast, fried, coated, prepared skinless, coating eaten, from raw | `2705975` | 165 | 140 |
| Chicken breast, fried, coated, skin / coating eaten, from pre-cooked | `2705976` | 195 | 150 |
| Chicken breast, fried, coated, skin / coating not eaten, from pre-cooked | `2705977` | 120 | 105 |
| Chicken breast, baked, coated, skin / coating eaten | `2705980` | 175 | 150 |
| Chicken breast, baked, coated, skin / coating not eaten | `2705981` | 135 | 105 |
| Chicken leg, drumstick and thigh, baked or broiled, skin eaten | `2705984` | 185 | 120 |
| Chicken leg, drumstick and thigh, stewed, skin eaten | `2705988` | 200 | 130 |
| Chicken leg, drumstick and thigh, stewed, skin not eaten | `2705989` | 130 | 110 |
| Chicken leg, drumstick and thigh, grilled without sauce, skin eaten | `2705990` | 140 | 120 |
| Chicken leg, drumstick and thigh, grilled with sauce, skin eaten | `2705992` | 195 | 165 |
| Chicken leg, drumstick and thigh, grilled with sauce, skin not eaten | `2705993` | 240 | 155 |
| Chicken leg, drumstick and thigh, sauteed, skin eaten | `2705994` | 185 | 120 |
| Chicken leg, drumstick and thigh, sauteed, skin not eaten | `2705995` | 120 | 105 |
| Chicken leg, drumstick and thigh, fried, coated, skin / coating eaten | `2705996` | 250 | 165 |
| Chicken leg, drumstick and thigh, baked, coated, skin / coating not eaten | `2705999` | 155 | 105 |
| Chicken drumstick, baked, broiled, or roasted, skin not eaten, from raw | `2706003` | 50 | 40 |
| Chicken drumstick, baked or broiled, skin not eaten, from pre-cooked | `2706005` | 65 | 40 |
| Chicken drumstick, grilled without sauce, skin eaten | `2706010` | 60 | 45 |
| Chicken drumstick, grilled without sauce, skin not eaten | `2706011` | 65 | 40 |
| Chicken drumstick, grilled with sauce, skin eaten | `2706012` | 110 | 65 |
| Chicken drumstick, grilled with sauce, skin not eaten | `2706013` | 75 | 55 |
| Chicken drumstick, stewed, skin eaten | `2706014` | 90 | 50 |
| Chicken drumstick, stewed, skin not eaten | `2706015` | 70 | 45 |
| Chicken drumstick, sauteed, skin not eaten | `2706017` | 65 | 40 |
| Chicken drumstick, fried, coated, skin / coating eaten, from raw | `2706018` | 110 | 65 |
| Chicken drumstick, fried, coated, skin / coating not eaten, from raw | `2706019` | 65 | 40 |
| Chicken drumstick, fried, coated, prepared skinless, coating eaten, from raw | `2706020` | 80 | 45 |
| Chicken drumstick, baked, coated, skin / coating eaten | `2706025` | 85 | 65 |
| Chicken drumstick, baked, coated, skin / coating not eaten | `2706026` | 65 | 40 |
| Chicken thigh, baked, broiled, or roasted, skin eaten, from raw | `2706029` | 105 | 75 |
| Chicken thigh, baked, broiled, or roasted, skin not eaten, from raw | `2706030` | 90 | 65 |
| Chicken thigh, stewed, skin eaten | `2706037` | 90 | 80 |
| Chicken thigh, grilled with sauce, skin eaten | `2706041` | 110 | 100 |
| Chicken thigh, grilled with sauce, skin not eaten | `2706042` | 100 | 90 |
| Chicken thigh, sauteed, skin eaten | `2706043` | 105 | 75 |
| Chicken thigh, sauteed, skin not eaten | `2706044` | 90 | 65 |
| Chicken thigh, fried, coated, skin / coating eaten, from raw | `2706045` | 140 | 100 |
| Chicken thigh, fried, coated, skin / coating not eaten, from raw | `2706046` | 90 | 65 |
| Chicken thigh, fried, coated, prepared skinless, coating eaten, from raw | `2706047` | 100 | 90 |
| Chicken thigh, fried, coated, skin / coating eaten, from pre-cooked | `2706048` | 140 | 100 |
| Chicken thigh, fried, coated, skin / coating not eaten, from pre-cooked | `2706049` | 90 | 65 |
| Chicken thigh, baked, coated, skin / coating eaten | `2706054` | 140 | 100 |
| Chicken thigh, baked, coated, skin / coating not eaten | `2706055` | 90 | 65 |
| Turkey, drumstick, cooked, skin not eaten | `2706121` | 270 | 130 |
| Turkey, drumstick, roasted, skin not eaten | `2706123` | 260 | 115 |
| Turkey, drumstick, roasted, skin eaten | `2706124` | 205 | 125 |
| Turkey, thigh, cooked, skin eaten | `2706125` | 300 | 225 |
| Turkey, thigh, cooked, skin not eaten | `2706126` | 275 | 205 |
| Turkey, neck | `2706127` | 155 | 115 |
| Turkey, wing, cooked, skin eaten | `2706129` | 240 | 90 |
| Fish, NS as to type, baked or broiled | `2706225` | 135 | 90 |
| Fish, NS as to type, fried | `2706227` | 135 | 90 |
| Fish, catfish, NFS | `2706234` | 135 | 90 |
| Fish, catfish, baked or broiled | `2706235` | 135 | 90 |
| Fish, catfish, baked or broiled, coated | `2706237` | 135 | 90 |
| Fish, catfish, steamed | `2706239` | 135 | 90 |
| Fish, cod, NFS | `2706240` | 210 | 140 |
| Fish, cod, fried | `2706244` | 210 | 140 |
| Fish, cod, steamed | `2706245` | 210 | 140 |
| Fish, flounder, grilled | `2706250` | 135 | 90 |
| Fish, flounder, baked or broiled, coated | `2706251` | 135 | 90 |
| Fish, flounder, fried | `2706252` | 135 | 90 |
| Fish, haddock, NFS | `2706254` | 210 | 140 |
| Fish, haddock, grilled | `2706256` | 210 | 140 |
| Fish, haddock, baked or broiled, coated | `2706257` | 210 | 140 |
| Fish, haddock, fried | `2706258` | 210 | 140 |
| Fish, mackerel, NFS | `2706263` | 210 | 140 |
| Fish, mackerel, baked or broiled | `2706264` | 210 | 140 |
| Fish, mackerel, baked or broiled, coated | `2706266` | 210 | 140 |
| Fish, mackerel, fried | `2706267` | 210 | 140 |
| Fish, perch, grilled | `2706272` | 135 | 90 |
| Fish, perch, baked or broiled, coated | `2706273` | 135 | 90 |
| Fish, perch, steamed | `2706275` | 135 | 90 |
| Fish, pompano, NFS | `2706277` | 135 | 90 |
| Fish, pompano, grilled | `2706279` | 135 | 90 |
| Fish, pompano, baked or broiled, coated | `2706280` | 135 | 90 |
| Fish, pompano, steamed | `2706282` | 135 | 90 |
| Fish, salmon, grilled | `2706287` | 210 | 140 |
| Fish, salmon, baked or broiled, coated | `2706288` | 210 | 140 |
| Fish, salmon, steamed | `2706290` | 210 | 140 |
| Fish, bass, NFS | `2706294` | 135 | 90 |
| Fish, bass, fried | `2706298` | 135 | 90 |
| Fish, trout, grilled | `2706304` | 135 | 90 |
| Fish, trout, baked or broiled, coated | `2706305` | 135 | 90 |
| Fish, trout, steamed | `2706307` | 135 | 90 |
| Fish, whiting, grilled | `2706314` | 135 | 90 |
| Fish, whiting, baked or broiled, coated | `2706315` | 135 | 90 |
| Fish, whiting, fried | `2706316` | 135 | 90 |
| Fish, tilapia, baked or broiled | `2706319` | 135 | 90 |
| Fish, tilapia, baked or broiled, coated | `2706321` | 135 | 90 |
| Fish, tilapia, steamed | `2706323` | 135 | 90 |
| Fish, white, mixed species, NFS | `2706324` | 135 | 90 |
| Fish, white, mixed species, baked or broiled | `2706325` | 135 | 90 |
| Fish, white, mixed species, baked or broiled, coated | `2706326` | 135 | 90 |
| Fish, white, mixed species, fried | `2706327` | 135 | 90 |
| Fish, white, mixed species, grilled | `2706329` | 135 | 90 |
| Shrimp, NFS | `2706360` | 15 | 10 |
| Shrimp, baked or broiled | `2706361` | 15 | 10 |
| Shrimp, grilled | `2706362` | 15 | 10 |
| Shrimp, steamed or boiled | `2706363` | 15 | 10 |
| Shrimp, fried | `2706364` | 15 | 10 |
| Shrimp, baked or broiled, coated | `2706365` | 15 | 10 |
| Beef with gravy | `2706379` | 158 | 83 |
| Meat loaf made with beef | `2706499` | 101 | 14 |
| Meat loaf made with beef, with tomato-based sauce | `2706500` | 36 | 18 |
| Meat loaf made with ham | `2706504` | 28 | 14 |
| Meat loaf made with chicken or turkey | `2706547` | 42 | 14 |
| Meat loaf made with chicken or turkey, with tomato-based sauce | `2706548` | 36 | 18 |
| Meat loaf made with beef and pork | `2706581` | 81 | 14 |
| Meat loaf made with beef, veal and pork | `2706582` | 134 | 14 |
| Meat loaf made with beef and pork, with tomato-based sauce | `2706583` | 103 | 18 |
| Beef, ground, with egg and onion | `2706748` | 113 | 68 |
| Egg salad, made with mayonnaise | `2707182` | 82 | 68 |
| Egg salad, made with light mayonnaise | `2707183` | 74 | 68 |
| Egg salad, made with mayonnaise-type salad dressing | `2707184` | 74 | 68 |
| Egg salad, made with light mayonnaise-type salad dressing | `2707185` | 74 | 68 |
| Egg salad, made with creamy dressing | `2707186` | 82 | 68 |
| Egg salad, made with light creamy dressing | `2707187` | 82 | 68 |
| Egg salad, made with light Italian dressing | `2707189` | 74 | 68 |
| Egg Salad, made with any type of fat free dressing | `2707190` | 74 | 68 |
| Bean chips | `2707428` | 85 | 28 |
| Soy chips | `2707434` | 85 | 28 |
| Roll, NS as to major flour | `2707595` | 68 | 28 |
| Roll, hard, NS as to major flour | `2707596` | 56 | 25 |
| Bread, pita with fruit | `2707617` | 85 | 28 |
| Roll, white, hoagie, submarine | `2707663` | 106 | 73 |
| Roll, Mexican, bolillo | `2707664` | 162 | 76 |
| Roll, sour dough | `2707665` | 45 | 34 |
| Roll, sweet, no frosting | `2707666` | 90 | 54 |
| Pan dulce, NFS | `2707669` | 93 | 70 |
| Pan Dulce, no topping | `2707674` | 76 | 56 |
| Croissant | `2707678` | 73 | 42 |
| Bagel | `2707684` | 131 | 69 |
| Bagel, with fruit other than raisins | `2707686` | 131 | 69 |
| Breadsticks, NFS | `2707689` | 43 | 28 |
| Breadsticks, hard, NFS | `2707690` | 10 | 5 |
| Breadsticks, hard, reduced sodium | `2707691` | 10 | 5 |
| Breadsticks, soft, NFS | `2707692` | 53 | 28 |
| Breadsticks, soft, with parmesan cheese, fast food / restaurant | `2707695` | 43 | 28 |
| Breadsticks, soft, stuffed or topped with melted cheese | `2707696` | 61 | 40 |
| Bread, chappatti or roti | `2707713` | 52 | 27 |
| Bagel, whole wheat | `2707733` | 131 | 69 |
| Bagel, wheat, with raisins | `2707734` | 131 | 69 |
| Bagel, whole wheat, with raisins | `2707735` | 131 | 69 |
| Breadsticks, hard, whole wheat | `2707745` | 10 | 5 |
| Roll, wheat or cracked wheat | `2707746` | 106 | 28 |
| Roll, whole wheat | `2707749` | 68 | 28 |
| Roll, whole grain white | `2707752` | 153 | 28 |
| Bagel, pumpernickel | `2707762` | 131 | 69 |
| Roll, pumpernickel | `2707767` | 36 | 28 |
| Bagel, oat bran | `2707772` | 131 | 69 |
| Breadsticks, hard, gluten free | `2707799` | 10 | 5 |
| Roll, gluten free | `2707800` | 52 | 28 |
| Cornbread muffin, stick, round | `2707813` | 113 | 66 |
| Cornbread muffin, stick, round, made from home recipe | `2707814` | 154 | 66 |
| Tortilla, NFS | `2707822` | 65 | 18 |
| Tortilla, corn | `2707823` | 28 | 18 |
| Tortilla, flour | `2707824` | 104 | 33 |
| Tortilla, whole wheat | `2707825` | 71 | 33 |
| Taco shell, corn | `2707826` | 28 | 18 |
| Taco shell, flour | `2707827` | 45 | 33 |
| Muffin, fruit | `2707830` | 180 | 70 |
| Muffin, fruit, low fat | `2707831` | 180 | 70 |
| Muffin, chocolate chip | `2707832` | 180 | 70 |
| Muffin, chocolate | `2707833` | 180 | 70 |
| Muffin, whole wheat | `2707834` | 130 | 70 |
| Muffin, whole grain | `2707836` | 180 | 70 |
| Muffin, oat bran | `2707840` | 130 | 70 |
| Muffin, plain | `2707841` | 180 | 70 |
| Muffin, cheese | `2707842` | 180 | 70 |
| Muffin, carrot | `2707845` | 130 | 70 |
| Cookie, NFS | `2707899` | 30 | 20 |
| Cookie, applesauce | `2707901` | 30 | 20 |
| Cookie, brownie, NS as to icing | `2707903` | 50 | 30 |
| Cookie, brownie, without icing | `2707904` | 90 | 30 |
| Cookie, brownie, with icing or filling | `2707905` | 65 | 40 |
| Cookie, butterscotch, brownie | `2707907` | 90 | 30 |
| Cookie, bar, with chocolate | `2707908` | 90 | 30 |
| Cookie, chocolate chip | `2707909` | 38 | 20 |
| Cookie, chocolate chip, made from home recipe or purchased at a bakery | `2707910` | 100 | 20 |
| Cookie, chocolate chip, reduced fat | `2707911` | 45 | 20 |
| Cookie, chocolate, made with oatmeal and coconut, no bake | `2707914` | 30 | 20 |
| Cookie, chocolate wafer | `2707924` | 10 | 5 |
| Cookie, graham cracker with chocolate and marshmallow | `2707925` | 84 | 42 |
| Cookie bar, with chocolate, nuts, and graham crackers | `2707926` | 56 | 25 |
| Cookie, fruit-filled bar | `2707928` | 38 | 25 |
| Cookie, gingersnaps | `2707932` | 30 | 20 |
| Cookie, granola | `2707933` | 45 | 20 |
| Cookie, lemon bar | `2707935` | 38 | 25 |
| Cookie, marshmallow, with rice cereal, no bake | `2707938` | 56 | 25 |
| Cookie, marshmallow and peanut butter, with oat cereal, no bake | `2707940` | 38 | 25 |
| Cookie, molasses | `2707942` | 45 | 20 |
| Cookie, oatmeal, with raisins | `2707946` | 45 | 20 |
| Cookie, oatmeal, reduced fat, NS as to raisins | `2707947` | 45 | 20 |
| Cookie, oatmeal, with chocolate chips | `2707949` | 45 | 20 |
| Cookie, peanut butter | `2707952` | 45 | 20 |
| Cookie, peanut butter, with chocolate | `2707953` | 30 | 20 |
| Cookie, peanut butter with rice cereal, no bake | `2707954` | 56 | 25 |
| Cookie, with peanut butter filling, chocolate-coated | `2707956` | 42 | 28 |
| Cookie, pumpkin | `2707959` | 56 | 20 |
| Cookie, raisin | `2707960` | 45 | 20 |
| Cookie, shortbread | `2707964` | 45 | 20 |
| Cookie, butter or sugar, with fruit and/or nuts | `2707972` | 30 | 20 |
| Cookie, sugar wafer | `2707973` | 8 | 4 |
| Cookie, toffee bar | `2707974` | 56 | 25 |
| Cookie, vanilla sandwich, extra filling | `2707976` | 36 | 14 |
| Cookie, butter or sugar, with icing or filling other than chocolate | `2707979` | 42 | 28 |
| Cookie, tea, Japanese | `2707980` | 11 | 2 |
| Cookie, vanilla wafer, reduced fat | `2707982` | 4 | 3 |
| Cookie, vanilla with caramel, coconut, and chocolate coating | `2707983` | 63 | 28 |
| Cookie, chocolate chip, reduced sugar | `2707985` | 45 | 20 |
| Cookie, peanut butter, sugar free | `2707990` | 45 | 20 |
| Pastry, made with bean or lotus seed paste filling, baked | `2708048` | 46 | 51 |
| Breakfast pastry, NFS | `2708058` | 142 | 56 |
| Danish pastry, plain or spice | `2708059` | 113 | 56 |
| Danish pastry, with fruit | `2708060` | 142 | 56 |
| Danish pastry, with cheese | `2708061` | 142 | 56 |
| Graham crackers | `2708133` | 85 | 15 |
| Graham crackers (Teddy Grahams) | `2708134` | 85 | 45 |
| Crackers, butter, reduced sodium | `2708141` | 85 | 45 |
| Crackers, butter, plain | `2708146` | 85 | 45 |
| Crackers, butter (Ritz) | `2708148` | 85 | 45 |
| Crackers, butter, reduced fat | `2708149` | 85 | 45 |
| Crackers, cheese | `2708150` | 45 | 1 |
| Crackers, cheese (Cheez-It) | `2708151` | 85 | 45 |
| Crackers, cheese, reduced fat | `2708153` | 45 | 1 |
| Crackers, cheese, reduced sodium | `2708154` | 85 | 45 |
| Crackers, cheese, whole grain | `2708155` | 45 | 1 |
| Chips, rice | `2708161` | 57 | 28 |
| Rice paper | `2708166` | 20 | 5 |
| Crackers, multigrain | `2708170` | 85 | 45 |
| Crackers, woven wheat | `2708180` | 85 | 45 |
| Crackers, wheat | `2708184` | 85 | 45 |
| Crackers, wheat, plain (Wheat Thins) | `2708185` | 85 | 45 |
| Crackers, wheat, flavored (Wheat Thins) | `2708186` | 85 | 45 |
| Crackers, wheat, reduced fat | `2708187` | 85 | 45 |
| Corn nuts | `2708195` | 57 | 28 |
| Corn chips, plain | `2708196` | 57 | 28 |
| Corn chips, flavored | `2708197` | 85 | 28 |
| Corn chips, flavored (Fritos) | `2708199` | 57 | 28 |
| Cheese flavored corn snacks | `2708200` | 85 | 2 |
| Cheese flavored corn snacks, reduced fat | `2708201` | 85 | 2 |
| Tortilla chips, plain | `2708202` | 57 | 28 |
| Cheese flavored corn snacks (Cheetos) | `2708203` | 57 | 2 |
| Tortilla chips, cool ranch flavor (Doritos) | `2708207` | 85 | 28 |
| Tortilla chips, reduced fat, flavored | `2708210` | 57 | 28 |
| Tortilla chips, low fat, unsalted | `2708211` | 85 | 28 |
| Pita chips | `2708215` | 85 | 28 |
| Popcorn, NFS | `2708216` | 85 | 28 |
| Popcorn, movie theater, with added butter | `2708217` | 238 | 112 |
| Popcorn, ready-to-eat, plain | `2708232` | 57 | 28 |
| Popcorn, ready-to-eat, plain, light | `2708233` | 57 | 28 |
| Popcorn, ready-to-eat, low sodium | `2708234` | 85 | 28 |
| Popcorn, ready-to-eat, cheese flavored | `2708236` | 57 | 28 |
| Popcorn, ready-to-eat, flavored, light | `2708237` | 57 | 28 |
| Popcorn, caramel coated, with nuts | `2708240` | 57 | 28 |
| Popcorn chips, other flavors | `2708243` | 85 | 28 |
| Popcorn chips, sweet flavors | `2708244` | 57 | 28 |
| Onion flavored rings | `2708245` | 28 | 2 |
| Pretzels, NFS | `2708247` | 57 | 28 |
| Pretzels, hard, plain, salted | `2708249` | 57 | 28 |
| Pretzels, hard, plain, lightly salted | `2708250` | 85 | 28 |
| Pretzels, hard, plain, unsalted | `2708251` | 57 | 28 |
| Pretzels, hard, flavored | `2708252` | 85 | 28 |
| Pretzels, hard, multigrain | `2708253` | 57 | 28 |
| Pretzels, hard, plain, gluten free | `2708254` | 85 | 28 |
| Pretzels, hard, flavored, gluten free | `2708255` | 85 | 28 |
| Pretzel chips, hard, flavored | `2708257` | 85 | 28 |
| Pretzels, hard, coated, NFS | `2708259` | 57 | 28 |
| Pretzels, hard, chocolate coated | `2708260` | 57 | 28 |
| Pretzels, hard, white chocolate coated | `2708261` | 57 | 28 |
| Pretzels, hard, yogurt coated | `2708262` | 57 | 28 |
| Pretzels, hard, cheese filled | `2708265` | 57 | 28 |
| Pretzels, hard, peanut butter filled | `2708266` | 85 | 28 |
| Pretzels, soft, ready-to-eat, NFS | `2708268` | 143 | 62 |
| Pretzels, soft, ready-to-eat, salted, buttered | `2708269` | 120 | 62 |
| Pretzels, soft, ready-to-eat, unsalted, buttered | `2708270` | 143 | 62 |
| Pretzels, soft, ready-to-eat, salted, no butter | `2708271` | 120 | 62 |
| Pretzels, soft, ready-to-eat, unsalted, no butter | `2708272` | 143 | 62 |
| Pretzels, soft, ready-to-eat, cinnamon sugar coated | `2708273` | 175 | 74 |
| Pretzels, soft, ready-to-eat, topped with cheese | `2708276` | 147 | 74 |
| Pretzels, soft, multigrain | `2708286` | 120 | 62 |
| Snack mix, plain (Chex Mix) | `2708291` | 57 | 28 |
| Bagel chips | `2708292` | 85 | 45 |
| Pancakes, NFS | `2708294` | 50 | 20 |
| Pancakes, plain, fast food / restaurant | `2708299` | 90 | 20 |
| Pancakes, fruit, fast food / restaurant | `2708300` | 50 | 20 |
| Pancakes, chocolate, fast food / restaurant | `2708301` | 150 | 20 |
| Pancakes, whole grain, fast food / restaurant | `2708302` | 90 | 20 |
| Pancakes, plain | `2708304` | 150 | 20 |
| Pancakes, plain, reduced fat | `2708305` | 90 | 20 |
| Pancakes, pumpkin | `2708307` | 90 | 20 |
| Pancakes, whole grain | `2708309` | 150 | 20 |
| Pancakes, gluten free | `2708311` | 50 | 20 |
| Waffle, chocolate, fast food / restaurant | `2708321` | 125 | 40 |
| Waffle, whole grain, fast food / restaurant | `2708323` | 75 | 40 |
| Waffle, fruit | `2708326` | 75 | 40 |
| Waffle, cinnamon | `2708328` | 75 | 40 |
| Waffle, gluten free | `2708330` | 125 | 40 |
| Taco or tostada salad with chicken | `2708509` | 400 | 240 |
| Taco or tostada salad, meatless | `2708510` | 388 | 234 |
| Taco or tostada salad with meat and sour cream | `2708511` | 358 | 264 |
| Taco or tostada salad with chicken and sour cream | `2708512` | 363 | 273 |
| Taco or tostada salad, meatless with sour cream | `2708513` | 354 | 266 |
| Taco, NFS | `2708514` | 160 | 105 |
| Taco, corn tortilla, beef, with beans, cheese | `2708516` | 160 | 105 |
| Taco, corn tortilla, pork, with beans, cheese | `2708518` | 160 | 105 |
| Taco, corn tortilla, chicken, cheese | `2708519` | 160 | 105 |
| Taco, corn tortilla, with beans, cheese | `2708521` | 160 | 105 |
| Taco, flour tortilla, pork, cheese | `2708524` | 160 | 105 |
| Taco, flour tortilla, pork, with beans, cheese | `2708525` | 160 | 105 |
| Taco, flour tortilla, chicken, cheese | `2708526` | 160 | 105 |
| Taco, with beans, no cheese | `2708532` | 150 | 100 |
| Burrito, beef, with beans, cheese | `2708537` | 330 | 220 |
| Burrito, beef, with beans and rice, cheese | `2708538` | 330 | 220 |
| Burrito, pork, with rice, cheese | `2708540` | 330 | 220 |
| Burrito, pork, with beans and rice, cheese | `2708542` | 330 | 220 |
| Burrito, chicken, with rice, cheese | `2708544` | 330 | 220 |
| Burrito, with beans, cheese | `2708548` | 285 | 190 |
| Burrito, meat, with rice, no cheese | `2708551` | 330 | 220 |
| Burrito, meat, with beans, no cheese | `2708552` | 330 | 220 |
| Burrito, meat, with beans and rice, no cheese | `2708553` | 330 | 220 |
| Burrito, cheese only | `2708554` | 225 | 150 |
| Taquito, beef or pork | `2708600` | 105 | 70 |
| Taquito, chicken | `2708601` | 105 | 70 |
| Pizza, cheese, from frozen, thin crust | `2708612` | 320 | 97 |
| Pizza, cheese, from frozen, thick crust | `2708613` | 1255 | 133 |
| Pizza, cheese, from restaurant or fast food, NS as to type of crust | `2708614` | 86 | 119 |
| Pizza, cheese, from restaurant or fast food, thin crust | `2708615` | 63 | 86 |
| Pizza, cheese, from restaurant or fast food, medium crust | `2708616` | 80 | 119 |
| Pizza, cheese, from restaurant or fast food, thick crust | `2708617` | 744 | 132 |
| Pizza, extra cheese, thin crust | `2708622` | 63 | 92 |
| Pizza, extra cheese, thick crust | `2708623` | 145 | 141 |
| Pizza, cheese, with vegetables, from frozen, thin crust | `2708624` | 369 | 109 |
| Pizza, cheese with vegetables, from frozen, thick crust | `2708625` | 483 | 143 |
| Pizza, cheese, with vegetables, from restaurant or fast food, thin crust | `2708626` | 112 | 100 |
| Pizza, cheese, with vegetables, from restaurant or fast food, thick crust | `2708628` | 1192 | 149 |
| Pizza with cheese and extra vegetables, thin crust | `2708629` | 1246 | 120 |
| Pizza with cheese and extra vegetables, medium crust | `2708630` | 84 | 152 |
| Pizza, cheese, with fruit, thin crust | `2708632` | 71 | 104 |
| Pizza, cheese, with fruit, medium crust | `2708633` | 1098 | 137 |
| Pizza, cheese, with fruit, thick crust | `2708634` | 102 | 150 |
| Pizza with pepperoni, from frozen, thin crust | `2708635` | 320 | 97 |
| Pizza with pepperoni, from frozen, medium crust | `2708636` | 340 | 102 |
| Pizza with pepperoni, from frozen, thick crust | `2708637` | 377 | 144 |
| Pizza with pepperoni, from restaurant or fast food, NS as to type of crust | `2708638` | 516 | 124 |
| Pizza with pepperoni, from restaurant or fast food, thin crust | `2708639` | 369 | 91 |
| Pizza with pepperoni, from restaurant or fast food,  medium crust | `2708640` | 134 | 124 |
| Pizza with pepperoni, from restaurant or fast food, thick crust | `2708641` | 147 | 139 |
| Pizza with pepperoni, stuffed crust | `2708642` | 110 | 164 |
| Pizza with meat other than pepperoni, from frozen, thin crust | `2708646` | 320 | 97 |
| Pizza with meat other than pepperoni, from frozen, medium crust | `2708647` | 340 | 102 |
| Pizza with meat other than pepperoni, from frozen, thick crust | `2708648` | 1361 | 144 |
| Pizza with meat other than pepperoni, from restaurant or fast food, NS as to type of crust | `2708649` | 1428 | 138 |
| Pizza with meat other than pepperoni, from restaurant or fast food, thin crust | `2708650` | 108 | 104 |
| Pizza with extra meat, medium crust | `2708658` | 869 | 150 |
| Pizza with extra meat, thick crust | `2708659` | 112 | 166 |
| Pizza with meat and vegetables, from frozen, thin crust | `2708660` | 961 | 103 |
| Pizza with meat and vegetables, from frozen, medium crust | `2708661` | 371 | 108 |
| Pizza with meat and vegetables, from restaurant or fast food, thin crust | `2708663` | 902 | 113 |
| Pizza with meat and vegetables, from restaurant or fast food, medium crust | `2708664` | 79 | 144 |
| Pizza with meat and vegetables, from restaurant or fast food, thick crust | `2708665` | 942 | 149 |
| Pizza with extra meat and extra vegetables, thin crust | `2708666` | 796 | 129 |
| Pizza with extra meat and extra vegetables, thick crust | `2708667` | 706 | 173 |
| Pizza with extra meat and extra vegetables, medium crust | `2708668` | 169 | 159 |
| Pizza with meat and fruit, thin crust | `2708669` | 121 | 115 |
| Pizza with meat and fruit, medium crust | `2708670` | 636 | 150 |
| Pizza with beans and vegetables, thin crust | `2708672` | 100 | 129 |
| Pizza with beans and vegetables, thick crust | `2708673` | 181 | 173 |
| Pizza, no cheese, thin crust | `2708674` | 432 | 75 |
| Pizza, no cheese, thick crust | `2708675` | 129 | 124 |
| White pizza, cheese, thick crust | `2708677` | 1112 | 141 |
| White pizza, cheese, with vegetables, thin crust | `2708678` | 1218 | 106 |
| White pizza, cheese, with vegetables, thick crust | `2708679` | 111 | 155 |
| White pizza, cheese, with meat, thin crust | `2708680` | 571 | 100 |
| White pizza, cheese, with meat and vegetables, thin crust | `2708682` | 81 | 118 |
| White pizza, cheese, with meat and vegetables, thick crust | `2708683` | 161 | 155 |
| Pizza, cheese, whole wheat thin crust | `2708687` | 86 | 119 |
| Pizza, cheese, whole wheat thick crust | `2708688` | 744 | 132 |
| Pizza, with meat, whole wheat thick crust | `2708690` | 96 | 139 |
| Pizza, cheese and vegetables, whole wheat thin crust | `2708691` | 1326 | 133 |
| Pizza, cheese and vegetables, whole wheat thick crust | `2708692` | 104 | 149 |
| Pizza, cheese, gluten-free thin crust | `2708693` | 128 | 119 |
| Pizza, cheese, gluten-free thick crust | `2708694` | 90 | 132 |
| Pizza, with meat, gluten-free thin crust | `2708695` | 88 | 124 |
| Pizza, with meat, gluten-free thick crust | `2708696` | 96 | 139 |
| Pizza, cheese and vegetables, gluten-free thin crust | `2708697` | 1326 | 133 |
| Pizza, cheese and vegetables, gluten-free thick crust | `2708698` | 1548 | 149 |
| Breakfast pizza with egg | `2708699` | 477 | 144 |
| Egg roll, meatless | `2708700` | 64 | 13 |
| Egg roll, with shrimp | `2708701` | 64 | 13 |
| Empanada, NFS | `2708709` | 130 | 35 |
| Empanada, no meat | `2708710` | 130 | 35 |
| Empanada, beef, with vegetables | `2708712` | 130 | 35 |
| Empanada, chicken | `2708713` | 130 | 35 |
| Samosa | `2708730` | 100 | 25 |
| Turnover or hot pocket, NFS | `2708734` | 130 | 35 |
| Turnover or hot pocket, meatless | `2708735` | 130 | 35 |
| Turnover or hot pocket, beef | `2708736` | 130 | 35 |
| Turnover or hot pocket, pizza pocket, meat | `2708738` | 130 | 35 |
| Turnover or hot pocket, pizza pocket | `2708739` | 130 | 35 |
| Lasagna with chicken or turkey | `2708756` | 232 | 206 |
| Macaroni or noodles with cheese, Easy Mac type | `2708815` | 423 | 321 |
| Dosa, with filling | `2709129` | 523 | 113 |
| Apple, raw | `2709215` | 200 | 165 |
| Cantaloupe, raw | `2709226` | 550 | 440 |
| Honeydew melon, raw | `2709241` | 1000 | 800 |
| Watermelon, raw | `2709270` | 6000 | 3200 |
| Fruit smoothie, with whole fruit, no dairy | `2709334` | 864 | 540 |
| Fruit smoothie, with whole fruit, non-dairy | `2709336` | 1080 | 540 |
| Fruit smoothie juice drink, no dairy | `2709337` | 864 | 540 |
| Fruit smoothie, light | `2709338` | 864 | 540 |
| Potato, baked, peel not eaten | `2709384` | 400 | 230 |
| Potato, boiled, from fresh, peel not eaten, NS as to fat | `2709387` | 300 | 130 |
| Potato, boiled, from fresh, peel not eaten, fat added, NS as to fat type | `2709389` | 170 | 130 |
| Potato, boiled, from fresh, peel not eaten, made with oil | `2709390` | 170 | 130 |
| Potato, boiled, from fresh, peel not eaten, made with butter | `2709391` | 170 | 130 |
| Potato, boiled, from fresh, peel eaten, NS as to fat | `2709393` | 300 | 130 |
| Potato, boiled, from fresh,  peel eaten, no added fat | `2709395` | 170 | 130 |
| Potato, boiled, from fresh, peel eaten, made with butter | `2709397` | 300 | 130 |
| Potato, boiled, from fresh, peel eaten, made with margarine | `2709398` | 300 | 130 |
| Potato, roasted, from fresh, peel eaten, NS as to fat | `2709403` | 300 | 130 |
| Potato, roasted, from fresh, peel eaten, no added fat | `2709404` | 170 | 130 |
| Potato, roasted, from fresh, peel eaten, fat added, NS as to fat type | `2709405` | 170 | 130 |
| Potato, roasted, from fresh, peel eaten, made with oil | `2709406` | 300 | 130 |
| Potato, roasted, from fresh, peel eaten, made with margarine | `2709408` | 300 | 130 |
| Potato, roasted, from fresh, peel not eaten, no added fat | `2709411` | 300 | 130 |
| Potato, roasted, from fresh, peel not eaten, made with oil | `2709412` | 170 | 130 |
| Potato, roasted, from fresh, peel not eaten, made with butter | `2709413` | 300 | 130 |
| Potato, roasted, from fresh, peel not eaten, made with margarine | `2709414` | 300 | 130 |
| Potato, roasted, ready-to-heat | `2709415` | 170 | 130 |
| Potato from Puerto Rican style stuffed pot roast, with gravy | `2709418` | 137 | 103 |
| Potato from Puerto Rican chicken fricassee, with sauce | `2709420` | 247 | 123 |
| Potato chips, NFS | `2709421` | 85 | 28 |
| Potato chips, plain | `2709422` | 85 | 28 |
| Potato chips, cheese flavored | `2709425` | 57 | 28 |
| Potato chips, other flavored | `2709426` | 57 | 28 |
| Potato chips, ruffled, barbecue flavored | `2709428` | 57 | 28 |
| Potato chips, ruffled, sour cream and onion flavored | `2709429` | 57 | 28 |
| Potato chips, baked, plain | `2709434` | 57 | 28 |
| Potato chips, unsalted | `2709438` | 57 | 28 |
| Potato chips, lightly salted | `2709439` | 57 | 28 |
| Potato chips, popped, plain | `2709441` | 57 | 28 |
| Potato chips, popped, NFS | `2709443` | 85 | 28 |
| Potato sticks, plain | `2709444` | 85 | 28 |
| Vegetable chips | `2709447` | 85 | 28 |
| Potato, french fries, from fresh, fried | `2709458` | 100 | 50 |
| Potato, french fries, from fresh, baked | `2709459` | 70 | 50 |
| Potato, french fries, fast food | `2709461` | 180 | 110 |
| Potato, french fries, restaurant | `2709462` | 145 | 110 |
| Potato, french fries, with cheese, fast food / restaurant | `2709465` | 222 | 169 |
| Potato, french fries, with chili, fast food / restaurant | `2709467` | 276 | 169 |
| Potato skins, with cheese | `2709489` | 70 | 35 |
| Potato skins, with cheese and bacon | `2709490` | 70 | 35 |
| Potato skins, NFS | `2709491` | 50 | 25 |
| Potato, baked, peel not eaten, with sour cream | `2709519` | 445 | 260 |
| Potato, baked, peel not eaten, with cheese | `2709520` | 445 | 260 |
| Potato, baked, peel not eaten, with meat | `2709521` | 315 | 260 |
| Potato, baked, peel not eaten, with vegetables | `2709523` | 315 | 260 |
| Potato, baked, peel eaten, with butter | `2709525` | 445 | 260 |
| Potato, baked, peel eaten, with sour cream | `2709526` | 315 | 260 |
| Potato, baked, peel eaten, with cheese | `2709527` | 445 | 260 |
| Potato, baked, peel eaten, with chili | `2709529` | 445 | 260 |
| Potato, baked, peel eaten, with vegetables | `2709530` | 315 | 260 |
| Potato pancake | `2709552` | 215 | 25 |
| Sweet potato, baked, NS as to fat | `2709698` | 150 | 80 |
| Sweet potato, baked, no added fat | `2709699` | 150 | 80 |
| Sweet potato, baked, fat added | `2709700` | 235 | 80 |
| Sweet potato, boiled, NS as to fat | `2709701` | 150 | 80 |
| Sweet potato, boiled, no added fat | `2709702` | 235 | 80 |
| Sweet potato chips | `2709710` | 85 | 28 |
| Fruit and vegetable smoothie, with dairy | `2710146` | 1080 | 540 |
| Fruit and vegetable smoothie, non-dairy | `2710148` | 1080 | 540 |
| Fruit and vegetable smoothie, non-dairy, added protein | `2710149` | 1080 | 540 |
| Candy, NFS | `2710325` | 120 | 5 |
| Chocolate candy, other, NFS | `2710327` | 90 | 8 |
| Chocolate candy with cereal | `2710331` | 90 | 8 |
| Dark chocolate candy, other, NFS | `2710335` | 90 | 8 |
| Dark chocolate candy | `2710336` | 90 | 8 |
| White chocolate candy | `2710339` | 90 | 8 |
| Chocolate candy, cream filled | `2710344` | 90 | 15 |
| Chocolate candy, nougat filled | `2710345` | 110 | 8 |
| Candy, caramel | `2710354` | 120 | 5 |
| Candy, nougat with nuts | `2710355` | 120 | 10 |
| Candy, hard | `2710360` | 120 | 5 |
| Candy, fruit flavored pieces | `2710364` | 120 | 2 |
| Chocolate candy, candy shell | `2710365` | 90 | 2 |
| Candy, taffy | `2710369` | 120 | 5 |
| Coffee, NS as to type | `2710373` | 600 | 360 |
| Coffee, NS as to brewed or instant | `2710374` | 1800 | 360 |
| Coffee, brewed | `2710375` | 600 | 360 |
| Coffee, brewed, blend of regular and decaffeinated | `2710376` | 600 | 360 |
| Coffee, brewed, flavored | `2710380` | 600 | 360 |
| Coffee, Latte, nonfat | `2710387` | 600 | 360 |
| Coffee, Latte, with non-dairy milk | `2710388` | 480 | 360 |
| Coffee, Latte, nonfat, flavored | `2710390` | 496 | 372 |
| Coffee, Latte, with non-dairy milk, flavored | `2710391` | 496 | 372 |
| Coffee, Latte, decaffeinated | `2710392` | 480 | 360 |
| Coffee, Latte, decaffeinated, with non-dairy milk | `2710394` | 600 | 360 |
| Coffee, Latte, decaffeinated, flavored | `2710395` | 496 | 372 |
| Coffee, Latte, decaffeinated, with non-dairy milk, flavored | `2710397` | 496 | 372 |
| Frozen coffee drink | `2710398` | 496 | 372 |
| Frozen coffee drink, with non-dairy milk | `2710400` | 620 | 372 |
| Frozen coffee drink, with whipped cream | `2710401` | 620 | 372 |
| Frozen coffee drink, with non-dairy milk and whipped cream | `2710403` | 620 | 372 |
| Frozen coffee drink, decaffeinated, nonfat | `2710405` | 620 | 372 |
| Frozen coffee drink, decaffeinated, with whipped cream | `2710407` | 496 | 372 |
| Frozen coffee drink, decaffeinated, with non-dairy milk and whipped cream | `2710409` | 620 | 372 |
| Coffee, Cafe Mocha | `2710410` | 620 | 372 |
| Coffee, Cafe Mocha, nonfat | `2710411` | 496 | 372 |
| Coffee, Cafe Mocha, decaffeinated | `2710413` | 620 | 372 |
| Coffee, Cafe Mocha, decaffeinated, nonfat | `2710414` | 496 | 372 |
| Coffee, Cafe Mocha, decaffeinated, with non-dairy milk | `2710415` | 620 | 372 |
| Frozen mocha coffee drink | `2710416` | 496 | 372 |
| Frozen mocha coffee drink, nonfat | `2710417` | 496 | 372 |
| Frozen mocha coffee drink, with non-dairy milk | `2710418` | 620 | 372 |
| Frozen mocha coffee drink, decaffeinated | `2710422` | 620 | 372 |
| Frozen mocha coffee drink, decaffeinated, nonfat | `2710423` | 496 | 372 |
| Frozen mocha coffee drink, decaffeinated, with non-dairy milk | `2710424` | 620 | 372 |
| Frozen mocha coffee drink, decaffeinated, with non-dairy milk and whipped cream | `2710427` | 496 | 372 |
| Iced Coffee, brewed, decaffeinated | `2710429` | 600 | 360 |
| Iced Coffee, pre-lightened and pre-sweetened | `2710430` | 620 | 372 |
| Coffee, Iced Latte | `2710431` | 600 | 360 |
| Coffee, Iced Latte, nonfat | `2710432` | 480 | 360 |
| Coffee, Iced Latte, with non-dairy milk | `2710433` | 480 | 360 |
| Coffee, Iced Latte, flavored | `2710434` | 496 | 372 |
| Coffee, Iced Latte, nonfat, flavored | `2710435` | 620 | 372 |
| Coffee, Iced Latte, with non-dairy milk, flavored | `2710436` | 496 | 372 |
| Coffee, Iced Latte, decaffeinated | `2710437` | 480 | 360 |
| Coffee, Iced Latte, decaffeinated, nonfat | `2710438` | 480 | 360 |
| Coffee, Iced Latte, decaffeinated, with non-dairy milk | `2710439` | 480 | 360 |
| Coffee, Iced Latte, decaffeinated, with non-dairy milk, flavored | `2710442` | 496 | 372 |
| Coffee, Iced Cafe Mocha | `2710443` | 496 | 372 |
| Coffee, Iced Cafe Mocha, nonfat | `2710444` | 496 | 372 |
| Coffee, Iced Cafe Mocha, decaffeinated, nonfat | `2710447` | 496 | 372 |
| Coffee, Iced Cafe Mocha, decaffeinated, with non-dairy milk | `2710448` | 620 | 372 |
| Coffee, NS as to brewed or instant, decaffeinated | `2710451` | 600 | 360 |
| Coffee, brewed, decaffeinated | `2710452` | 1800 | 360 |
| Coffee, Cappuccino, nonfat | `2710473` | 480 | 360 |
| Coffee, Cappuccino, with non-dairy milk | `2710474` | 480 | 360 |
| Coffee, Cappuccino, decaffeinated | `2710475` | 480 | 360 |
| Coffee, Cappuccino, decaffeinated, nonfat | `2710476` | 480 | 360 |
| Tea, hot, leaf, green | `2710490` | 480 | 360 |
| Tea, hot, leaf, green, decaffeinated | `2710491` | 600 | 360 |
| Tea, hot, leaf, oolong | `2710492` | 600 | 360 |
| Tea, hot, herbal | `2710502` | 480 | 360 |
| Tea, hot, hibiscus | `2710503` | 480 | 360 |
| Tea, hot, chamomile | `2710505` | 480 | 360 |
| Tea, ginger | `2710507` | 480 | 360 |
| Tea, iced, brewed, black, pre-sweetened with sugar | `2710515` | 512 | 372 |
| Tea, iced, brewed, black, pre-sweetened with low calorie sweetener | `2710516` | 979 | 360 |
| Tea, iced, brewed, black, unsweetened | `2710517` | 495 | 360 |
| Tea, iced, brewed, black, decaffeinated, pre-sweetened with sugar | `2710518` | 744 | 372 |
| Tea, iced, brewed, black, decaffeinated, pre-sweetened with low calorie sweetener | `2710519` | 979 | 360 |
| Tea, iced, brewed, black, decaffeinated, unsweetened | `2710520` | 979 | 360 |
| Tea, iced, brewed, green, pre-sweetened with sugar | `2710521` | 512 | 372 |
| Tea, iced, brewed, green, pre-sweetened with low calorie sweetener | `2710522` | 495 | 360 |
| Tea, iced, brewed, green, unsweetened | `2710523` | 979 | 360 |
| Tea, iced, brewed, green, decaffeinated, pre-sweetened with sugar | `2710524` | 512 | 372 |
| Tea, iced, brewed, green, decaffeinated, pre-sweetened with low calorie sweetener | `2710525` | 495 | 360 |
| Tea, iced, bottled, black | `2710527` | 512 | 372 |
| Tea, iced, bottled, black, decaffeinated | `2710528` | 512 | 372 |
| Tea, iced, bottled, black, decaffeinated, diet | `2710530` | 979 | 360 |
| Tea, iced, bottled, black, unsweetened | `2710531` | 720 | 360 |
| Tea, iced, bottled, black, decaffeinated, unsweetened | `2710532` | 979 | 360 |
| Tea, iced, bottled, green | `2710533` | 1023 | 372 |
| Tea, iced, bottled, green, diet | `2710534` | 512 | 372 |
| Tea, iced, bottled, green, unsweetened | `2710535` | 979 | 360 |
| Soft drink, NFS | `2710536` | 1023 | 372 |
| Soft drink, NFS, diet | `2710537` | 495 | 360 |
| Soft drink, cola, diet | `2710542` | 720 | 360 |
| Soft drink, cola, decaffeinated | `2710543` | 512 | 372 |
| Soft drink, cola, decaffeinated, diet | `2710544` | 720 | 360 |
| Soft drink, pepper type | `2710545` | 744 | 372 |
| Soft drink, pepper type, diet | `2710546` | 495 | 360 |
| Soft drink, pepper type, decaffeinated | `2710547` | 512 | 372 |
| Soft drink, pepper type, decaffeinated, diet | `2710548` | 495 | 360 |
| Soft drink, cream soda | `2710549` | 1023 | 372 |
| Soft drink, cream soda, diet | `2710550` | 720 | 360 |
| Soft drink, fruit flavored, diet, caffeine free | `2710552` | 720 | 360 |
| Soft drink, fruit flavored, caffeine containing | `2710553` | 512 | 372 |
| Soft drink, ginger ale, diet | `2710556` | 979 | 360 |
| Soft drink, root beer | `2710557` | 744 | 372 |
| Soft drink, root beer, diet | `2710558` | 495 | 360 |
| Soft drink, chocolate flavored | `2710559` | 512 | 372 |
| Soft drink, chocolate flavored, diet | `2710560` | 495 | 360 |
| Soft drink, cola, fruit or vanilla flavored | `2710561` | 512 | 372 |
| Soft drink, cola, chocolate flavored | `2710562` | 1023 | 372 |
| Soft drink, cola, fruit or vanilla flavored, diet | `2710563` | 495 | 360 |
| Soft drink, cola, chocolate flavored, diet | `2710564` | 720 | 360 |
| Fruit juice drink | `2710567` | 1023 | 372 |
| Fruit juice drink, with high vitamin C | `2710580` | 744 | 372 |

### `can`（27）

| 食物 | fdc_id | 旧 g | 新 g |
|---|---|---:|---:|
| Fish, salmon, canned | `2706291` | 115 | 75 |
| Crab, canned | `2706345` | 450 | 60 |
| Oysters, canned | `2706355` | 255 | 75 |
| Shrimp, canned | `2706367` | 115 | 75 |
| Corned beef hash | `2706477` | 425 | 198 |
| Potato chips, restructured, multigrain | `2708214` | 60 | 20 |
| Potato chips, restructured, flavored | `2709433` | 185 | 20 |
| Potato chips, restructured, reduced fat, lightly salted | `2709437` | 60 | 20 |
| Potato chips, restructured, lightly salted | `2709440` | 185 | 20 |
| Coffee, bottled/canned | `2710478` | 341 | 202 |
| Coffee, bottled/canned, light | `2710479` | 450 | 195 |
| Tea, iced, bottled, black | `2710527` | 620 | 372 |
| Tea, iced, bottled, black, decaffeinated, diet | `2710530` | 600 | 360 |
| Tea, iced, bottled, black, unsweetened | `2710531` | 507 | 360 |
| Tea, iced, bottled, black, decaffeinated, unsweetened | `2710532` | 600 | 360 |
| Tea, iced, bottled, green | `2710533` | 524 | 372 |
| Tea, iced, bottled, green, diet | `2710534` | 620 | 372 |
| Beer | `2710616` | 480 | 360 |
| Beer, light | `2710617` | 480 | 360 |
| Beer, higher alcohol | `2710618` | 480 | 360 |
| Alcoholic malt beverage | `2710620` | 480 | 360 |
| Hard cider | `2710621` | 480 | 360 |
| Energy drink (Monster) | `2710747` | 620 | 257 |
| Energy drink (No Fear Motherload) | `2710750` | 496 | 248 |
| Energy Drink | `2710756` | 992 | 248 |
| Energy drink, sugar free (Mountain Dew AMP) | `2710759` | 720 | 480 |
| Energy drink, sugar-free (Red Bull) | `2710763` | 507 | 252 |

