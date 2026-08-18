# catalog-v2 dry-run：FNDDS-only + staple 重钉

只读对照：**不写** `data/fdc/catalog-v2.sqlite`，不改 `catalog.sqlite`、
`catalog-v1.sqlite`、任何 `data/splits/*.json`。本文件是 AGENTS.md 纪律 2
要求的落地前清单，供 codex 审查 + 主 agent 裁决后再重建。

复跑：

```
.venv/bin/python scripts/build_fdc_catalog.py --fndds-only --dry-run
```

## 框定

- catalog-v2 是新文件（`data/fdc/catalog-v2.sqlite`），不覆盖
  `catalog.sqlite` 与 `catalog-v1.sqlite`。
- FNDDS 食物数与份量图来自 `survey.zip`（food.csv / food_nutrient /
  food_portion），不是现成 sqlite 的 COUNT / portions 拷贝。
- v0.5-gold 绑 `catalog.sqlite`，本 dry-run 与日后 catalog-v2 对其零影响。

## 食物数对账（survey.zip）

- `survey.zip` `food.csv` 行数：**5432**
- 无 kcal、不入库：**1**（`2705383`）
- catalog-v2 预计食物数：**5431**（= food.csv − 无 kcal，不硬编码）
- 当前 catalog 里仍有的 `sr_legacy_food`：**7793**（catalog-v2 将全部丢弃；此数只描述现状，不参与 FNDDS 计数）

## FNDDS 份量图：builder scan vs 独立 raw scan

- 源：`data/fdc/raw/survey.zip`
- builder `collect_portions_full` 有份量的食物：**5395**
- 独立 `fndds_dry_run.collect_full_fndds`：**5395**
- 两图不一致的食物数：**0**

零漂移指这两次 **survey.zip** 扫描一致，不是拿 catalog-v1.sqlite 自己比自己。

## 哪些 staple 换条目

| slug | 当前 SR id | 当前名 | FNDDS id | FNDDS 名 |
|---|---|---|---|---|
| `chicken_breast` | `171477` | Chicken, broilers or fryers, breast, meat only, cooked, roasted | `2705956` | Chicken breast, baked, broiled, or roasted, skin not eaten, from raw |
| `tuna` | `171986` | Fish, tuna, light, canned in water, without salt, drained solids | `2706311` | Fish, tuna, canned |
| `tofu` | `172448` | Tofu, firm, prepared with calcium sulfate and magnesium chloride (nigari) | `2707435` | Soybean curd |
| `salmon` | `171998` | Fish, salmon, Atlantic, wild, cooked, dry heat | `2706286` | Fish, salmon, baked or broiled |
| `shrimp` | `175180` | Crustaceans, shrimp, cooked | `2706363` | Shrimp, steamed or boiled |
| `beef` | `171793` | Beef, ground, 90% lean meat / 10% fat, patty, cooked, pan-broiled | `2705855` | Beef, ground, patty |
| `olive_oil` | `171413` | Oil, olive, salad or cooking | `2710186` | Olive oil |
| `black_beans` | `173735` | Beans, black, mature seeds, cooked, boiled, without salt | `2707361` | Black beans, from dried, no added fat |
| `peanut` | `172430` | Peanuts, all types, raw | `2707514` | Peanuts, unroasted |
| `almond` | `168592` | Nuts, almonds, honey roasted, unblanched | `2707486` | Almonds, unroasted |

选型说明：tofu / chicken / tuna 用票面已点名的 FNDDS id；其余 7 个按当前
SR 行的形态就近选 survey 里的 FNDDS 行。beef 丢失 90/10 瘦度、salmon 与
旧 wild 条目营养不等价，见下方披露。

## 哪些食物克数会变

FNDDS 食物份量键相对独立 raw scan **0 变**（上节）。变化只来自 10 个 staple
别名换条目（旧 SR 行随 SR Legacy 一起消失）。v0.5-gold 不读 catalog-v2。

