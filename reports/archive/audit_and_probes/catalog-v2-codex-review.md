# round 2 — catalog-v2 Codex 复审报告

## 结论：REJECT

上一轮的 patty 多收和 quantity 吞未知前置词均已正确修复；beverage 的 `steak`/`kale` 子串反例也已修复。但新的 compound-suffix 实现会把真实 FNDDS 食物 `Candy, lollipop` 当作饮料，使 `a glass of lollipop` 错误解析为 10g，仍然破坏 fail-closed。因此本轮不能批准重建 catalog-v2。

复审只写本报告；未修改源码、catalog、data 或仓库内 dry-run 报告。复现产物写入 `/tmp/catalog-v2-codex-round2-dryrun.md`。

## 逐项复核

### 1. patty 裸行规则：通过

- 两处均使用 `^1\s+patty(?:,\s*nfs)?$`，匹配清理后的 `desc`，不再使用包含 modifier 的 `blob`。
- 扫描 `survey.zip` 全部 `food_portion.csv` 行：patty 命中 **43** 行，其中 `1 patty` 42 行、`1 patty, NFS` 1 行；非裸描述 **0**。
- `1 cake or patty`、`1 patty with sauce and cheese`、`1 patty shell`、`1 miniature patty` 均不再写 patty。

### 2. quantity 容忍：通过

独立合成 catalog 探针结果：

| 表达 | 结果 |
|---|---:|
| `two chicken wings` | 70g |
| `two toxic mystery cups` | `None` |
| `half random cup` | `None` |
| `half a cup` | 122g |
| `one and a half cups` | 366g |
| `cup of soup` | 186g |

`_leading_run` 与 `_span_crumbs_are_food_identity` 将单位前残余词限制为 food name、slug 或 alias 的 token；本轮要求的正反例均符合预期，未发现该修复引入的新回归。

### 3. beverage 修复：部分通过，存在新阻断

以下规定用例通过：

- `a glass of steak` → `None`
- `a glass of kale` → `None`
- `a glass of milkshake` → 299g
- `a glass of soymilk` → 244g
- `a bottle of root beer` → 372g

但 `_BEVERAGE_COMPOUND_SUFFIXES` 对每个名称 token 使用无条件 `endswith`。这只是把“任意子串”误判改成了“任意后缀”误判：

- `lollipop.endswith("pop")`
- `swine.endswith("wine")`
- `dishwater.endswith("water")`

其中 `lollipop` 不是纯合成反例：现有 catalog-v2 中真实存在 FNDDS `2710361 Candy, lollipop`，portions 为 `piece=10, qns=10`；实测 `a glass of lollipop` → **10g**。这违反 Resolver fail-closed，属于新高严重度阻断。compound 支持应限定为明确允许的形式（至少 milkshake、soymilk、buttermilk），不能用通用 suffix 集合判断所有名称。

### 4. builder / dry-run parity：通过

- 对 `food_portion.csv` 每一原始行逐项调用两套 key 函数，结果不一致数为 **0**。
- 完整 dry-run：builder 与独立 raw scan 均为 5395 个有份量食物，`portion_map_diffs == 0`。
- 修复后的 delta 为：仅新增 key 的食物 **462**、新增 key-food 对 **487**（其中 patty=43）、移除 0、同 key 克数变化 0。

仓库当前 `reports/catalog-v2-dryrun.md` 仍写 472/497、patty=53，是上一轮规则生成的旧结果。catalog 重建进入下一次裁决前，必须用修复后的规则重新生成该正式报告。

### 5. 测试：规定排除项之外全绿

- `tests/test_portions.py tests/test_gram_anchor.py tests/test_catalog_v2_fndds_only.py`：**121 passed**。
- `tests/test_agent_behavior_verify.py -k 'not test_handbook_matches_resolve_portion_on_catalog_v2'`：**9 passed, 1 deselected**。
- 相关测试合计：**130 passed, 1 个规定的重建产物依赖测试被排除**。

该排除项仍须在 Claude 裁决允许重建后，用新 catalog-v2 运行并全绿，才能作为落地完成证据。

## Standards

