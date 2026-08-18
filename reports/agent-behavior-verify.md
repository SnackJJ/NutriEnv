# 08 — agent 考试行为验证（catalog-v2 + 手册对称）

日期：2026-08-18
范围：catalog-v2 工具缝 + **live ReAct v1** 考试轨迹。灰区结果送 Opus 终裁，本文件不自称 GATE_SAFE。

复跑：

```
.venv/bin/python scripts/agent_behavior_verify.py --model deepseek-v4-flash-0731
.venv/bin/python -m pytest -q tests/test_agent_behavior_verify.py
```

## 1. 本轮相对 e58e023 改了什么

| 发现 | 改动 |
|---|---|
| 1 灰区未跑真 agent | 删除 `_HandbookLogHarness` 的 oracle-pass 测试。灰区 6 题走 live ReAct，轨迹如下。 |
| 2 未验证真实 ReAct | `ReActHarness` 用 `lookup_chat_model` 路由 `deepseek-v4-flash-0731` / `qwen3.7-flash-2026-07-15` 到 DashScope；本脚本跑 v1 手册。 |
| 3 search chicken 丢 staple | `_search_fts` 把 **精确 alias**（`aliases` 分词集 == query）插到 BM25 前。`q="chicken"` → 2705956。不是 get_food 注入。 |

## 2. search 决策

BM25 `q="chicken"` 原先 top 25 不含 2705956。`_promote_alias_hits` 只重排已返回的行。
这是可修的排序缺口：staple 已有精确 alias `chicken`。
修复后 `search_foods "chicken"` 第一名是 2705956，`get_food` 观察 `piece=105`。
精确匹配避免把 egg 的 alias `chicken egg` 提上来。
同一 `FoodCatalog.search` 也作用于 `catalog.sqlite`：`q="chicken"` 现在第一名是旧 SR staple `171477`。
冻结 split / oracle 未改；只改变 live agent 的检索排序。

## 3. 手册 / 表值（确定性，非 live 断言）

| 短语 | resolve_portion |
|---|---|
| a piece of chicken | 105 |
| 150 g of chicken | 150 |
| one apple | 165 |
| half a cup of milk | 122（cup=qns=244 / 2） |
| a chicken breast | None |
| sandwich piece / a sandwich | 175 / 115 |
| lasagna piece / a serving | 206 / 250 |
| omelet piece / an omelet | 55 / 110 |

QNS vs first-wins：chicken 120 vs 105；tuna 85 vs 75；beef 85 vs 65。

## 4. Live ReAct 轨迹

- 模型：`deepseek-v4-flash-0731`
- harness：`react-v1`
- catalog：`data/fdc/catalog-v2.sqlite`
- max_steps：12

| id | group | query | oracle | passed | tag | ops | ledger |
|---|---|---|---|---|---|---|---|
| `oral-piece-chicken` | oral | Please log a piece of chicken. | 2705956 105.0g | **PASS** | pass | `search_foods,get_food,log_meal,finish` | 2705956 105.0g |
| `oral-150g-chicken` | oral | Please log that I ate 150 g of chicken. | 2705956 150.0g | **PASS** | pass | `search_foods,log_meal,finish` | 2705956 150.0g |
| `oral-one-apple` | oral | Please log one apple. | 2709215 165.0g | **PASS** | pass | `search_foods,get_food,log_meal,finish` | 2709215 165.0g |
| `oral-half-cup-milk` | oral | Please log half a cup of milk. | 2705385 122.0g | **PASS** | pass | `search_foods,get_food,log_meal,finish` | 2705385 122.0g |
| `oral-chicken-breast` | oral | Please log a chicken breast. | empty ledger | **FAIL** | log_miss | `search_foods,get_food,log_meal,finish` | 2705956 105.0g |
| `gray-sandwich-piece` | gray | Please log a piece of sandwich. | 2706880 175.0g | **PASS** | pass | `search_foods,get_food,log_meal,finish` | 2706880 175.0g |
| `gray-sandwich-qns` | gray | Please log a sandwich. | 2706880 115.0g | **PASS** | pass | `search_foods,get_food,get_food,log_meal,finish` | 2706880 115.0g |
| `gray-lasagna-piece` | gray | Please log a piece of lasagna. | 2708750 206.0g | **PASS** | pass | `search_foods,get_food,log_meal,finish` | 2708750 206.0g |
| `gray-lasagna-qns` | gray | Please log a serving of lasagna. | 2708750 250.0g | **PASS** | pass | `search_foods,get_food,log_meal,log_meal,finish` | 2708750 250.0g |
| `gray-omelet-piece` | gray | Please log a piece of omelet. | 2707198 55.0g | **PASS** | pass | `search_foods,get_food,get_food,log_meal,finish` | 2707198 55.0g |
| `gray-omelet-qns` | gray | Please log an omelet. | 2707198 110.0g | **PASS** | pass | `search_foods,get_food,log_meal,log_meal,finish` | 2707198 110.0g |