| slug | 当前 SR portions | FNDDS portions（raw scan） | 克数变化 |
|---|---|---|---|
| `chicken_breast` | cup=140 | cup=135, oz=28.35, piece=105, qns=120, slice=30 | cup 140→135; +oz=28.35; +piece=105; +qns=120; +slice=30 |
| `tuna` | can=165 | can=75, cup=135, qns=85 | can 165→75; +cup=135; +qns=85 |
| `tofu` | cup=126 | cubic_inch=17.6, cup=248, piece=120, qns=62 | +cubic_inch=17.6; cup 126→248; +piece=120; +qns=62 |
| `salmon` | — | cubic_inch=17, cup=135, oz=20, piece=140, qns=140 | +cubic_inch=17; +cup=135; +oz=20; +piece=140; +qns=140 |
| `shrimp` | — | cup=135, piece=10, qns=85 | +cup=135; +piece=10; +qns=85 |
| `beef` | — | cubic_inch=17, cup=125, oz=20, piece=65, qns=85 | +cubic_inch=17; +cup=125; +oz=20; +piece=65; +qns=85 |
| `olive_oil` | cup=216, tbsp=13.5, tsp=4.5 | cup=224, qns=14, tbsp=14 | cup 216→224; +qns=14; tbsp 13.5→14; -tsp=4.5 |
| `black_beans` | cup=172 | cup=180, oz=70, qns=90 | cup 172→180; +oz=70; +qns=90 |
| `peanut` | cup=146 | cup=146, oz=28.35, qns=28 | +oz=28.35; +qns=28 |
| `almond` | cup=144 | cup=141, oz=28.35, qns=28 | cup 144→141; +oz=28.35; +qns=28 |

## 每条 staple 的 raw PortionFact + 规范化键

先写 FNDDS 原行（含 small/regular/medium 等修饰），再写 resolver 规范化键。

### `chicken_breast` → `2705956` Chicken breast, baked, broiled, or roasted, skin not eaten, from raw

- 当前：`171477` [sr_legacy_food] Chicken, broilers or fryers, breast, meat only, cooked, roasted
- 选型：票面候选。对应 SR 去皮烤胸。raw first-wins 行是 `1 small breast`=105g，规范化为 piece=105。裸 a chicken breast 按 ticket 02 仍是 None。
- **raw PortionFact**：`1 small breast` = **105 g**
- 规范化 resolver 键：`piece=105`（`a piece` → resolve_portion=105.0，通过）
- 规范化后 portions：`cup=135, oz=28.35, piece=105, qns=120, slice=30`
- ticket 02 仍成立：`a chicken breast` → None（切块名词，不是 piece）

### `tuna` → `2706311` Fish, tuna, canned

- 当前：`171986` [sr_legacy_food] Fish, tuna, light, canned in water, without salt, drained solids
- 选型：票面候选。对应 SR 水浸罐头；FNDDS can=75（SR can=165）。
- **raw PortionFact**：`1 small can` = **75 g**
- 规范化 resolver 键：`can=75`（`a can` → resolve_portion=75.0，通过）
- 规范化后 portions：`can=75, cup=135, qns=85`

### `tofu` → `2707435` Soybean curd

- 当前：`172448` [sr_legacy_food] Tofu, firm, prepared with calcium sulfate and magnesium chloride (nigari)
- 选型：AGY 核验：FNDDS 纯豆腐官方名 Soybean curd（底层 SR 16127 为 soft）。当前 SR 钉的是 firm；cup 126→248。
- **raw PortionFact**：`1 piece (2-1/2" x 2-3/4" x 1")` = **120 g**
- 规范化 resolver 键：`piece=120`（`a piece` → resolve_portion=120.0，通过）
- 规范化后 portions：`cubic_inch=17.6, cup=248, piece=120, qns=62`

### `salmon` → `2706286` Fish, salmon, baked or broiled

- 当前：`171998` [sr_legacy_food] Fish, salmon, Atlantic, wild, cooked, dry heat
- 选型：SR 是 Atlantic wild, cooked, dry heat。FNDDS 2706286 是 baked or broiled、未标野捕/品种，营养素不等价（见 nutrition_deltas）。
- **raw PortionFact**：`1 small/regular fillet` = **140 g**
- 规范化 resolver 键：`piece=140`（`a piece` → resolve_portion=140.0，通过）
- 规范化后 portions：`cubic_inch=17, cup=135, oz=20, piece=140, qns=140`

### `shrimp` → `2706363` Shrimp, steamed or boiled

- 当前：`175180` [sr_legacy_food] Crustaceans, shrimp, cooked
- 选型：SR 是 cooked。选 steamed or boiled（2706363），与 NFS 2706360 同份量表。
- **raw PortionFact**：`1 small/medium shrimp` = **10 g**
- 规范化 resolver 键：`piece=10`（`a piece` → resolve_portion=10.0，通过）
- 规范化后 portions：`cup=135, piece=10, qns=85`

### `beef` → `2705855` Beef, ground, patty