1. **高｜硬违规**：`_BEVERAGE_COMPOUND_SUFFIXES` 将真实 `Candy, lollipop` 误判为饮料，违反 `docs/llm-generated-exam-data.md` 的 Resolver“任一失败即拒”纪律。
2. **低｜判断项（Duplicated Code）**：beverage 词汇同时存在于未使用的 `_BEVERAGE_NAME_WORDS`、正则和 suffix 集合，规则易漂移；两套 catalog key 规则的重复则是独立 parity 验证所需，可接受。

## Spec

1. **高｜实现不完整并引入新问题**：round 2 要求检查 beverage 修复及是否引入新问题；规定例虽逐一通过，但修复产生真实 lollipop 假阳性。
2. **高｜审批证据错误**：正式 dry-run 报告仍保留已排除的 10 个 patty，数字应由 472/497/patty=53 更新为 462/487/patty=43。
3. **中｜范围蔓延**：本轮修复之外还把裸 cut noun 放宽，使 `a chicken breast` 从 `None` 改为 105g；round-2 规格没有给出该语义变化的依据，应单独确认其来源和门禁。

汇总：Standards 轴 1 个硬违规、1 个判断项，最严重为真实 lollipop 的 fail-closed 失败；Spec 轴 3 个问题，最严重为 beverage 新误判与正式 dry-run 证据陈旧。

## Round 3 快审

### 结论：REJECT

A/B 的指定检查全部通过，但 beverage 判断仍在真实 catalog 中产生新的非饮料假阳性，违反 fail-closed，因此不能 APPROVE。

### A. parity 与测试

- 扫描 `survey.zip` 的 22,046 条 portion 原始行，逐行比较 builder 与 dry-run：**0 mismatch**。
- `tests/test_portions.py tests/test_gram_anchor.py tests/test_catalog_v2_fndds_only.py`：**121 passed**。
- `tests/test_agent_behavior_verify.py -k 'not test_handbook_matches_resolve_portion_on_catalog_v2'`：**9 passed, 1 deselected**。
- 正式 dry-run 报告已更新为：仅新增 key 的食物 462、新增 key-food 对 487（patty=43）、移除 0、同 key 克数变化 0。

### B. 指定反例

- 真实 catalog `2710361 Candy, lollipop`：`a glass of lollipop` → `None`。
- 合成白米饭 catalog：`two toxic mystery cups` → `None`。
- 合成鸡翅 catalog：`two chicken wings` → 70g。

### C. 残留阻断

`_BEVERAGE_COMPOUND_WORDS` 的显式复合白名单修复了 lollipop 后缀问题；但 `_BEVERAGE_WORD_PAT` 仍在整段 food name/alias 的任意位置匹配饮料整词。食物名称“包含饮料词”不等于该食物本身是饮料。真实 catalog 独立探针得到：

| FDC id | 食物 | 表达 | 错误结果 |
|---|---|---|---:|
| `2707677` | Coffee cake, yeast type | `a glass of coffee cake, yeast type` | 57g |
| `2707192` | Egg casserole with bread, cheese, milk and meat | `a glass of ...` | 82g |
| `2709152` | Soup, ramen noodles, water added | `a glass of ...` | 245g |
| `2707852` | Bread, Irish soda | `a glass of ...` | 74g |
| `2709753` | Cocktail sauce | `a glass of cocktail sauce` | 34g |

这些表达均应拒绝。beverage 判定需要识别食物的主类型，而不能只判断完整名称中是否出现 `coffee`、`milk`、`water`、`soda`、`cocktail` 等词。

#### Standards

1. **高｜硬违规**：上述真实非饮料被容器单位解析，违反 Resolver fail-closed 纪律。
2. **低｜判断项（Duplicated Code）**：未使用的 `_BEVERAGE_NAME_WORDS` 与 `_BEVERAGE_WORD_PAT` 重复维护词表，存在漂移风险，但不是本轮阻断。

#### Spec

1. **高｜新阻断**：虽然 A/B 明列样例全部通过，但 round 3 要求“无新问题”才 APPROVE；真实 catalog 的多类假阳性不满足该条件。

Round 3 汇总：Standards 轴 1 个硬违规、1 个判断项；Spec 轴 1 个高严重度问题。最严重问题均为 beverage 类型判断仍非 fail-closed。

## Round 4 终审

### 结论：REJECT-WITH-REMAINING-BLOCKER

