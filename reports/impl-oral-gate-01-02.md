# 实现报告：ticket 01 + 02 — oracle gate 放行真实口语

日期：2026-08-18
范围：源码 + 测试 + `react.py` 手册。未改 `data/splits/*.json`、`data/fdc/*.sqlite`、`tests/test_freeze_guard.py` 哈希断言。未 rebuild catalog，未跑 live LLM。

复跑：

```
.venv/bin/python -m pytest -q
.venv/bin/python scripts/landing_verify.py
```

## 1. 改了哪些文件

| 文件 | 改动 |
|---|---|
| `src/nutrienv/bench/validator.py` | `validate_oracle_grams` 增加 query-traceable 口语克数第二锚点；`_validate_evaluate` 共用同一绑定；克数短语只绑它所修饰的食物 NP（fix round 1） |
| `src/nutrienv/world/portions.py` | 裸食物名词 → `portions.piece`；切法/身体部位无 PortionFact 键仍 `None`；dish-noun 命中后不再回落到裸名词 |
| `src/nutrienv/harness/react.py` | `_SYSTEM_V1_TAIL` 追加裸名词 / 切法拒绝一行 |
| `tests/test_oral_grams_gate.py` | **新增**。ticket 01 表驱动 + freezer + evaluate 绑定 + v1.0-gold 哈希 |
| `tests/test_portions.py` | ticket 02 裸名词 / 切法拒绝 / 手册对称 |
| `reports/impl-oral-gate-01-02.md` | 本报告 |

## 2. 行为

### Ticket 01 — log/freezer 口语克数通道

每个 oracle `(food_id, grams)` 合法当且仅当：

1. `matches_portion_table`（原 PortionFact × {0.5,1,1.5,2} + 盎司倍数），或
2. query 里有一个口语克数短语**修饰该食物**（见 `_modified_food_span`），且 `resolve_portion(food_id, phrase, catalog)` 得到同一克数。

绑定取克数短语后的食物 NP：跳过 `of`/`in` 和冠词，在 `and`/`with`/`after`/逗号等处截断。`150 g of rice with chicken` 只绑 rice。短语后为空时回退到短语前的 NP（`chicken 150 g`）。

`_validate_evaluate` 的旧通道（query 里任意口语克数给任意食物放行）已删，改为调用同一 `_query_traceable_grams`。

### Ticket 02 — 裸名词默认份量

单位扫描与 dish-noun 都未命中后：

- `"one apple"` / `"a banana"` / `"two eggs"` → `quantity × portions.piece`
- 短语里出现切法/身体部位词（`breast`/`chop`/`fillet`…）且 catalog 无该键 → `None`，不猜 cup/QNS
- 无 `piece` 键 → `None`

**未走 `_serving_default`（qns→piece→slice→cup）。** 原因：catalog-v1 `apple` 的 qns=200、piece=165；验收要求 `"one apple" → 165`。QNS 已是 `"a serving of X"` 的语义。若用 `_serving_default`，`"a chicken breast"` 会猜到 cup=140，与「无锚点切法必须拒绝」冲突。

`two eggs`：ticket 写 200.0（piece 100×2）。catalog-v1 `egg.piece=50`（FNDDS 表值），实现为 **100.0**，不另造克数。

## 3. 新增测试

`tests/test_oral_grams_gate.py`：

- `"Please log that I ate 150 g of chicken."` / `150g` / `150 grams` / `150 g chicken` → `validate_oracle_grams` 空
- 同上题 `freeze_tasks` 可冻结
- `"a cup of chicken"` 140.0 仍过（PortionFact 零回归）
- query 未说克数 + 150 非表倍数 → 拒
- `"150 g of rice"` 不能给 chicken 150 放行
- evaluate：`"150 g of Greek yogurt"` 仍过；`"150 g of rice and a cup of chicken"` 不能给 chicken 150 放行
- v1.0-gold 20 题仍过，sha256 钉死

`tests/test_portions.py`：

- catalog-v1：`one apple` 165 / `a banana` 126 / `two eggs` 100 / `an apple` 165 / `one egg` 50
- `a chicken breast` / `half a chicken breast` / `one chicken breast` / `two chicken breasts` → `None`
- 手册含 `"one apple"` / `"a banana"` / `"two eggs"` / `"a chicken breast"`，且解析与手册一致

## 4. 验证

| 检查 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **988 passed**（基线 957；01/02 +22；r1–r3 +8；r5 +1） |
| `scripts/landing_verify.py` | **PASS**（v0.5 240 题 `validate_draft` 0 fail；v1.0-gold 20 题 draft+grams 0 fail） |
| `data/splits/v1.0-gold.json` sha256 | `39dc756c7c8ab7986f02e324b7e9e8f7099fcc68aa5b3c07870bf374a8a2c6ac`（不变） |
| 交叉影响 | evaluate 收紧后既有 EVALUATE_ROWS / v0.5 / v1.0-gold 全绿；fix round 1 只改 validator 绑定 |

## 5. 未决

1. `reports/oral-gate-audit.md` 落盘时不存在。验收话术取自 ticket / scout 任务正文（T1=`150 g of chicken`，T2=`one apple` / `a banana` / `two eggs`）。审计报告若后补「必须放行」条目，需再对照补测。
2. ticket 02 写 `two eggs → 200.0`；按 catalog-v1 表值做成 100.0。
3. `HANDBOOK_VOCABULARY` / expander 未改；裸名词只进了 `_SYSTEM_V1_TAIL`。expander 若要产出 `"one apple"` 需另开任务。

