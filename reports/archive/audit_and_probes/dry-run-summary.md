# FNDDS 完整接入 dry-run

只读对比：未改 `data/fdc/catalog.sqlite`、未改任何 gold JSON、未改 `scripts/build_fdc_catalog.py`。

- survey: `data/fdc/raw/survey.zip`
- catalog: `data/fdc/catalog.sqlite`
- split: `data/splits/v0.5-gold.json`（240 条，version `v0.5-gold`）
- 复跑: `.venv/bin/python scripts/fndds_dry_run.py`

## 接入策略

### 排序（first-wins 之前）

先把 `food_portion.csv` 全部行按 `(fdc_id 升序, seq_num 升序, portion id 升序)` 排定，再合并。`seq_num` 是 FNDDS 问卷里该食物的官方顺序；id 做并列打平，结果不依赖 zip 内行序。

### 合并

每个 `(fdc_id, key)` **first-wins**：排序后第一条 `gram_weight > 0` 留下，同键后续行丢弃。

### 复合描述 `1 piece/slice, any size`

描述里同时出现 piece 与 slice（典型即 `1 piece/slice, any size`）时，**同一克数双写 `piece` 和 `slice`**。

当前 `build_fdc_catalog._portion_key` 按 `_UNIT_PATTERNS` 扫描，`slice` 写在 `piece` 前面，所以这一行的 piece 分支被吃掉、只落成 slice。双写把该 FNDDS 行当成「piece 与 slice 可互换的同一份量」。各键仍独立 first-wins：若更早已有独立 `1 piece` 行，piece 不被覆盖；若复合行排在最前，则两个键都由它定值。

落地时若要保住冻结 split，应 **旧键冻结后再补缺失的一侧**：已有 slice=30 的牛排只补 piece=30，不会去改 cheddar 已有的 slice=21。

### QNS

`modifier == 90000`，或 `portion_description` 以 `quantity not` 开头 → 键 `qns`。`gram_weight <= 0` 丢弃。

### 旧键映射与仍丢弃的行

cup/tbsp/tsp/slice/piece/can 沿用当前 builder 的 household 正则；banana/egg/medium/large/small 仍塌缩为 piece。household 单位优先于 thick/thin/regular/oz，因此 `1 large or thick slice` 仍是 slice，不会变成 thick。

Guideline-amount 行仍丢弃。含 `mashed` 的行、以及同时含 `sliced` 与 `cup`的行仍丢弃，避免 mashed cup 抢走 cup 键。

新增键: `thick`, `thin`, `regular`, `oz`, `fl_oz`, `cubic_inch`, `serving`, `qns`。`fl_oz` 与重量 `oz` 分开；`5.3 oz container` 这类包装行不算 oz。

## 漂移统计（相对当前 catalog）

- 对比食物数: **5395**（catalog 内 FNDDS 5431；survey 提出份量 5395）
- 有任何差异（含仅新增键）: **5394**
- 旧键 cup/tbsp/tsp/slice/piece/can 值被改或被删: **861**
- 仅新增键、旧键原值不动: **4533**
- 完全零漂移: **1**

旧键被改的主因是 **seq_num 排序改变了 first-wins 赢家**：同一食物有多行映到同一旧键时，当前 catalog 按 zip 文件顺序取第一行，本 dry-run 按 FNDDS `seq_num` 取第一行。典型例子：

- Cheddar `1 cracker-size slice`（seq 1, 9 g）先于 `1 slice`（seq 2, 21 g） → `slice` 21→9
- Apple `1 small`（seq 1, 165 g）先于 `1 medium`（seq 2, 200 g） → `piece` 200→165（small/medium/large 仍按当前 builder 塌缩为 piece）

## Gold 25 种食物

**结论：25 种 gold 食物中，2 种旧键会变；14 条 gold 行的克数会随旧键一起变。按本策略落地会破坏冻结 split，不允许重建 catalog。**

### 每种食物

