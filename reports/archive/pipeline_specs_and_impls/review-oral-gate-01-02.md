# Ticket 01 + 02 实现复核（Codex）

日期：2026-08-18  
范围：未提交工作树相对 `HEAD` 的 ticket 01/02 实现；只读审查与验证，未修改源码、测试或数据。  
总体结论：**REQUEST-CHANGES**

阻断原因只有一个：ticket 01 的口语克数并未真正绑定到食物短语，只绑定到粗粒度“子句”。同一子句出现多个食物时，属于 rice 的 `150 g` 仍可给 chicken 150g 放行。Ticket 02 的两处声明偏差均应批准，不应为了符合错误/冲突的 ticket 文案而回改实现。

## A. Spec 轴

### 关键发现（阻断）

`src/nutrienv/bench/validator.py:296-305` 先判断目标食物是否出现在子句任意位置，再遍历该子句内所有克数；它没有证明某个克数短语修饰该食物。`_GRAM_CLAUSE_SPLIT` 仅按 `and`、逗号、分号和句点切分，因此以下独立探针错误放行：

```text
log query: "Please log 150 g of rice with chicken."
oracle: chicken (171477), 150.0 g
validate_oracle_grams => []                         # 应拒绝

evaluate query: "Evaluate this lunch: 150 g of rice with chicken."
oracle plan: chicken 150.0 g + rice 158.0 g
validate_draft => 无 chicken grams issue            # 应拒绝 chicken 150
```

现有故障注入只覆盖了纯 `150 g of rice`，以及用 `and` 主动切开的 evaluate 句子（`tests/test_oral_grams_gate.py:102-111,137-147`），没有覆盖“同一子句多个食物”。这不满足 ticket 01 的核心要求“该食物的克数绑定”，也没有完整维持 fail-closed。

建议修复：让 gram span 与其修饰/相邻的 food mention 建立局部关联，而不是“同一 clause 任意 gram × 任意 food”；至少补 log 与 evaluate 两条 `150 g of rice with chicken` 故障注入。修复后重跑本报告的全部验证。

### Ticket 01 验收逐条

| 验收 | 结论 | 证据 / 裁决 |
|---|---|---|
| 1. log 150g chicken 过 gate 且可冻结 | **PASS** | 独立 log 探针返回 `[]`；`tests/test_oral_grams_gate.py:49-76` 覆盖 gate 与 freezer。 |
| 2. cup 不回归；rice 克数不能授权 chicken | **FAIL** | cup 140g 与纯 `150 g of rice` 均符合预期；但同一子句 `150 g of rice with chicken` 错误授权 chicken。 |
| 3. 未说克数且非 PortionFact 倍数仍拒绝 | **PASS** | 独立探针 `Please log the chicken I ate.` / chicken 150g 返回 portion-table issue；测试亦覆盖。 |
| 4. evaluate 收紧且按食物绑定 | **FAIL** | Greek yogurt 150g 与既有 evaluate 题通过；但同子句反例同样错误放行 chicken。 |
| 5. v1.0 20 题、v0.5 基线及 split 哈希不变 | **PASS** | landing：v0.5 240/0 failing；v1.0 20/0 failing；哈希一致。 |
| 6. 全量 pytest 与 landing | **PASS** | `979 passed`；landing `RESULT: PASS`。 |
| 7. Codex 双轴审查通过 | **FAIL** | Standards PASS；Spec 因上述绑定缺陷 FAIL。 |

### Ticket 02 验收逐条

