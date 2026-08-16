# FNDDS 份量完整接入审查意见

审查对象：`scripts/build_fdc_catalog.py` 的 `_portion_key`、`_merge_portion`、
`_collect_portions`；影响基线为 `data/splits/v0.5-gold.json`（240 条）。结论是：
**可以扩充份量键，但不能直接重建并覆盖 catalog。必须先产出 dry-run diff，证明冻结
split 的现有表达零漂移，再单独招收使用新表达的新题。** 判分规则
`Pass ⇔ end state == Oracle` 不应为迁就 catalog 漂移而放宽。

## 1. 当前实际保留与过滤的条目

当前 `_portion_key` 只会产出六个键：`cup`、`tbsp`、`tsp`、`slice`、
`piece`、`can`。其中 `each`，以及包含 `banana`、`egg`、`medium`、`large`、
`small` 的描述也会被折叠为 `piece`。

以下条目会被过滤或丢失语义：

| 类型 | 当前行为 | 风险 |
|---|---|---|
| 空描述 | 返回 `None` | 无法入表 |
| QNS（`Quantity not specified`） | 因 `startswith("quantity not")` 被显式丢弃 | 官方默认份量不可用 |
| 含 `guideline` | 返回 `None` | 指南类条目全部丢弃 |
| 含 `mashed` | 返回 `None` | 即使同时有 cup 也丢弃 |
| 同时含 `sliced` 和 `cup` | 返回 `None` | sliced-cup 与普通 cup 无法区分 |
| `thick` / `thin` / `regular` | 若没有六种已识别单位则返回 `None` | 牛排等尺寸档位丢失 |
| `oz` / `ounce` / `oz, yields` | 没有匹配规则，返回 `None` | FNDDS edible-yield 行丢失；不可与固定 28.35 g/oz 混为一谈 |
| `cubic inch` | 没有匹配规则，返回 `None` | 体积档位丢失 |
| 其他未列入 `_UNIT_PATTERNS` 的描述 | 返回 `None` | 新或食品特有的份量档位静默消失 |
| 非数字 gram weight | `_collect_portions` 跳过 | 合理，但无诊断输出 |
| `grams <= 0` | `_merge_portion` 跳过 | 合理，但无诊断输出 |

这里需要区分“过滤”和“错误折叠”：如果 `thick`、`thin`、`regular` 等描述中还
含有 `slice` 或 `piece`，该行不会被过滤，而会丢掉修饰词并合并到通用
`slice`/`piece`。这比显式丢弃更危险，因为 catalog 看起来仍有一个合法键，却未保留
原始档位的含义。

## 2. first-wins 与复合描述风险

`_collect_portions` 按 CSV 迭代顺序处理；`_merge_portion` 在键已存在时直接返回。因此
同一食物的多个描述只要被折叠为同一个键，**CSV 中先出现的行获胜**。代码没有按
modifier、描述精确度或 USDA 默认语义排序，也没有记录被丢弃的候选。结果虽对同一份
archive 可重复，却不具备跨 FNDDS 版本、导出顺序或映射规则变更的语义稳定性。

`"1 piece/slice, any size"` 是典型歧义。当前 pattern 顺序先检查 `slice`，所以该描述
被存为 `slice`；这不是 USDA 对 `slice` 优先于 `piece` 的声明，只是正则顺序造成的。
把它改存为 `piece` 会改变现有 `piece` 解析，把同一个克数同时复制到两个键又会制造
并不存在的等价关系。建议保留为独立键并记录原始 description/modifier；若产品必须把
用户的 `piece` 或 `slice` 映射到它，应另写、测试并审查明确的消歧政策。

## 3. 对 v0.5 gold 240 条的潜在影响

静态扫描冻结 split 得到恰好 25 个 food_id。Oracle 中有 81 条题、136 个 item 的克数
恰好落在当前 portions 档位的 0.5/1/1.5/2 倍或固定 2 oz 上，共涉及 21 种食物。
因此 catalog 重建不是“只增加展示字段”：只要旧键的 winner 或默认份量改变，这些题的
query 所表达的克数就可能不再等于冻结 Oracle。

### 直接暴露于份量漂移的 21 种食物

| 食物 | gold 当前使用的表意档位 | 主要风险 |
|---|---|---|
| `almond` | half cup、2 oz | cup winner；2 oz 仍是固定换算，不应改走 `oz_yield` |
| `apple` | piece、slice | size/`piece`/`slice` 复合描述碰撞 |
| `avocado` | half/one cup、slice | cup 与 sliced-cup、slice 档位碰撞 |
| `banana` | piece | 裸菜名与 piece/QNS 默认值的选择；当前 QNS 与 piece 同为 126 g 只是已知巧合 |
| `black_beans` | cup | cup winner |
| `broccoli` | cup | cup 形态；当前另有 10 g `piece`，错误回退会放大风险 |
| `cheddar` | slice | 厚薄/尺寸 slice winner |
| `egg` | two pieces | size 与烹调形态；piece/QNS 不能默认视作相同 |
| `greek_yogurt` | half/one cup | cup winner |
| `milk_whole` | half/one cup | cup winner |
| `oats` | cup、2 oz | cup winner；2 oz 必须保持固定 56.7 g |
| `olive_oil` | tbsp、tsp | spoon 档位 winner |
| `orange` | cup、slice | cup 形态与 slice winner |
| `pasta` | cup | cooked/形态 cup winner |
| `peanut_butter` | tbsp | tbsp winner |
| `potato` | piece | “a baked potato”依赖默认/裸菜名语义，QNS 接管后可能漂移 |
| `soy_milk` | half/one cup | cup winner |
| `spinach` | cup | raw/packed/chopped 等 cup 形态碰撞 |
| `tofu` | cup | cubed/mashed 等 cup 形态碰撞 |
| `tuna` | can | can 大小与 drained/yield 语义碰撞 |
| `white_rice` | half/one/1.5 cups | cup winner；出现频率最高，漂移波及面最大 |