### 逐步动作

#### `oral-piece-chicken` — Please log a piece of chicken.

first-wins piece; agent must find 2705956 via search, not injected slug

- `search_foods` q='chicken' hits=['2705956', '2706087', '2706081', '2706083', '2706084', '2706085', '2706091', '2706154']
- `get_food` id=2705956 portions={'cup': 135.0, 'piece': 105.0, 'slice': 30.0, 'oz': 28.35, 'qns': 120.0}
- `log_meal` {'food_id': '2705956', 'grams': 105.0, 'eaten_at': 'now'}
- `finish`

#### `oral-150g-chicken` — Please log that I ate 150 g of chicken.

spoken grams

- `search_foods` q='chicken' hits=['2705956', '2706087', '2706081', '2706083', '2706084', '2706085', '2706091', '2706154']
- `log_meal` {'food_id': '2705956', 'grams': 150.0, 'eaten_at': 'now'}
- `finish`

#### `oral-one-apple` — Please log one apple.

bare noun → piece

- `search_foods` q='apple' hits=['2709215', '2707995', '2708019', '2708023', '2708039', '2709196', '2709220', '2709294']
- `get_food` id=2709215 portions={'piece': 165.0, 'slice': 25.0, 'cup': 125.0, 'serving': 34.0, 'qns': 200.0}
- `log_meal` {'food_id': '2709215', 'grams': 165.0, 'eaten_at': 'now'}
- `finish`

#### `oral-half-cup-milk` — Please log half a cup of milk.

cup=qns=244 / 2

- `search_foods` q='milk' hits=['2705385', '2705404', '2705384', '2705395', '2705411', '2705412', '2705413', '2705501']
- `get_food` id=2705385 portions={'cup': 244.0, 'fl_oz': 30.5, 'qns': 244.0}
- `log_meal` {'food_id': '2705385', 'grams': 122.0, 'eaten_at': 'now'}
- `finish`

#### `oral-chicken-breast` — Please log a chicken breast.

ticket 02: cut noun stays None; empty ledger is the oracle

- `search_foods` q='chicken breast' hits=['2705956', '2705963', '2705965', '2705971', '2705964', '2705966', '2705972', '2705967']
- `get_food` id=2705956 portions={'cup': 135.0, 'piece': 105.0, 'slice': 30.0, 'oz': 28.35, 'qns': 120.0}
- `log_meal` {'food_id': '2705956', 'grams': 105.0, 'eaten_at': 'now'}
- `finish`

#### `gray-sandwich-piece` — Please log a piece of sandwich.

sandwich 1.5× pair, piece

- `search_foods` q='sandwich' hits=['2706880', '2706946', '2706952', '2706962', '2706973', '2706977', '2707033', '2707055']
- `get_food` id=2706880 portions={'regular': 115.0, 'piece': 175.0, 'qns': 115.0}
- `log_meal` {'food_id': '2706880', 'grams': 175.0, 'eaten_at': 'now'}
- `finish`

#### `gray-sandwich-qns` — Please log a sandwich.

sandwich 1.5× pair, qns via dish noun