| 验收 | 票面结论 | 实现裁决 |
|---|---|---|
| 1. apple 165 / banana 126 / two eggs 200 | **FAIL（ticket 数值错误）** | 实测 165 / 126 / **100**。catalog-v1 `2707152` 的 `piece=50.0`，故 two eggs 必须是 100.0。**APPROVE 实现；修 ticket，不改代码。** |
| 2. 裸名词等于 `_serving_default`（qns→piece→slice→cup） | **FAIL（ticket 内部冲突）** | apple 的 qns=200、piece=165；照默认链会直接违反验收 1。裸计数名词走 `piece` 的语义更准确，且避免 chicken breast 猜 cup。**APPROVE piece-only；修 ticket 文案。** |
| 3. chicken breast / half chicken breast 仍 None | **PASS** | 指定 numeric ID `171477` 独立探针为 `None`；参数化测试覆盖 4 种形式。 |
| 4. react 手册对称；判分规则不动 | **PASS** | `_SYSTEM_V1_TAIL` 明确 bare noun→piece、无 key cut→ask grams（`react.py:66`）；评分说明未改，Scorer 无 diff。 |
| 5. 冻结题与其他单位零回归 | **PASS** | 全量测试、landing、哈希均通过；cup/serving/dish 等既有定向测试通过。 |
| 6. 全量测试与 Codex 审查 | **FAIL** | 测试全绿，但同一交付中的 ticket 01 Spec 阻断，故整体审查不能批准。 |

### 三个偏差裁决点

1. **`two eggs = 100.0`：APPROVE。** catalog-v1 实值为 `egg.piece=50.0`，来自当前冻结数据锚点；ticket 的 `piece 100×2` 与表值冲突。按 AGENTS.md 的 FNDDS/QNS 锚点纪律，不能制造 200g。
2. **裸名词只走 `piece`：APPROVE。** `one apple` 表达可数个体，piece=165；QNS=200 是“quantity not specified”，不应覆盖明确的 one。现有显式 `a serving of X` 仍走原 unit/default 分支，dish noun 仍走 `_dish_noun_grams`，全量 fuzzy/portion 回归通过。注意 catalog 中若有显式 `serving` key，现有 resolver 会优先该 key；本改动未改变此行为。
3. **`_SYSTEM_V1_TAIL` 手册对称：APPROVE。** 手册与实现一致地描述 bare noun→piece 和无 portion key 的 cut 拒绝；判分规则、Scorer、冻结 split 均未改。

### 并发出现的 audit 报告（非本 ticket 阻断）

收尾时工作树中新增了本审查未创建的 `reports/oral-gate-audit.md`。其中把 `a 6 oz container of Greek yogurt → 170.1g` 列为建议“必须放行”，并称 ticket 01 覆盖；独立探针显示当前 `validate_oracle_grams` 仍拒绝它。原因是新 trace 通道只匹配 `g/gram(s)`，而原 ounce whitelist 只有 `{0.5,1,1.5,2} oz`，不含 6 oz。

这不改变本次结论：ticket 01 明文范围是口语**克数**，audit 的清单也是后续建议，不是既有验收标准。若主 agent 将该建议升级为 requirement，应另开/扩 ticket，明确任意 spoken ounces（以及 container 词）是否进入 query-traceable 通道并补 gate/手册对称测试；不能声称当前 ticket 已覆盖。

## B. Standards 轴

结论：**PASS（0 硬违规，1 非阻断建议）**。

- 测试风格总体符合仓库约定：`test_portions.py` 使用参数化表驱动；oral gate 测试包含合法、缺锚、错食物、evaluate rebound 和 freezer 故障注入。Spec 阻断反例尚缺测试，但这是覆盖需求缺口，不是独立的编码规范违规。
- fail-closed、小型确定性语法以及表值作为唯一克数来源符合 `AGENTS.md`。`_CUT_NOUNS` / `_NAME_STOP` 虽新增规则较多，但服务于保守拒绝，未构成明显过度设计。
- **非阻断 Duplicated Code（judgement call）：** 已新增 `_food_query_names` / `_food_mentioned_in`，但 `_validate_evaluate` 的第二轮 food-mentioned 检查（`validator.py:625-631`）仍手写同一套 food_id/name/aliases 拼接；`_validate_condition` 也有相似形状。可后续复用 helper，本 ticket 不必因此扩 scope。
- `git diff --check HEAD` 通过。`data/splits/*.json`、`data/fdc/*.sqlite`、`tests/test_freeze_guard.py` 均无 diff/status 变更；未越界。

## 独立验证结果