| food_id | fdc_id | 类型 | 旧键 | 新键变化 | QNS |
|---|---|---|---|---|---|
| `almond` | `168592` | sr_legacy_food | cup=144 | 零漂移 | — |
| `apple` | `2709215` | FNDDS | cup=125, piece=200, slice=25 | piece 200→165; +qns=200; +serving=34 | 200 |
| `avocado` | `2709223` | FNDDS | cup=150, slice=15 | +qns=30 | 30 |
| `banana` | `2709224` | FNDDS | cup=150, piece=126, slice=6 | +qns=126 | 126 |
| `beef` | `171793` | sr_legacy_food | — | 零漂移 | — |
| `black_beans` | `173735` | sr_legacy_food | cup=172 | 零漂移 | — |
| `broccoli` | `2709643` | FNDDS | cup=90, piece=10 | +qns=45 | 45 |
| `cheddar` | `2705709` | FNDDS | cup=132, slice=21 | cup 132→113; slice 21→9; +cubic_inch=17; +qns=21 | 21 |
| `chicken_breast` | `171477` | sr_legacy_food | cup=140 | 零漂移 | — |
| `egg` | `2707152` | FNDDS | cup=245, piece=50 | +qns=50 | 50 |
| `greek_yogurt` | `2705424` | FNDDS | cup=245 | +qns=150 | 150 |
| `milk_whole` | `2705385` | FNDDS | cup=244 | +fl_oz=30.5; +qns=244 | 244 |
| `oats` | `2708489` | FNDDS | cup=80 | +qns=10 | 10 |
| `olive_oil` | `171413` | sr_legacy_food | cup=216, tbsp=13.5, tsp=4.5 | 零漂移 | — |
| `orange` | `2709171` | FNDDS | cup=180, slice=15 | +qns=154 | 154 |
| `pasta` | `2708357` | FNDDS | cup=140 | +oz=80; +qns=140 | 140 |
| `peanut_butter` | `2707537` | FNDDS | tbsp=16 | +qns=32; +serving=45 | 32 |
| `potato` | `2709383` | FNDDS | cup=130, piece=230 | +qns=285 | 285 |
| `salmon` | `171998` | sr_legacy_food | — | 零漂移 | — |
| `shrimp` | `175180` | sr_legacy_food | — | 零漂移 | — |
| `soy_milk` | `2705404` | FNDDS | cup=244 | +fl_oz=30.5; +qns=244 | 244 |
| `spinach` | `2709614` | FNDDS | cup=25 | +qns=13 | 13 |
| `tofu` | `172448` | sr_legacy_food | cup=126 | 零漂移 | — |
| `tuna` | `171986` | sr_legacy_food | can=165 | 零漂移 | — |
| `white_rice` | `2708408` | FNDDS | cup=158 | +qns=118 | 118 |

### 旧键被改的 gold 食物

| food_id | 变化 |
|---|---|
| `apple` | piece 200→165 |
| `cheddar` | cup 132→113; slice 21→9 |

### Gold 克数会变的条目

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

## QNS 覆盖

- FNDDS 对比集里带 `qns` 键的食物: **5326** / 5395
- Gold 25 种里来自 FNDDS 的: **16**；其中有 QNS 的: **16**（其余为 SR Legacy，survey.zip 无行，本 dry-run 不动它们）

QNS 与当前 serving 回退（piece→slice→cup）一致的 gold 食物:

- `apple` QNS=200 = piece 200
- `banana` QNS=126 = piece 126
- `cheddar` QNS=21 = slice 21
- `egg` QNS=50 = piece 50
- `milk_whole` QNS=244 = cup 244
- `pasta` QNS=140 = cup 140
- `soy_milk` QNS=244 = cup 244

QNS 与 serving 回退不一致（日后改 serving 回退时的灰区候选）:

- `avocado` QNS=30 ≠ serving-default slice=15
- `broccoli` QNS=45 ≠ serving-default piece=10
- `greek_yogurt` QNS=150 ≠ serving-default cup=245
- `oats` QNS=10 ≠ serving-default cup=80
- `orange` QNS=154 ≠ serving-default slice=15
- `peanut_butter` QNS=32（无 piece/slice/cup）
- `potato` QNS=285 ≠ serving-default piece=230
- `spinach` QNS=13 ≠ serving-default cup=25
- `white_rice` QNS=118 ≠ serving-default cup=158

## 落地建议（本脚本未改 builder）

按本 dry-run 的 seq_num + first-wins **不能**直接重建 catalog：gold 旧键非零漂移，14 条冻结克数会变。

若要完整接入且冻结 split 零漂移，builder 应改成 **旧键冻结、只追加新键**：
cup/tbsp/tsp/slice/piece/can 保持当前 catalog 值；只插入当前没有的 thick/thin/regular/oz/fl_oz/cubic_inch/serving/qns。
该「安全叠加」下 gold 条目漂移数为 **0**，旧键零漂移成立。

复合 `piece/slice` 建议在落地时采用本脚本的双写规则，但 **不得覆盖** 已经存在的 piece/slice 值（先冻结旧键，再双写缺失的那一侧）。这样牛排一类食物会补上 `piece=30`（与现有 `slice=30` 相同），而 cheddar 的 `slice=21` 不会被 seq 1 的 cracker-size 9 g 抢走。

seq_num 排序适合作为新键的稳定顺序，不适合用来重选旧键赢家。

