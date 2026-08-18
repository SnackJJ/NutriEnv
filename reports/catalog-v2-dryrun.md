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
- 构建策略与 catalog-v1 相同（`--full`：seq_num first-wins），只是不 ingest
  SR Legacy，并把 10 个 SR staple 重钉到 FNDDS 等价条目。
- v0.5-gold 绑 `catalog.sqlite`（sha 见该 split 的 `catalog_sha256`），
  本 dry-run 与日后 catalog-v2 对其零影响。

## 食物数对账

- 当前 `catalog.sqlite` / `catalog-v1.sqlite` 的 `survey_fndds_food`：**5431**
- 当前 `sr_legacy_food`：**7793**（catalog-v2 将全部丢弃）
- catalog-v2 预计食物数：**5431**（= 对账后的 FNDDS 数）
- catalog-v1 内 `survey_fndds_food`：**5431**
  （与 live 一致则对账闭合）

票面曾写 5432：那是 `survey.zip` `food.csv` 行数。其中 `2705383` Milk, human
无 kcal，builder 不入库，所以 catalog 实测是 **5431**。catalog-v2 用 5431，
不硬编码 5432。

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
SR 行的形态就近选 catalog-v1 里已有的 FNDDS 行（cooked patty / unroasted /
olive oil / dried no-fat beans）。详见每条 PortionFact。

## 哪些食物克数会变

相对 **catalog-v1**（同 `--full` 策略）：FNDDS 食物份量键 **0 变**。变化只来自
10 个 staple 别名换条目（旧 SR 行随 7793 条 SR 一起消失）。

相对 **catalog.sqlite**（v0.5 safe-overlay）：FNDDS 旧键还有 catalog-v1 已记录
的 861 处取值变化（见 `reports/catalog-v1-dryrun.md`）。那些变化已经在
catalog-v1 落地；catalog-v2 继承 catalog-v1 的 FNDDS 份量，不再另变。
v0.5-gold 不读 catalog-v2，冻结 JSON 克数不动。

| slug | 当前 portions | FNDDS portions | 克数变化 |
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

## 每条 staple 的 FNDDS target + PortionFact

### `chicken_breast` → `2705956` Chicken breast, baked, broiled, or roasted, skin not eaten, from raw

- 当前：`171477` [sr_legacy_food] Chicken, broilers or fryers, breast, meat only, cooked, roasted
- 新 portions：`cup=135, oz=28.35, piece=105, qns=120, slice=30`
- 选型：票面候选。对应 SR 去皮烤胸；piece=105 是 catalog-v1 完整策略对 2705956 的 first-wins 行。
- PortionFact：`a piece` → **105 g**（resolve_portion=105.0，通过）
- 票面例句 `a chicken breast`：resolve_portion=None（ticket 02 切块名词保持 None；piece=105 可解析的是 `a piece`，不是裸 `a chicken breast`）

### `tuna` → `2706311` Fish, tuna, canned

- 当前：`171986` [sr_legacy_food] Fish, tuna, light, canned in water, without salt, drained solids
- 新 portions：`can=75, cup=135, qns=85`
- 选型：票面候选。对应 SR 水浸罐头；FNDDS can=75（SR can=165）。
- PortionFact：`a can` → **75 g**（resolve_portion=75.0，通过）

### `tofu` → `2707435` Soybean curd

- 当前：`172448` [sr_legacy_food] Tofu, firm, prepared with calcium sulfate and magnesium chloride (nigari)
- 新 portions：`cubic_inch=17.6, cup=248, piece=120, qns=62`
- 选型：AGY 核验：FNDDS 纯豆腐官方名 Soybean curd（底层 SR 16127 为 soft）。当前 SR 钉的是 firm；cup 126→248。
- PortionFact：`a piece` → **120 g**（resolve_portion=120.0，通过）

### `salmon` → `2706286` Fish, salmon, baked or broiled