| 命令 / 探针 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **979 passed in 289.66s** |
| `.venv/bin/python scripts/landing_verify.py` | **RESULT: PASS**；v0.5 `240 items, 0 failing`；v1.0 `20 items, 0 failing`（draft 与 grams） |
| `sha256sum data/splits/v1.0-gold.json` | `39dc756c7c8ab7986f02e324b7e9e8f7099fcc68aa5b3c07870bf374a8a2c6ac` |
| `resolve_portion("2709215", "one apple")` | **165.0** |
| `resolve_portion("2707152", "two eggs")` | **100.0**；entry `piece=50.0`, `qns=50.0` |
| `resolve_portion("171477", "a chicken breast")` | **None**；entry 只有 `cup=140.0` |
| log `150 g of chicken`, oracle chicken 150g | `validate_oracle_grams == []` |
| log `150 g of rice`, oracle chicken 150g | 正确拒绝 |
| log/evaluate `150 g of rice with chicken`, chicken 150g | **错误放行（阻断反例）** |

## 最终结论

**REQUEST-CHANGES。** 修复 ticket 01 的 gram-to-food 局部绑定并补同子句多食物的 log/evaluate 故障注入后再审。Ticket 02 实现可保留；应同步修正 ticket 中 `two eggs=200` 与裸名词走 `_serving_default` 两处错误/冲突描述。

## 复审（round 2）

日期：2026-08-18  
结论：**REQUEST-CHANGES**

上一轮的三个阻断反例已经修复，任务明列的双克数、后置克数（句尾）和无 `of/in` 裸写也均通过。但 NP break 在被检查字符串开头时仍失效，导致一个与后置克数直接相邻的错绑：`chicken 150 g with rice` 会拒绝 chicken 150g、反而授权 rice 150g；log/evaluate 均可复现。这仍违反 ticket 01 的核心不变量“克数只授权它修饰的食物 NP”。

### Spec 复现结果

| 独立探针 | 期望 | 实际 |
|---|---|---|
| log：`150 g of rice with chicken`，oracle chicken 150g | 拒绝 | **PASS**：返回 chicken `171477` portion-table issue |
| evaluate：`150 g of rice with chicken`，plan chicken 150g | 拒绝 | **PASS**：返回 chicken `171477` grams issue |
| evaluate：`chicken with 150 g of rice`，plan chicken 150g | 拒绝 | **PASS**：返回 chicken `171477` grams issue |
| log：`150 g of chicken and 200 g of rice`，对应 oracle | 两项通过 | **PASS**：无 grams issue |
| evaluate：同上，对应 plan | 两项通过 | **PASS**：无 grams issue |
| log/evaluate：同上但交换 150/200 | 两项均拒 | **PASS**：chicken 200 与 rice 150 均有 grams issue |
| log：`chicken 150 g`，oracle chicken 150g | 通过 | **PASS**；反向 rice 150g 被拒 |
| log：`150 g chicken`，oracle chicken 150g | 通过 | **PASS**；反向 rice 150g 被拒 |
| log：`150 g chicken with rice`，oracle chicken/rice 150g | 只授权 chicken | **PASS**：chicken 通过、rice 被拒 |
| log/evaluate：`chicken 150 g with rice` | 只授权 chicken | **FAIL（阻断）**：chicken 被拒、rice 被错误授权 150g |
| log：`chicken 150 g and rice 200 g` | 各自绑定 | **FAIL（同根因）**：chicken 150g 漏绑；逗号版本可通过 |

根因在 `src/nutrienv/bench/validator.py`：`_modified_food_span` 对 gram 后文本先 `.lstrip()`，而 `_GRAM_NP_BREAK` 的单词分支要求 `\s+` 前缀。于是 `with` / `and` 位于字符串开头时不是 break，代码不会得到空的 after span 并回退到 gram 前的 chicken NP；反而把后面的 rice 当作 modified span。标点分支不要求前导空白，所以逗号版本碰巧正常。

建议让 break 同时匹配字符串开头与空白之后（例如 `(?:^|\s+)`），并补至少以下 log + evaluate 故障注入：

- `chicken 150 g with rice`：chicken 150 通过，rice 150 拒绝；
- `chicken 150 g and rice 200 g`：两项各自通过，交换克数拒绝。

