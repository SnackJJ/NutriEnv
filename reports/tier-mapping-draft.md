# Tier 内容映射草案（issue 15 #3 的裁决输入）

> **Status:** technical proposal for the main-agent ruling. tier **数据通道**已实现
> （generate_one tier=" 参数 + recipe channel `evaluate:tier`，claude RELEASE）。
> 本草案回答"每个 tier 对应什么题面形状 + 现有代码支撑到哪"，供裁决后直接实施。
> 不替代裁决：允许你改映射/数字。

## tier 六档的语义假设（源自 v0.3 迁移的难度寓意 + 现有词表）

| tier（底线） | 题面特征假设 | 现有代码支撑 |
|---|---|---|
| single (7) | 单食物 evaluate（一餐一食） | `AMOUNT_PATHS` 任一 + 1 食物 pool；`evaluate.py` realize 支持单行 |
| pair (11) | 双食物（一餐两食） | 2 食物 pool；`multi_item` realize 行 |
| triple (11) | 三食物（一餐三食） | 3 食物 pool；`multi_item` realize 行 |
| long (5) | 长话术 evaluate（带杂讯/多从句的 query） | 需 expander 产出长 query 的 shell；现无专门 long shell |
| explicit_grams (4) | 题面显式说克数（"150 g of X"） | `amount_path="explicit_grams"` + `_SYSTEM_V1_TAIL` 的 "Grams (\"150 g\")" 行 |
| synonym (3) | 用别名/俗名（"PB" for peanut butter、学名互换） | `near_synonym.py` realize 行 + 别名解析（match_spoken 别名覆盖） |

## 缺口（实施前需补的）

1. **long** 无专门 shell：需一个 expander 模板产长 query（或现有 `_fit_expander` 的陈述式就够长？需试产判定）。
2. **synonym** 依赖 catalog 别名丰富度 + near_synonym 行；需验证哪几个食物有可用的俗名/别名（如 peanut butter ↔ PB）。
3. tier 与 pool 食物数（1/2/3）的绑定：recipe channel 的 `evaluate:tier=triple` 目前**不控制 pool 大小**（pool 是 sample_pools 随机 8 食物，resolver 只取候选板子里的食物）。要让 tier=triple 真产三食物题，需要 recipe 也控制"取该 tier 的食物数"（`evaluate:items=N` 之类）或 pool 预过滤。

## 建议的落地方式（裁决后执行）

- recipe channel 增加 `evaluate:items=N` knob（或 tier→默认 items 映射：single=1/pair=2/triple=3，long/explicit_grams/synonym=1 但配不同 amount_path/shell）。
- explicit_grams 映射到 `--recipe evaluate:amount_path=explicit_grams`（若 recipe 目前不支持 amount_path，需加）。
- synonym 用 near_synonym realize 行验证后，映射到"含别名食物的 pool 过滤"。
- long 用现有陈述式 expander 产长 query（试产判定是否够）。

## 待裁决

1. tier→items 映射（single 1 / pair 2 / triple 3）是否认可？
2. explicit_grams/synonym/long 是否按上表映射，还是你另有词典？
3. recipe 是否增加 `items`/`amount_path` knob（还是 tier 直接隐含）？