新的“饮料词 + `fl_oz`”双条件消除了 round 3 点名的假阳性，并保留了真饮料与 quantity/patty 行为；但全 catalog 扫描发现 3 个明确的固体冷冻甜品仍被判为饮料。`fl_oz` 只能证明 FNDDS 提供体积折算，不能证明食物可用 glass/bottle 表达，因此仍有一个直接的 fail-closed 阻断。

### 1. 全 catalog beverage 扫描

`_is_beverage_name` 在现有 catalog-v2 的 5431 个食物中判定 **512** 个为饮料。绝大多数为 milk、juice、coffee、tea、soft drink、beer、wine、water 等液体；但以下三项是明确固体：

| FDC id | 食物 | portions | 错误解析 |
|---|---|---|---:|
| `2709312` | Frozen fruit juice bar | `fl_oz=30, qns=80` | `a glass of ...` → 80g |
| `2709313` | Frozen fruit juice bar, no sugar added | `fl_oz=30, qns=80` | `a bottle of ...` → 80g |
| `2710322` | Freezer pop | `fl_oz=30, qns=50` | `a glass of ...` → 50g |

这不是可接受边界，而是缺陷：对象的 food form 明确是 bar/pop；FNDDS 的 `1 fl oz = 30g` 行只表示冰棒可以做体积换算。当前 container unit 最终还取 `_serving_default` 的 qns，而不是按 `fl_oz` 计算，更不能据此推导“一杯/一瓶冰棒”。这些表达应 fail-closed。

### 2. 三轮点名反例：通过

以下食物均为 `_is_beverage_name=False`，对应 `a glass of ...` 返回 `None`：