### Standards 与改动范围

Standards：**PASS（0 硬违规，1 非阻断建议）**。预编译 regex 与三个职责明确的 helper 被 log/evaluate 共用，复杂度与局部语法需求相称；新增测试包含正例、错绑和 swapped 故障注入。非阻断建议仍是 `_food_query_names` 与 validator 中既有 name/aliases 收集逻辑有小范围重复，可后续统一。

round 2 的文件时间戳及与上一轮已审内容对比显示，仅 `src/nutrienv/bench/validator.py`（08:32）与 `tests/test_oral_grams_gate.py`（08:31）在修复时更新；`src/nutrienv/world/portions.py`（08:01）和 `src/nutrienv/harness/react.py`（07:58）的内容与 round 1 相同，未被本轮触碰。由于所有实现均未提交，Git 只能显示它们相对 `HEAD` 的累计 diff，不能单独证明 round 1→2 的历史边界；上述结论由内容对比、时间戳和实现报告第 6 节交叉确认。

### 独立验证（round 2）

| 检查 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **983 passed in 292.38s** |
| `.venv/bin/python scripts/landing_verify.py` | **RESULT: PASS**；v0.5 240/0 failing；v1.0 20/0 failing |
| `sha256sum data/splits/v1.0-gold.json` | `39dc756c7c8ab7986f02e324b7e9e8f7099fcc68aa5b3c07870bf374a8a2c6ac`（不变） |
| `git diff --check HEAD` | PASS |

复审裁决：**REQUEST-CHANGES**。原阻断已修，但串首 `with/and` break 导致后置 gram 错绑到后续食物，仍需修复并补对称测试后再审。

## 复审（round 3）

日期：2026-08-18  
结论：**REQUEST-CHANGES**

round 2 的串首 break 阻断已正确修复：`chicken 150 g with rice` 只授权 chicken，`chicken 150 g and rice 200 g` 能各自绑定且交换克数会全部拒绝，log/evaluate 对称。但本轮要求明确点名的“无连接词、相邻两个 gram span”仍会 fail-open：一个克数可授权另一个食物，违反 query-traceable 按食物绑定及 fail-closed，因此 ticket 01 尚不能结案。

### Spec 探针结果

| Query / oracle 探针 | Log | Evaluate | 裁决 |
|---|---|---|---|
| `chicken 150 g with rice`；chicken 150 | 通过 | 通过 | **PASS** |
| 同上；rice 150 | 拒绝 | 拒绝 | **PASS** |
| `chicken 150 g and rice 200 g`；对应 150/200 | 两项通过 | 两项通过 | **PASS** |
| 同上；交换为 chicken 200 / rice 150 | 两项拒绝 | 两项拒绝 | **PASS** |
| `150 g chicken`；chicken 150 | 通过 | 通过 | **PASS**；rice 150 与错误克数均拒绝 |
| `chicken 150 g rice 200 g`；对应 150/200 | chicken 150 被拒；其余错误授权见下 | 同左 | **FAIL（阻断）** |
| `150 g of chicken 200 g of rice`；rice 150 | **错误通过** | **错误通过** | **FAIL（阻断）** |

`chicken 150 g rice 200 g` 的完整授权矩阵（log/evaluate 相同）：

```text
chicken 150 = reject       chicken 200 = ALLOW（错误）
rice 150    = ALLOW（错误） rice 200    = ALLOW
```

`150 g of chicken 200 g of rice` 的授权矩阵（log/evaluate 相同）：

```text
chicken 150 = ALLOW        chicken 200 = reject
rice 150    = ALLOW（错误） rice 200    = ALLOW
```

根因：`_modified_food_span` 只以连接词/adjunct/标点为边界，不把下一个 `_EXPLICIT_GRAMS` span 当边界，也不拒绝一个候选 span 中出现多个食物/克数。无连接词时，首个 gram 的 after-span 吞入后续食物和 gram；后置 gram 的 before-span 又可能包含前面多个食物，于是 `_food_mentioned_in` 能让同一 gram 值授权多个 food。

