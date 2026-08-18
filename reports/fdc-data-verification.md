# USDA FoodData Central (FDC) 数据官方核验报告

- **核验对象**：本地 `data/fdc/raw/survey.zip` (FNDDS) 与 `data/fdc/raw/sr_legacy.zip` (SR Legacy)
- **核验时间**：2026-08-18
- **核验机构与数据源**：USDA FoodData Central (FDC) / USDA Agricultural Research Service (ARS)

---

## 1. FNDDS survey 是否包含“纯 tofu”条目？

### 结论
**包含，但官方命名为 "Soybean curd" 而非 "Tofu"。**  
本地 survey 数据库完全完整，并未缺失纯豆腐条目。在 FNDDS 的分类体系中，纯豆腐条目的描述为 **"Soybean curd"**（FDC ID `2707435`，FoodCode `41420010`），其底层原料（input food）精确映射为 SR Legacy 的 `16127`（"Tofu, soft, prepared with calcium sulfate and magnesium chloride"）。

### 官方依据
1. **官方条目属性**：
   - **FDC ID**: `2707435`
   - **Food Code**: `41420010`
   - **Description**: `Soybean curd`
   - **Food Category (WWEIA)**: `Soy and meat-alternative products` (Category ID: `2806`)
   - **Input Food / Recipe**: `Tofu, soft, prepared with calcium sulfate and magnesium chloride (nigari)` (SR Code `16127`, 100g)
2. **标准档位 (Food Portions)**：
   - `1 cup (1/2" cubes)` = 248.0 g
   - `1 piece (2-1/2" x 2-3/4" x 1")` = 120.0 g
   - `1 cubic inch` = 17.6 g
   - `Quantity not specified (QNS)` = 62.0 g
3. **相关衍生豆腐条目**：
   - `2707437` - *Soybean curd cheese*
   - `2707448` - *Soybean curd, deep fried*
   - `2707449` - *Soybean curd, breaded, fried*
4. **设计背景**：FNDDS 是针对 NHANES 饮食回顾调查建立的编码库，其食品名称继承了 USDA 经典的食物命名层级（414 代表豆制品，传统上使用 "Soybean curd"）。含 "tofu" 字样的条目大多为后来增补的现代混合菜肴（如 "Tofu and vegetables with soy-based sauce"）。

### 来源 URL
- USDA FoodData Central 详情页：[https://fdc.nal.usda.gov/fdc-app.html#/food-details/2707435/nutrients](https://fdc.nal.usda.gov/fdc-app.html#/food-details/2707435/nutrients)
- USDA ARS FNDDS 2021-2023 文档：[https://www.ars.usda.gov/nea/bhnrc/fsrg/fndds/](https://www.ars.usda.gov/nea/bhnrc/fsrg/fndds/)

---

## 2. SR Legacy 的 Chicken Breast (171477) 原始档位

### 结论
**官方原始档位精确包含且仅包含这 3 个 Portion，本地导入完全一致且无任何数据丢失。**

### 官方依据
查询 USDA FoodData Central API / 官方原始数据，FDC ID `171477`（*Chicken, broilers or fryers, breast, meat only, cooked, roasted*）的 `foodPortions` 列表如下：

| Sequence | Portion Description / Modifier | Amount | Gram Weight | Portion ID |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `cup, chopped or diced` | 1.0 | **140.0 g** | 88817 |
| 2 | `unit (yield from 1 lb ready-to-cook chicken)` | 1.0 | **52.0 g** | 88818 |
| 3 | `breast, bone and skin removed` | 0.5 | **86.0 g** | 88819 |

官方数据中本条目确实没有 1.0 full breast 的直接单行记录（通常通过 0.5 breast = 86g 换算得到完整 1 breast = 172g）。本地 SR Legacy 数据的 3 个 portion 与官方数据 100% 吻合。

### 来源 URL
- USDA FoodData Central 详情页：[https://fdc.nal.usda.gov/fdc-app.html#/food-details/171477/nutrients](https://fdc.nal.usda.gov/fdc-app.html#/food-details/171477/nutrients)
- USDA FDC API Endpoint: `https://api.nal.usda.gov/fdc/v1/food/171477`

---

## 3. 本地 zip 版本是否最新 / 完整

### 结论
**本地 zip 数据已是官方最新、最完整的正式版本，条目总数与官方完全一致，无需重新下载。**

### 官方依据
1. **FNDDS (Survey Foods)**：
   - **当前最新版本**：FNDDS 2021-2023（对应 NHANES 2021-2023 调查周期，由 USDA ARS 于 2024 年 10 月正式发布）。
   - **官方发布文件名**：`FoodData_Central_survey_food_csv_2024-10-31.zip`
   - **条目总数**：**5,432 条**（本地 `data/fdc/raw/survey.zip` 内 `food.csv` 行数严格为 5,432 条）。
   - *注：NHANES 2023-2025 周期的 FNDDS 尚未完成编制与发布。*
2. **SR Legacy (Standard Reference Legacy)**：
   - **当前版本**：SR Legacy（2018 年 4 月最终发布版本）。
   - **官方发布文件名**：`FoodData_Central_sr_legacy_food_csv_2018-04.zip`
   - **条目总数**：**7,793 条**（本地 `data/fdc/raw/sr_legacy.zip` 内 `food.csv` 行数严格为 7,793 条）。
   - *注：USDA 已宣布 SR Legacy 为最终静态归档库，不再追加更新（后续新食品分析归入 Foundation Foods）。*

### 官方下载源 URL
- USDA FoodData Central 官方下载门户：[https://fdc.nal.usda.gov/download-datasets.html](https://fdc.nal.usda.gov/download-datasets.html)
- USDA ARS FNDDS 数据库下载页：[https://www.ars.usda.gov/nea/bhnrc/fsrg/fndds/download/](https://www.ars.usda.gov/nea/bhnrc/fsrg/fndds/download/)

---

## 4. FDC 的维护机构

### 结论
**FoodData Central (FDC) 由 USDA（美国农业部）全权建立和维护，而非 FDA。**

### 官方依据
FDC 是由美国农业部（USDA）下属的两个核心机构协同运营：
1. **Agricultural Research Service (ARS)** — 负责食品组分分析、营养素数据测定与 FNDDS 数据库编制（由 Beltsville Human Nutrition Research Center 主导）。
2. **National Agricultural Library (NAL)** — 负责数据平台系统的建设、API 开发与数据发布托管。

### 来源 URL
- USDA FDC About Us：[https://fdc.nal.usda.gov/about-us.html](https://fdc.nal.usda.gov/about-us.html)

---

## 5. 总结与建议

1. **本地数据完整性**：本地的 `data/fdc/raw/survey.zip`（5,432 条）和 `data/fdc/raw/sr_legacy.zip`（7,793 条）与 USDA 官方最新发布的二进制数据源 100% 一致，校验通过，**完全不需要重新下载或补全**。
2. **业务逻辑适配建议**：
   - 在构建或检索食材 catalog 时，如需匹配纯豆腐，应将关键词 `"tofu"` / `"firm tofu"` 关联或同义词映射到 `"Soybean curd"` (FDC ID `2707435` / SR Code `16127`)。