- Coffee cake, yeast type (`2707677`)
- Bread, Irish soda (`2707852`)
- Cocktail sauce (`2709753`)
- Candy, lollipop (`2710361`)
- Steak / Kale
- Shrimp cocktail (`2706449`)
- Fruit cocktail
- Nutrition bar (Tiger's Milk) (`2708125`)

### 3. 真饮料：通过

| 表达 | 结果 |
|---|---:|
| `a glass of milk` | 244g |
| `a bottle of root beer` | 372g |
| `a glass of milkshake` | 280g |
| `a glass of soymilk` | 244g |

### 4. quantity、patty 与 parity：通过

- `two toxic mystery cups` → `None`。
- `survey.zip` 共 22,046 条 portion 行；patty 命中 43 条，均为裸 `1 patty` 或 `1 patty, NFS`，非裸 0。
- builder 与 dry-run 逐行 parity：**0 mismatch**。

### 5. 测试：通过规定门禁

- `tests/test_portions.py tests/test_gram_anchor.py tests/test_catalog_v2_fndds_only.py`：**121 passed**。
- `tests/test_agent_behavior_verify.py -k 'not test_handbook_matches_resolve_portion_on_catalog_v2'`：**9 passed, 1 deselected**。

依赖重建后 catalog 的 handbook 测试仍按任务要求排除，须在获准重建后全绿。

### Standards

1. **高｜硬违规**：固体 frozen juice bar/freezer pop 被 glass/bottle 解析，违反 Resolver fail-closed 纪律。
2. **低｜判断项（Primitive Obsession / Mysterious Name）**：`_is_beverage_name` 表达的是饮料类型判断，实际依赖名称关键词与原始 portion key 的启发式组合；`fl_oz` 的领域含义不足以单独承担“可饮用”类型证据。

### Spec

1. **高｜剩余阻断**：任务要求判断 Frozen fruit juice bar 是可接受边界还是缺陷；终审认定为缺陷，并确认同类 `Freezer pop` 也受影响。

Round 4 汇总：Standards 轴 1 个硬违规、1 个判断项；Spec 轴 1 个高严重度剩余阻断。最终结论为 **REJECT-WITH-REMAINING-BLOCKER**。

## Round 5 终审

### 结论：REJECT-WITH-REMAINING-BLOCKER

“head 最后 token + `fl_oz`”已解决 round 4 的 frozen juice bar/freezer pop 固体假阳性，正向命中集也未发现明确固体误判；但规格声称的“真饮料 0 遗漏”不成立。反向扫描发现 **194** 个带 `fl_oz` 却被 `_is_beverage_name` 拒绝的食物，其中大量是无争议的真饮料。该规则从过宽变成过窄，仍不能进入 Claude 裁决。

### 1. 全 catalog 双向扫描

- catalog 食物数：5431。
- `_is_beverage_name=True`：**437**；复核未发现明确固体假阳性。
- `portions.fl_oz` 存在但 `_is_beverage_name=False`：**194**。

194 项并非都应判饮料，其中包含 frozen dessert、cream 等应拒绝项；但也包含大量明确真饮料。代表性漏判如下：

| FDC id | 食物 | head 最后 token | 结果 |
|---|---|---|---|
| `2705394` | Kefir | `kefir` | `a glass of kefir` → `None` |
| `2705507` | Milk shake with malt | `malt` | `a glass of ...` → `None` |
| `2709194` | Fruit juice blend, citrus, 100% juice | `blend` | `a glass of ...` → `None` |
| `2709341` | Apricot nectar | `nectar` | `a glass of ...` → `None` |
| `2710470` | Coffee and chicory, brewed | `chicory` | `a glass of ...` → `None` |
| `2710486` | Coffee substitute | `substitute` | `a glass of ...` → `None` |
| `2710574` | Pina Colada, nonalcoholic | `colada` | `a glass of ...` → `None` |
| `2710628` | Bloody Mary | `mary` | `a glass of ...` → `None` |
| `2710694` | Wine cooler | `cooler` | `a glass of ...` → `None` |
| `2710697` | Wine spritzer | `spritzer` | `a glass of ...` → `None` |
| `2710699` | Brandy | `brandy` | `a glass of ...` → `None` |
| `2710746` | Energy drink (Full Throttle) | `throttle` | `a bottle of ...` → `None` |
| `2710769` | Sports drink (Gatorade G) | `g` | `a bottle of ...` → `None` |

此外，Kefir、infant/toddler formula、nectar 系列、Horchata/Atole、多数具名鸡尾酒和烈酒均有同类漏判。根因是 FNDDS 的真实饮料名称并不总以通用饮料头名词结尾；品牌括号、配料结构和专有饮料名都会使最后 token 白名单失效。

### 2. Round 4 固体阻断：通过

- `2709312` Frozen fruit juice bar → `None`。
- `2709313` Frozen fruit juice bar, no sugar added → `None`。
- `2710322` Freezer pop → `None`。

`tests/test_portions.py::test_beverage_name_is_word_boundary_not_substring` 已覆盖 juice bar/freezer pop，并通过。

### 3. 代码实现复核

实现确实按规格描述执行：取 food name 第一个逗号前的 head，分词后仅检查最后 token 是否属于 `_BEVERAGE_HEAD_WORDS` / `_BEVERAGE_COMPOUND_WORDS`，随后要求 `fl_oz` 存在。问题不是代码偏离方案，而是方案本身无法覆盖真实 catalog 的饮料命名形态。

另有一个非阻断的小问题：`_BEVERAGE_HEAD_WORDS` 中的字符串 `root beer` 不可能等于单个 `last` token；实际 root beer 因 head 为 `Soft drink` 或最后 token `beer` 才能命中。

### 4. 测试

- `tests/test_portions.py tests/test_gram_anchor.py tests/test_catalog_v2_fndds_only.py`：**121 passed**。
- `tests/test_agent_behavior_verify.py -k 'not test_handbook_matches_resolve_portion_on_catalog_v2'`：**9 passed, 1 deselected**。

现有测试证明固体反例已修复，但没有覆盖上述反向真饮料遗漏，因此全绿不足以支持 APPROVE。

### Standards

1. **高｜判断项（Primitive Obsession）**：用最后一个字符串 token 的白名单承担 beverage 领域分类，真实数据中的大量假阴性已证明该表示过于脆弱。
2. **低｜判断项（Mysterious Name）**：`_BEVERAGE_HEAD_WORDS` 看似支持 head 词/短语，实际只与单 token 比较；其中 `root beer` 是不可达成员。

未发现新的 fail-open 固体误判；本轮安全方向是保守拒绝，Standards 轴没有新的硬违规。

### Spec

1. **高｜剩余阻断**：规格明确要求全 catalog “真饮料遗漏 0”，但反向扫描确认 194 个 `fl_oz` 未命中项中存在大量明确真饮料，要求未满足。

Round 5 汇总：Standards 轴 0 个硬违规、2 个判断项；Spec 轴 1 个高严重度剩余阻断。最终结论为 **REJECT-WITH-REMAINING-BLOCKER**。