建议：gram-to-food 配对不得跨越相邻 gram span。对于无连接词的多个 `(food, gram)` / `(gram, food)` 串，如果不能确定唯一局部 NP，应整体或对应项 fail-closed；至少新增上述两条 query 的 log/evaluate 授权矩阵测试，而不只断言“正确组合”。

### Standards 与范围

Standards：**PASS（0 硬违规，1 非阻断重复建议）**。本轮 `(?:^|\s+)` 修复局部、注释一致；两项新增测试对 log/evaluate 覆盖正例、错食物和 swapped 克数。累计实现中的 `_food_query_names` 与既有 name/aliases 收集仍有小范围 Duplicated Code（judgement call），不应在本 ticket 扩 scope。

文件时间戳与 round 2 内容对比支持本轮仅更新 `src/nutrienv/bench/validator.py`（08:50）和 `tests/test_oral_grams_gate.py`（08:49）；`src/nutrienv/world/portions.py`（08:01）与 `src/nutrienv/harness/react.py`（07:58）未被本轮触碰。因改动始终未提交，Git 只能显示相对 `HEAD` 的累计 diff，轮次边界由内容对比、时间戳及实现报告第 7 节交叉确认。split/FDC/freeze guard 无状态变更，`git diff --check HEAD` 通过。

### 独立验证（round 3）

| 检查 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **985 passed in 299.09s** |
| `.venv/bin/python scripts/landing_verify.py` | **RESULT: PASS**；v0.5 240/0 failing；v1.0 20/0 failing |
| `sha256sum data/splits/v1.0-gold.json` | `39dc756c7c8ab7986f02e324b7e9e8f7099fcc68aa5b3c07870bf374a8a2c6ac`（不变） |

ticket 01 结案意见：**暂不结案 / REQUEST-CHANGES**。round 2 blocker 已消除，但相邻 gram span 仍能跨食物 fail-open；修复唯一局部配对并补授权矩阵故障注入后再终审。

## 复审（round 4·终局）

日期：2026-08-18  
终局结论：**APPROVE-WITH-NOTES（ticket 01 结案）**

round 3 的相邻 gram-span fail-open 已按 fail-closed 原则修复。必测授权矩阵在 log 与真正的 evaluate 通道（`validate_draft → _validate_evaluate`）完全一致；of/in 补语、后置克数、串首 with/and、无连接词多 gram、frame `Log 150 g chicken` 等既有类别均未发现新的缺陷类别。

### 必测授权矩阵

`150 g of chicken 200 g of rice`：

| 候选授权 | Log | Evaluate | 期望 |
|---|---|---|---|
| chicken 150 | ALLOW | ALLOW | ALLOW |
| chicken 200 | reject | reject | reject |
| rice 150 | reject | reject | reject |
| rice 200 | ALLOW | ALLOW | ALLOW |

`chicken 150 g rice 200 g`（第一克数前后都有真实食物 NP，配对不唯一）：

| 候选授权 | Log | Evaluate | 期望 |
|---|---|---|---|
| chicken 150 | reject | reject | reject / fail-closed |
| chicken 200 | reject | reject | reject |
| rice 150 | reject | reject | reject |
| rice 200 | ALLOW | ALLOW | ALLOW |

### 同类边界穷举摘要

| 类别 / query | 授权结果（log/evaluate 对称） | 裁决 |
|---|---|---|
| of：`150 g of chicken` | 仅 chicken 150 | PASS |
| in：`150 g in chicken` | 仅 chicken 150 | PASS |
| of + adjunct：`150 g of chicken with rice` | 仅 chicken 150 | PASS |
| 后置：`chicken 150 g` | 仅 chicken 150 | PASS |
| 串首 with：`chicken 150 g with rice` | 仅 chicken 150 | PASS |
| 后置 and 双量：`chicken 150 g and rice 200 g` | chicken 150 / rice 200；交叉拒 | PASS |
| 前置 and 双量：`150 g of chicken and 200 g of rice` | chicken 150 / rice 200；交叉拒 | PASS |
| frame：`Log 150 g chicken`、`Please log …`、`I ate …` | 仅 chicken 150 | PASS |
| 单 gram、无连接词双食物：`150 g chicken rice` | chicken 150 与 rice 150 均 ALLOW | **NOTE：同类别残余歧义** |
| of + 歧义双食物：`150 g of chicken rice` | chicken 150 与 rice 150 均 ALLOW | **NOTE：同类别残余歧义** |
| 后置歧义：`chicken rice 150 g` | chicken 150 与 rice 150 均 ALLOW | **NOTE：同类别残余歧义** |
| 双 gram + 歧义 NP：`150 g of chicken rice 200 g` | 四格均 ALLOW | **NOTE：同类别残余歧义** |