- `search_foods` q='sandwich' hits=['2706880', '2706946', '2706952', '2706962', '2706973', '2706977', '2707033', '2707055']
- `get_food` error={'code': 'bad_schema', 'message': "'food_id' must be a string"}
- `get_food` id=2706880 portions={'regular': 115.0, 'piece': 175.0, 'qns': 115.0}
- `log_meal` {'food_id': '2706880', 'grams': 115.0, 'eaten_at': 'now'}
- `finish`

#### `gray-lasagna-piece` — Please log a piece of lasagna.

lasagna 1.2× pair, piece

- `search_foods` q='lasagna' hits=['2708758', '2708750', '2708751', '2708754', '2708759', '2708752', '2708753', '2708755']
- `get_food` id=2708750 portions={'piece': 206.0, 'cup': 250.0, 'qns': 250.0}
- `log_meal` {'food_id': '2708750', 'grams': 206.0, 'eaten_at': 'now'}
- `finish`

#### `gray-lasagna-qns` — Please log a serving of lasagna.

lasagna 1.2× pair, serving/qns

- `search_foods` q='lasagna' hits=['2708758', '2708750', '2708751', '2708754', '2708759', '2708752', '2708753', '2708755']
- `get_food` id=2708750 portions={'piece': 206.0, 'cup': 250.0, 'qns': 250.0}
- `log_meal` error={'code': 'bad_schema', 'message': "'food_id' must be a string"}
- `log_meal` {'food_id': '2708750', 'grams': 250.0, 'eaten_at': 'now'}
- `finish`

#### `gray-omelet-piece` — Please log a piece of omelet.

omelet 2.0× pair, piece

- `search_foods` q='omelet' hits=['2710807', '2710781', '2710808', '2710806', '2707199', '2707200', '2707201', '2707205']
- `get_food` error={'code': 'bad_schema', 'message': "'food_id' must be a string"}
- `get_food` id=2707198 portions={'piece': 55.0, 'cup': 135.0, 'qns': 110.0}
- `log_meal` {'food_id': '2707198', 'grams': 55.0, 'eaten_at': 'now'}
- `finish`

#### `gray-omelet-qns` — Please log an omelet.

omelet 2.0× pair, dish noun/qns

- `search_foods` q='omelet' hits=['2710807', '2710781', '2710808', '2710806', '2707199', '2707200', '2707201', '2707205']
- `get_food` id=2707198 portions={'piece': 55.0, 'cup': 135.0, 'qns': 110.0}
- `log_meal` error={'code': 'bad_schema', 'message': "'food_id' must be a string"}
- `log_meal` {'food_id': '2707198', 'grams': 110.0, 'eaten_at': 'now'}
- `finish`

## 5. 灰区（送 Opus）

6 题 live ReAct，**6/6** end state 命中表值 oracle（sandwich 175/115、lasagna 206/250、omelet 55/110）。
轨迹里有几次 `food_id` 非字符串的 `bad_schema`，agent 重试后写对了。
omelet 的 BM25 前 8 名不含 2707198，agent 仍 `get_food` 到了该 id。
lasagna search 第一名是 meatless `2708758`，agent 选了表值题的 `2708750`。

本文件不封 gate。Opus 看上表轨迹后裁决。

## 6. 观测到的手册偏离（不假装没发生）

`oral-chicken-breast`：**FAIL** `log_miss`。手册写裸切块名词无 default、要克数；`resolve_portion(..., "a chicken breast")` 仍是 None。
live `deepseek-v4-flash-0731` 搜 `chicken breast` → `get_food 2705956`（piece=105）→ 记了 105 g。
这是观测到的 agent 行为，不是 resolver 行为。pytest 不断言这题 Pass。

`oral-150g-chicken` 搜到 2705956 后直接 `log_meal 150`，没再 `get_food`。克数来自 query 字面，end state 命中 oracle。

## 7. 机器可读结果

`reports/agent-behavior-verify.json`

## 8. pytest

| 检查 | 结果 |
|---|---|
| `tests/test_agent_behavior_verify.py` + `test_react.py` routing | 通过（不断言 live Pass） |
| 全量 pytest | **1016 passed** |