## 6. fix round 1（codex 阻断修复）

Codex `reports/review-oral-gate-01-02.md` REQUEST-CHANGES：同子句 `150 g of rice with chicken` 把 150 错绑到 chicken。

**只改** `validator.py` 绑定 + `tests/test_oral_grams_gate.py`。`portions.py` / `react.py` 未碰。

最终语义：口语克数只授权它修饰的那个食物 NP，不是同子句里的任意食物。`150 g of chicken` → chicken；`150 g of rice with chicken` → rice；`150 g of chicken and 200 g of rice` → 各自绑定。

新增 4 个测试函数（覆盖审查要求的 log/evaluate 故障注入）：

1. log `"Please log 150 g of rice with chicken"` / chicken 150 → 拒
2. log `"Please log 150 g of chicken and a cup of rice"` / chicken 150 过；同句 rice 走 cup=158（catalog-v1 表值，不是 ticket 笔误的 140）过
3. evaluate `"Evaluate: 150 g of rice with chicken"` / chicken 150 → 拒
4. evaluate Greek yogurt 150 原用例不回归（既有测试）
5. `"150 g of chicken and 200 g of rice"` log+evaluate 各自绑定；对调克数则拒

pytest **983 passed**；landing PASS；v1.0-gold 哈希不变。

## 7. fix round 2（后置克数串首 break）

Codex 复审：`chicken 150 g with rice` 把 150 错绑到 rice。根因是 `_modified_food_span` 对 gram 后文本先 `.lstrip()`，而 `_GRAM_NP_BREAK` 的单词分支要求 `\s+`，串首 `with`/`and` 不成 break，after span 吃到 rice，无法回退到 gram 前的 chicken NP。逗号版本碰巧正常。

**只改** `validator.py` 的 `_GRAM_NP_BREAK`（`(?:^|\s+)`）+ `tests/test_oral_grams_gate.py`。`portions.py` / `react.py` 未碰。

绑定语义不变，补上 lstrip 后的串首 adjunct：`chicken 150 g with rice` → after 为空 → 回退 chicken；`chicken 150 g and rice 200 g` → 各自绑定。

新增 2 个测试函数（log + evaluate 各覆盖）：

- `chicken 150 g with rice`：chicken 150 过，rice 150 拒
- `chicken 150 g and rice 200 g`：各自过；交换克数拒
- 上一轮 `150 g of rice with chicken`（拒）与 `150 g of chicken and 200 g of rice`（各自过）不回归

pytest **985 passed**；landing PASS；v1.0-gold 哈希不变。

## 8. fix round 3（终局）

Codex round 3：无连接词相邻克数串 fail-open。`150 g of chicken 200 g of rice` 的首 gram after-span 吞入后续食物和 gram，rice 150 被错误授权。`chicken 150 g rice 200 g` 同根因。

**只改** `validator.py` 绑定 + `tests/test_oral_grams_gate.py`。`portions.py` / `react.py` 未碰。

fail-closed 语义：

1. modified span 夹在相邻 `_EXPLICIT_GRAMS` 命中之间，前一个克数不吞后一个。
2. `of`/`in` 补语优先（`150 g of chicken` → chicken）。
3. 前后都有真实食物 NP 且不是 `of`/`in` 结构 → 配对不唯一 → 该克数不授权任何食物。
4. `log`/`please` 等 frame 词不是食物 NP，所以 `Log 150 g chicken` 仍过。

因此：`150 g of chicken 200 g of rice` → chicken 150 过、rice 200 过、rice 150 拒、chicken 200 拒。`chicken 150 g rice 200 g` → 第一克数 fail-closed（chicken 150 与 rice 150 都拒），rice 200 仍可绑后一个局部 NP。

新增 2 个授权矩阵测试（log + evaluate）：

- `150 g of chicken 200 g of rice`：正确组合过，交叉克数拒
- `chicken 150 g rice 200 g`：无 fail-open；第一克数 fail-closed

上一轮正例不回归。pytest **987 passed**；landing PASS；v1.0-gold 哈希不变。

## 9. round 5 合入前微修

Codex 终局 APPROVE-WITH-NOTES 的两条 note，主 agent 裁决都修。只改 `validator.py` + `tests/test_oral_grams_gate.py`。

**Note 1：** `_query_traceable_grams` 不再对每个 oracle food 独立 `_food_mentioned_in`。对 modified span 收集 spoken n-gram 命中的 **canonical food identity**（`canonical_food_id`，staple slug 与数字 FDC 算同一个），仅当集合恰好是 `{目标食物}` 时授权。span 里两个 identity（如 `150 g of chicken rice`）→ 该克数不授权任何食物。别用 `and` 做反例：`150 g of chicken and rice` 会在 `and` 处截断，测不到同 span 双 identity。

**Note 2：** `_authorizes(..., evaluate=True)` 改为 `validate_draft`，只看是否存在目标食物的 `evaluate grams ...` issue（忽略缺失 profile/window）。

新增 1 个测试：`150 g of chicken rice` log+evaluate，chicken 150 与 rice 150 都拒。

pytest **988 passed**；landing PASS；v1.0-gold 哈希不变。