上述 note 不是新缺陷类别，而是 round 3 已识别的“无连接词多食物 / 唯一 NP”类别内残余：`_modified_food_span` 已确保不跨相邻 gram span，但 `_query_traceable_grams` 仍对每个 oracle food 独立调用 `_food_mentioned_in`，没有验证同一个 span 只命中一个 catalog food。因此一个包含 chicken 与 rice 两个食物词的 span 能分别授权两者。

最小后续修复建议：对 span 收集规范化后的 catalog food 命中，只在唯一 food identity 命中且等于目标 food 时授权；多个 food identity 命中则 fail-closed。需注意 staple alias / numeric FDC key 可能指向同一 canonical entry，去重应按 canonical food identity，而不是 raw catalog key。按用户终局规则，此为同类小漏点，记录后由主 agent 直接裁决，不再要求新一轮。

另有同类 false-negative note：`_GRAM_FRAME` 是有限词表，`Record/Track/Please add/Could you log 150 g chicken` 会 fail-closed，而 `Log/Please log/I ate` 正常。这不会造成错食物授权；若扩真实 command frame，可在后续补 frame 词或改为更结构化的前缀识别。

### Standards 轴与测试说明

生产实现未见新 standards 阻断；helper/regex 复杂度有清楚注释支撑，round 4 仍是局部 fail-closed 修改。累计 `_food_query_names` 与既有 name/aliases 收集的 Duplicated Code 继续作为非阻断 judgement-call note。

但新增测试有一处覆盖声明不准确：`tests/test_oral_grams_gate.py` 的 `_authorizes(..., evaluate=True)` 虽构造 evaluate Task，最终仍无条件调用 `validate_oracle_grams`，没有走 `validate_draft → _validate_evaluate`。因此两个 round 4 矩阵测试验证了通用 oracle gate 对 `last_plan` 的行为，却没有直接覆盖 evaluate family validator。最小修复是在 evaluate 分支调用 `validate_draft`，并只判断目标 `evaluate grams ...` issue，避免被 profile/window 等无关 issue 干扰。此项不阻断功能结案，因为本轮独立探针已用真实 `validate_draft` 重跑全部矩阵且结果正确，但建议合入前直接修正测试。

范围证据：内容对比和时间戳支持本轮仅更新 `src/nutrienv/bench/validator.py`（09:07）与 `tests/test_oral_grams_gate.py`（09:08）；`src/nutrienv/world/portions.py`（08:01）和 `src/nutrienv/harness/react.py`（07:58）未再触碰。未提交状态使 Git 只能显示累计 diff；split/FDC/freeze guard 无状态变更，`git diff --check HEAD` 通过。

### 独立验证（round 4）

| 检查 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **987 passed in 295.36s** |
| `.venv/bin/python scripts/landing_verify.py` | **RESULT: PASS**；v0.5 240/0 failing；v1.0 20/0 failing |
| `sha256sum data/splits/v1.0-gold.json` | `39dc756c7c8ab7986f02e324b7e9e8f7099fcc68aa5b3c07870bf374a8a2c6ac`（不变） |

### 终局意见

**APPROVE-WITH-NOTES（ticket 01 结案）。** 原 ticket 的 query-traceable gram 食物绑定、evaluate 收紧与 fail-closed 主路径均已满足；round 1–3 的阻断全部关闭。将“同一 span 多 food identity 仍可双授权”和“round 4 evaluate 测试 helper 未走 validate_draft”记录为主 agent 直接裁决/合入前可修事项，不再要求另开复审轮。