- 当前：`171793` [sr_legacy_food] Beef, ground, 90% lean meat / 10% fat, patty, cooked, pan-broiled
- 选型：SR 是 90/10 cooked patty。FNDDS 2705855 是 Beef, ground, patty，丢失 90/10 瘦度（见 nutrition_deltas）。
- **raw PortionFact**：`1 small patty` = **65 g**
- 规范化 resolver 键：`piece=65`（`a piece` → resolve_portion=65.0，通过）
- 规范化后 portions：`cubic_inch=17, cup=125, oz=20, piece=65, qns=85`

### `olive_oil` → `2710186` Olive oil

- 当前：`171413` [sr_legacy_food] Oil, olive, salad or cooking
- 选型：FNDDS 唯一纯橄榄油行 2710186。tbsp 13.5→14；无 tsp。
- **raw PortionFact**：`1 tablespoon` = **14 g**
- 规范化 resolver 键：`tbsp=14`（`a tablespoon` → resolve_portion=14.0，通过）
- 规范化后 portions：`cup=224, qns=14, tbsp=14`

### `black_beans` → `2707361` Black beans, from dried, no added fat

- 当前：`173735` [sr_legacy_food] Beans, black, mature seeds, cooked, boiled, without salt
- 选型：SR 是 boiled without salt。选 from dried, no added fat（2707361）；不用 NFS 2707359（cup=185）或 canned。
- **raw PortionFact**：`1 cup` = **180 g**
- 规范化 resolver 键：`cup=180`（`a cup` → resolve_portion=180.0，通过）
- 规范化后 portions：`cup=180, oz=70, qns=90`

### `peanut` → `2707514` Peanuts, unroasted

- 当前：`172430` [sr_legacy_food] Peanuts, all types, raw
- 选型：SR 是 raw。选 unroasted 2707514；cup 仍 146，补 oz/qns。
- **raw PortionFact**：`1 cup, without shell, NS as to form` = **146 g**
- 规范化 resolver 键：`cup=146`（`a cup` → resolve_portion=146.0，通过）
- 规范化后 portions：`cup=146, oz=28.35, qns=28`

### `almond` → `2707486` Almonds, unroasted

- 当前：`168592` [sr_legacy_food] Nuts, almonds, honey roasted, unblanched
- 选型：当前 SR 168592 是 honey roasted（name-match 误伤）。针写 Almonds, raw → unroasted 2707486。
- **raw PortionFact**：`1 cup` = **141 g**
- 规范化 resolver 键：`cup=141`（`a cup` → resolve_portion=141.0，通过）
- 规范化后 portions：`cup=141, oz=28.35, qns=28`

## 营养素披露（beef 瘦度 / salmon 野捕）

每 100 g，来自 `sr_legacy.zip` / `survey.zip` 的 food_nutrient，不是 sqlite。

### `beef`

- Beef loses 90/10 leanness: SR 171793 is '90% lean meat / 10% fat, patty, cooked, pan-broiled'; FNDDS 2705855 is generic 'Beef, ground, patty' (NFS fat).
- SR `171793`：kcal=204, protein_g=25.21, fat_g=10.68, carb_g=0, sodium_mg=75, fiber_g=0
- FNDDS `2705855`：kcal=272, protein_g=25.45, fat_g=18.18, carb_g=0, sodium_mg=383, fiber_g=0

### `salmon`

- Salmon is not nutritionally equivalent to the old wild entry: SR 171998 is 'Atlantic, wild, cooked, dry heat'; FNDDS 2706286 is 'baked or broiled' with no wild/species tag.
- SR `171998`：kcal=182, protein_g=25.44, fat_g=8.13, carb_g=0, sodium_mg=56, fiber_g=0
- FNDDS `2706286`：kcal=274, protein_g=25.4, fat_g=18.4, carb_g=0.01, sodium_mg=294, fiber_g=0

## v0.5-gold 影响（绑旧 catalog，零落地）

split 里这 10 个 slug 共 **97** 行（peanut 不在 gold 25 里）。
冻结克数写在 JSON 里，不随 catalog-v2 变。**本票不改 v0.5-gold，
也不改 catalog.sqlite。**

| slug | gold 行数 |
|---|---:|
| `chicken_breast` | 25 |
| `tuna` | 9 |
| `tofu` | 8 |
| `salmon` | 10 |
| `shrimp` | 5 |
| `beef` | 9 |
| `olive_oil` | 21 |
| `black_beans` | 5 |
| `peanut` | 0 |
| `almond` | 5 |

## ticket 02 仍成立

验收 2 已改为：chicken piece 锚点 = 105g（raw `1 small breast`）；
裸 `"a chicken breast"` 按 ticket 02 保持 None。本 dry-run 不改
`resolve_portion`。

## 裁决请求

请 codex 独立审查本清单，主 agent 裁决 APPROVE 后再允许：
`build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite`。