其中 `apple`、`avocado`、`banana`、`broccoli`、`cheddar`、`egg`、`orange`、
`potato` 当前使用 `piece`/`slice` 或裸菜名，最容易受 thick/thin/regular/size 与复合
描述折叠影响。`white_rice`、`oats`、`banana`、`spinach` 使用次数也高，哪怕只有一个
基础键改变也会同时影响多条冻结题。

### 当前 gold 只用显式克数的 4 种食物

`beef`、`chicken_breast`、`salmon`、`shrimp` 在当前冻结 query/Oracle 中只使用显式
克数，单纯增加 portions 键不会改变这些题的克数。它们仍需留在 dry-run 清单中：重建若
同时改变 staple alias 指向、FDC 行或 nutrients，evaluate windows 和食物解析仍可能漂移；
未来一旦使用 `serving`、`thick` 等表达，就会立即进入高风险组。

### “只加新键”何时才是零漂移

只有同时满足以下条件，现有 240 条才能视为克数零漂移：

1. 现有六个键及其 gram value 完全不变；
2. 当前固定 ounce 语义继续使用 `OUNCE_GRAMS = 28.35`，不被 `oz_yield` 覆盖；
3. `serving`、裸 dish noun、裸食物名的回退行为对现有 query 不变，或逐题证明新 QNS
   与旧结果相同；
4. 25 个 staple alias 的目标 FDC id、nutrients 和 allergen tags 不变；
5. 用冻结 split 重解析所有可解析表达，与已烤入 Oracle 做逐 item diff，结果为空。

任何一项不满足，都应生成“task id / food_id / query / old grams / new grams / source row”
清单交 GPT 审查和主 agent 裁决，而不是覆盖 catalog 或重写旧 Oracle。

## 4. 接入建议

### 4.1 新键命名与数据保真

保留现有稳定键：`cup`、`tbsp`、`tsp`、`slice`、`piece`、`can`。新增键建议采用
小写 snake_case，并保持语义互斥：

- `qns`：仅对应 Quantity not specified；不得伪装成 `piece` 或 `slice`；
- `thick`、`thin`、`regular`：食品自身的尺寸档位；
- `oz_yield`：FNDDS “oz, yields” 条目，明确区别于物理 ounce 的 28.35 g；
- `cubic_inch`：体积档位；
- `piece_or_slice_any_size`：保留复合描述，不靠正则优先级偷偷选择一边。

若同一语义仍有多个候选，不能继续静默 first-wins。至少应在 dry-run 中列出冲突；更稳妥
的是同时保存原始 `portion_description`、`modifier`（包括 modifier code）与 gram weight，
再由显式优先级选出对外键。优先级必须按语义制定并有 fixture 测试，不能依赖 CSV 顺序。

### 4.2 与 `resolve_portion` 的同步

每一个允许进入 query 的新表达，都必须与
`src/nutrienv/world/portions.py::UNIT_SYNONYMS` 或等价的复合短语解析规则同步，并补
phrase→key→grams 测试。仅把键写进 catalog 不会让 resolver 自动理解它。

- `thick/thin/regular` 需要明确解析类似 `a thick steak` 的修饰词，而不是继续先命中
  `slice`/`piece`；
- `serving`/`portion`/dish noun 若改用 `qns`，应显式读取 `qns`，并逐题验证旧回退
  `piece → slice → cup` 的差异；
- `oz_yield` 不应加入普通 `oz` 同义词。普通 `oz` 当前是固定质量单位；只有明确表达
  edible yield 的短语才能选 `oz_yield`；
- `piece_or_slice_any_size` 不应同时成为 `piece` 与 `slice` 的无条件同义词。

catalog schema、resolver grammar 和造题 phrase 三者必须在同一个变更中有对称测试；否则
LLM query 即使自然，Oracle 仍可能无法确定性反解。

### 4.3 与 ReAct agent 手册的同步

`src/nutrienv/harness/react.py::_SYSTEM_V1_TAIL` 当前只告诉 agent 使用 cup、tbsp、tsp、
slice、piece，连现有 `can`、固定 `oz`、serving/dish-noun 回退都没有完整说明。新表达进题
之前必须先同步手册，使 agent 能仅凭 observation 和规则复现 Oracle：

- 列出对 agent 可见的所有新 portions 键及含义；
- 说明 `a thick/thin/regular X` 选择哪个键；
- 说明 `a serving/portion/order` 以及裸 dish noun 是否选择 `qns`；
- 明确普通 ounce 固定按 28.35 g，而 `oz_yield` 不是它的替代品；
- 对 `piece_or_slice_any_size` 给出明确的询问澄清或选择政策。

手册更新、`UNIT_SYNONYMS`/复合解析更新和新 realization/query 应视作不可拆分的原子变更。
在这三者对称之前，不应招收任何使用新表达的 LLM 候选题。

## 5. 建议 gate

1. 对新 catalog 做不落盘 dry-run，输出 25 种 gold 食物的 alias、旧/新 portions、QNS、
   nutrients diff；
2. 对 240 条冻结题重放可解析 phrase，要求 `old Oracle grams == new resolved grams`；
3. 单独报告 first-wins 冲突及被过滤行，不允许静默覆盖；
4. 用独立 `validate_oracle_grams(task)` 检查候选 Oracle 的每个 ledger/plan item；
5. 只有冻结 split 零漂移、resolver 与手册对称、灰区 judge 用例通过后，才允许新键进入
   下一版题目。