- 当前：`171998` [sr_legacy_food] Fish, salmon, Atlantic, wild, cooked, dry heat
- 新 portions：`cubic_inch=17, cup=135, oz=20, piece=140, qns=140`
- 选型：SR 是 cooked dry heat。选 baked or broiled（2706286），与 NFS 2706285 同份量表；不用 raw 2706284（无 piece）。
- PortionFact：`a piece` → **140 g**（resolve_portion=140.0，通过）

### `shrimp` → `2706363` Shrimp, steamed or boiled

- 当前：`175180` [sr_legacy_food] Crustaceans, shrimp, cooked
- 新 portions：`cup=135, piece=10, qns=85`
- 选型：SR 是 cooked。选 steamed or boiled（2706363），与 NFS 2706360 同份量表。
- PortionFact：`a piece` → **10 g**（resolve_portion=10.0，通过）

### `beef` → `2705855` Beef, ground, patty

- 当前：`171793` [sr_legacy_food] Beef, ground, 90% lean meat / 10% fat, patty, cooked, pan-broiled
- 新 portions：`cubic_inch=17, cup=125, oz=20, piece=65, qns=85`
- 选型：SR 是 90/10 cooked patty。选 Beef, ground, patty（2705855，piece=65）；不用无 piece 的 2705854 Beef, ground。
- PortionFact：`a piece` → **65 g**（resolve_portion=65.0，通过）

### `olive_oil` → `2710186` Olive oil

- 当前：`171413` [sr_legacy_food] Oil, olive, salad or cooking
- 新 portions：`cup=224, qns=14, tbsp=14`
- 选型：FNDDS 唯一纯橄榄油行 2710186。tbsp 13.5→14；无 tsp。
- PortionFact：`a tablespoon` → **14 g**（resolve_portion=14.0，通过）

### `black_beans` → `2707361` Black beans, from dried, no added fat

- 当前：`173735` [sr_legacy_food] Beans, black, mature seeds, cooked, boiled, without salt
- 新 portions：`cup=180, oz=70, qns=90`
- 选型：SR 是 boiled without salt。选 from dried, no added fat（2707361）；不用 NFS 2707359（cup=185）或 canned。
- PortionFact：`a cup` → **180 g**（resolve_portion=180.0，通过）

### `peanut` → `2707514` Peanuts, unroasted

- 当前：`172430` [sr_legacy_food] Peanuts, all types, raw
- 新 portions：`cup=146, oz=28.35, qns=28`
- 选型：SR 是 raw。选 unroasted 2707514；cup 仍 146，补 oz/qns。
- PortionFact：`a cup` → **146 g**（resolve_portion=146.0，通过）

### `almond` → `2707486` Almonds, unroasted

- 当前：`168592` [sr_legacy_food] Nuts, almonds, honey roasted, unblanched
- 新 portions：`cup=141, oz=28.35, qns=28`
- 选型：当前 SR 168592 是 honey roasted（name-match 误伤）。针写 Almonds, raw → unroasted 2707486。
- PortionFact：`a cup` → **141 g**（resolve_portion=141.0，通过）

## v0.5-gold 影响（绑旧 catalog，零落地）

split 里这 10 个 slug 共 **97** 行（peanut 不在 gold 25 里）。
冻结克数写在 JSON 里，不随 catalog-v2 变。若有人误把 v0.5 指到 catalog-v2，
别名会换 FDC id、营养素与份量表都会变；household 克数（tuna can 165、
tofu cup 126、black_beans cup 172、olive_oil tbsp 13.5 / tsp 4.5）将不再
等于新表。**本票不改 v0.5-gold，也不改 catalog.sqlite。**

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

## 验收冲突（STEP 1 记下，不改 resolve_portion）

ticket 06 验收 2 写 chicken `"a chicken breast"` → piece 105g。
ticket 02 已把 `breast` 列为切块名词：无同名 portion 键则 `resolve_portion`
返回 None（`tests/test_portions.py` 钉死）。2705956 的 PortionFact 是
`piece=105`；`a piece` 解析为 105g，裸 `a chicken breast` 仍是 None。
STEP 2 落地前由主 agent 裁定是否改语法，本 dry-run 不猜。

## 裁决请求

请 codex 独立审查本清单，主 agent 裁决 APPROVE 后再允许：
`build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite`。

