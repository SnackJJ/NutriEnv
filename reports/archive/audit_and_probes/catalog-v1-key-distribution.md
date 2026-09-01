# catalog-v1 键分布

构建：`.venv/bin/python scripts/build_fdc_catalog.py --full --out data/fdc/catalog-v1.sqlite`

`data/fdc/catalog.sqlite`（v0.5 safe-overlay）未改。完整策略按
`scripts/fndds_dry_run.py` POLICY：`(fdc_id, seq_num, portion id)` 排序后
first-wins；`1 piece/slice` 双写；`oz` 而非 `oz_yield`；包装行不算 oz。

## 文件

| 产物 | SHA-256 |
|---|---|
| `data/fdc/catalog-v1.sqlite`（两次构建字节相同） | `f49e4f904905abbb8b4ebb02c908935f01776280a2c00b3de1a3e890cad5ae91` |
| `data/fdc/catalog.sqlite`（未改） | `ff2f26325cc0cc71c3230f82060997afaeefcad0051b09989c662ac0b0fa2d90` |

复现：同命令写到临时路径，`cmp` 与上表 catalog-v1 哈希一致。

## 食物数

| 集合 | 数量 |
|---|---:|
| catalog-v1 总食物 | **13224** |
| `survey_fndds_food` | **5431** |
| 其中有 ≥1 份量键 | **5394** |
| 其中份量为空（as-ingredient 等） | 37 |
| `sr_legacy_food` | **7793** |
| 其中有 ≥1 份量键 | 3875 |
| staple aliases | 27（oats=`2708489`，chicken_breast=`171477`，与 v0.5 相同） |

5394 vs dry-run 的 5395：survey 另有 `2705383` Milk, human（`cup=246`，`fl_oz=30.8`，无 qns）因缺少 kcal 未写入 catalog，与 v0.5 builder 的 ingest 过滤一致。

## QNS 覆盖

- FNDDS 有份量的食物带 `qns`：**5326 / 5394 ≈ 98.7%**
- dry-run 分母是 5395（含 Milk, human）；该食物无 qns，catalog-v1 不收录它，分子同为 5326。
- `oz_yield` 食物数：**0**（键名落地为 `oz`）

## 新键食物数（FNDDS）

| 键 | catalog-v1 | 相对 catalog.sqlite |
|---|---:|---:|
| `thick` | 54 | 0 |
| `thin` | 55 | −1 |
| `regular` | 267 | −186 |
| `oz` | 556 | +314 |
| `oz_yield` | 0 | −304 |
| `fl_oz` | 631 | +3 |
| `cubic_inch` | 382 | 0 |
| `serving` | 79 | +79 |
| `qns` | 5326 | 0 |

与 `reports/catalog-v1-dryrun.md` 的增删表一致。`fl_oz` dry-run 写 +4，其中 1 条是未入库的 Milk, human，catalog 内实为 +3。`regular` −186 / `thin` −1 是 household 或 piece 塌缩赢了尺寸键。`oz_yield` 304 条改为同克数 `oz`（另有部分食物本身已是 `oz`）。

## Gold 25

v0.5-gold 用到的 25 种食物（16 FNDDS + 9 SR Legacy）。apple `piece` 200→165；cheddar `slice` 21→9、`cup` 132→113。SR Legacy 份量未改。

| food_id | fdc_id | 类型 | catalog-v1 portions |
|---|---|---|---|
| `almond` | `168592` | sr_legacy_food | cup=144 |
| `apple` | `2709215` | FNDDS | piece=165, slice=25, cup=125, serving=34, qns=200 |
| `avocado` | `2709223` | FNDDS | slice=15, cup=150, qns=30 |
| `banana` | `2709224` | FNDDS | piece=126, slice=6, cup=150, qns=126 |
| `beef` | `171793` | sr_legacy_food | — |
| `black_beans` | `173735` | sr_legacy_food | cup=172 |
| `broccoli` | `2709643` | FNDDS | cup=90, piece=10, qns=45 |
| `cheddar` | `2705709` | FNDDS | slice=9, cup=113, cubic_inch=17, qns=21 |
| `chicken_breast` | `171477` | sr_legacy_food | cup=140 |
| `egg` | `2707152` | FNDDS | piece=50, cup=245, qns=50 |
| `greek_yogurt` | `2705424` | FNDDS | cup=245, qns=150 |
| `milk_whole` | `2705385` | FNDDS | cup=244, fl_oz=30.5, qns=244 |
| `oats` | `2708489` | FNDDS | cup=80, qns=10 |
| `olive_oil` | `171413` | sr_legacy_food | tbsp=13.5, cup=216, tsp=4.5 |
| `orange` | `2709171` | FNDDS | slice=15, cup=180, qns=154 |
| `pasta` | `2708357` | FNDDS | cup=140, oz=80, qns=140 |
| `peanut_butter` | `2707537` | FNDDS | tbsp=16, serving=45, qns=32 |
| `potato` | `2709383` | FNDDS | piece=230, cup=130, qns=285 |
| `salmon` | `171998` | sr_legacy_food | — |
| `shrimp` | `175180` | sr_legacy_food | — |
| `soy_milk` | `2705404` | FNDDS | cup=244, fl_oz=30.5, qns=244 |
| `spinach` | `2709614` | FNDDS | cup=25, qns=13 |
| `tofu` | `172448` | sr_legacy_food | cup=126 |
| `tuna` | `171986` | sr_legacy_food | can=165 |
| `white_rice` | `2708408` | FNDDS | cup=158, qns=118 |

白名单（`matches_portion_table` 读 catalog 全部份量值 × {0.5,1,1.5,2} + 固定 2 oz）：apple 165 在表上；cheddar 9 / 113 在表上；各食物 qns 在表上。apple 200 与 cheddar 21 仍在表上（它们是 qns，不是被替换掉的旧 piece/slice）。cheddar 旧 cup 132 不在表上。
