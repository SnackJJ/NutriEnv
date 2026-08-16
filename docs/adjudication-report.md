# 第一阶段收尾裁决报告

> 裁决人：claude（5 小时限量，单次终审）
> 裁决对象：`reports/dry-run-summary.md` + `reports/dry-run-drift.json` + `scripts/fndds_dry_run.py`；
> `reports/qns-gap-audit.json` + `scripts/qns_gap_audit.py`；`docs/review-fndds-ingestion.md` +
> `src/nutrienv/bench/validator.py` 的 `validate_oracle_grams()`；`docs/llm-generated-exam-data.md` 最新版。
> 方法：只读三份产出 + 项目方案文档，用 `.venv/bin/python` 独立复算数字、直接读 `survey.zip`/`catalog.sqlite`
> 原始数据核对因果链、跑现有测试套件确认基线，未修改任何代码/数据/catalog。

## 结论先行

**允许进入"落地实施"**（按安全叠加改 `build_fdc_catalog.py` 并重建 catalog，再跑 validate + split
测试验证零漂移），但必须先合入本报告发现的 **三处新实现陷阱**（见第 2、4 节），并满足第 4 节验收清单。
这三处陷阱不影响"当前 25 种 gold 食物零漂移"这一具体结论（已逐一核实不受影响），但会让落地后的
`build_fdc_catalog.py` 比 dry-run 报告承诺的范围更激进，或重新引入 review 文档已经点名警告过的风险。

---

## 1. 终审三份产出

### 1.1 dry-run（FNDDS 完整接入）

**复跑验证**：`.venv/bin/python scripts/fndds_dry_run.py` 重新生成的 `dry-run-drift.json`
与 `dry-run-summary.md` 和仓库里已落盘的版本逐字节相同（`diff -q` 无输出）——脚本是纯函数、无隐藏状态，
"复跑"这条自我声明成立。

**关键统计独立复算**（直接读 JSON，不依赖 summary 里的转述）：

| 声明 | JSON 实际值 | 核实 |
|---|---|---|
| 对比食物数 5395 | `stats.foods_compared = 5395` | ✅ |
| 旧键被改/被删 861 | `stats.foods_old_key_changed_or_removed = 861` | ✅ |
| 仅新增键 4533 | `stats.foods_only_new_keys_added = 4533` | ✅ |
| 完全零漂移 1 | `stats.foods_zero_drift = 1` | ✅ |
| gold 14 条克数会变 | `gold.item_drifts` 长度 = 14 | ✅ |
| gold 2 种旧键会变 | `gold.foods_with_old_key_changes` 长度 = 2（apple、cheddar）| ✅ |
| 安全叠加下 gold 漂移 0 | `gold.safe_overlay_item_drifts` 长度 = 0，`safe_overlay_old_key_zero_drift = True` | ✅ |

**根因独立复核**（不信任报告转述，直接读 `survey.zip` 原始 `food_portion.csv`）：

- Beef steak NFS（fdc `2705824`）：实测 **恰好 8 行**——`regular=160`(QNS 同值)、`thick=240`、
  `thin=120`、`cup=135`、复合 `1 piece/slice, any size=30`、`oz yields=20`、`cubic inch=17`。
  与 `docs/llm-generated-exam-data.md` 关键发现 1 的修正版逐字吻合，"16 行是初稿误数"的说法可信。
- Apple（`2709215`）：seq 1 是 `1 small`=165g，seq 2 是 `1 medium`=200g；当前 builder 走 zip 行序、
  取到 200g；dry-run 按 seq_num 排序后 165g 赢——与 apple `piece 200→165` 的漂移说法完全对应。
- Cheddar（`2705709`）：seq 1 是 `1 cracker-size slice`=9g，seq 2 是 `1 slice`=21g；同理复现
  `slice 21→9` 的漂移。且 cheddar **没有任何复合 piece/slice 行**，也没有 piece 键——排除了"漂移是
  复合双写造成"的误读，纯粹是 first-wins 排序基准从 zip 序换成 seq_num 序导致。

**结论**：dry-run 的统计数字和因果链叙述真实、可复现、与原始数据吻合，没有夸大或漏报。

### 1.2 QNS 差距审计

- `total_catalog_foods=13224` 与 catalog 实测 `sr_legacy_food(7793) + survey_fndds_food(5431) = 13224`
  精确相等 ✅。
- `gold_foods_in_survey_with_qns=16` 与 dry-run 报告独立声称的"gold 25 种里来自 FNDDS 的 16，全部有
  QNS"**交叉一致**——两份产出用不同脚本、不同方法（一个走 sqlite+`resolve_portion`，一个走
  `collect_full_fndds` 自建索引）算出同一个数字，是有效的相互印证，不是同一处代码抄了两遍。
- `is_sr = len(fid) == 6 or fid.startswith("17") or fid.startswith("16")` 这行启发式没有直接读
  `data_type` 字段，看起来脆弱。**实测验证**：当前 catalog 里 `survey_fndds_food` 恒为 7 位、前缀
  `27`；`sr_legacy_food` 恒为 6 位、前缀 `16`/`17`，无一例外——启发式在当前数据上 100% 准确，
  **不是缺陷**，只是不必要的重新发明；建议以后直接查 `data_type`，更稳健、不依赖 id 形状假设长期成立。
- 抽样核对 `current_serving` 公式（cheddar→slice 21、avocado→slice 15、potato→piece 230）与
  `resolve_portion` 的 `_serving_default`（piece→slice→cup）逐一吻合，方法论正确。
- 汇总数字里的极端案例（cereal 0.1g、watermelon 6000g）不是审计脚本的 bug，而是当前 catalog 已有的
  退化数据——恰恰印证了主文档"serving 回退改用 QNS"这条建议的必要性，属于审计要找的东西，不是审计本身的问题。

**结论**：差距审计的量化可信，方法论正确，与 dry-run 报告的重叠数字互相印证一致。

### 1.3 FNDDS 接入审查意见

- 逐条核对现状描述与实际代码（`scripts/build_fdc_catalog.py` 当前只有 6 个 `_UNIT_PATTERNS`、
  `slice` 排在 `piece` 前面、`quantity not`/`guideline`/`mashed`/`sliced+cup` 确实被丢弃）——**完全属实**。
- `resolve_portion`/`UNIT_SYNONYMS` 现状核对：确认 `UNIT_SYNONYMS` 里没有 `qns`、`thick`、`thin`、
  `regular`、`oz_yield`、`cubic_inch` 的词条；`OUNCE_UNITS`（`oz`/`ounce`/`ounces`）在
  `resolve_portion` 里走的是固定 `28.35 g` 路径，**在 `UNIT_SYNONYMS` 查表之前就已经分支返回**，
  和 catalog 的 `portions["oz"]` 完全无关——审查文档 4.2 节"仅把键写进 catalog 不会让 resolver
  自动理解它"的论断精确成立，甚至比字面描述更彻底：现在这条路径**根本不会读** catalog 的新 `oz` 键。
- `react.py` 手册核对：`grep` 结果只有一行提到量具，且只列 cup/tbsp/tsp/slice/piece 五种，
  连当前已存在的 `can` 键、固定 `oz` 换算、serving/dish-noun 回退都没写全——与审查文档 4.3 节的描述一致。
- 审查文档给出的"新键建议"（`oz_yield` 独立于 `oz`、复合行保留独立键而非双写）与主 agent 后续裁决的
  "复合双写 + 不覆盖旧键"之间存在**未被显式调和的张力**，见第 2.3 节。

**结论**：审查意见的关键结论全部核实为真，是三份产出里论证最严谨的一份；但它提出的部分建议
（`oz_yield` 独立键、复合行不双写）与最终裁决的执行细节没有完全对齐，需要在落地时收口（见第 2 节）。

---

## 2. 终审主 agent 裁决

### 2.1 "拒绝直接重建" —— 维持

seq_num + first-wins 会动 14 条冻结 gold 行，数字已在 1.1 节独立复核为真，此裁决**维持**，无异议。

### 2.2 "批准安全叠加策略" —— 维持，但零漂移的证明力度比报告暗示的更强也更弱

**更强的一面（结构性证明，不依赖 dry-run 报告的具体方法）**：`safe_proposed` 的合并规则是
`merged = dict(old); merged.setdefault(key, grams)`——这是纯字典操作，`setdefault` 对已存在的键
永远是 no-op。也就是说，只要一个键在 `old`（当前 catalog）里已经存在，安全叠加下它的值**在数学上
不可能改变**，与 dry-run 报告用来算"14 条漂移"的 `infer_key` 数值反推方法猜没猜对无关。这条保证比
报告字面呈现的"我们跑了一遍脚本，得到 0"更硬——它是构造性的。

**更弱的一面（gate 建议第 2 条尚未真正满足）**：dry-run 判定"哪条 gold 题的克数由哪个旧键撑起"用的是
`infer_key`——对每个冻结 grams 反查 `old` 表里 `factor × old_grams == grams`（`factor` 取
`0.25/1/3/0.5/0.75/1/1.5/2/3/4`）的最佳匹配，**不是**审查文档 gate 建议第 2 条要求的"重放
`realizations.py` 里真实的 phrase，要求 old Oracle grams == new resolved grams"。这是数值近似，
不是语义重放。已用 apple/cheddar 两个真实案例核实反推结果与原始数据吻合，但这只是经验验证，
没有把方法论缺口堵上——尤其是对于**不在** `EVALUATE_ROWS`/`UPDATE_ROWS` 里、query 对不上任何
手写 Row 的题（比如未来 LLM 候选题），数值反推法完全没有防护，而"老键 immutable"这条结构性保证依然
成立。落地前应该按 gate 建议第 2 条把"真重放"补上（第 4 节验收清单第 3 条）。

### 2.3 复合 `piece/slice` 双写 —— 语义上站得住，但与审查文档的表述有张力

审查文档 2 节明确反对双写（"把同一个克数同时复制到两个键又会制造并不存在的等价关系"），建议保留成
独立键 `piece_or_slice_any_size`。但实测 FNDDS 原始行本身就是 `"1 piece/slice, any size"`
——**这不是代码发明的等价关系，是 USDA 问卷设计本身对这一个 fdc_id 的这一行认定 piece 和 slice
可以互换措辞**，双写是忠实转录该行的语义，不是凭空捏造。用真实 steak 案例核实：当前 catalog 里
`2705824` 只有 `{slice: 30, cup: 135}`，落地后按"冻结旧键 + 补缺失一侧"会补上 `piece=30`
（与 slice 相同）——这个具体例子里双写没有产生虚假信息。**审查文档的顾虑在通用场景下仍然成立**
（如果某食物同时有一条独立 `"1 piece"`行和一条复合行，且两者克数不同，双写就可能制造混淆）——
但 dry-run 脚本的规则已经处理了这种情况（"各键仍独立 first-wins：若更早已有独立 `1 piece` 行，
piece 不被覆盖"），足以化解。**结论**：主 agent 的裁决可以维持，但审查文档提的顾虑没有被显式回应，
建议落地时在 commit message / ADR 里写一句"审查过 review-fndds-ingestion.md §2 的顾虑，双写限定为
`_merge_portion` 的 first-wins 语义之下、且只在 FNDDS 原行本身就是复合描述时触发"，做一个书面对齐，
不需要改代码逻辑。

### 2.4 新发现的实现陷阱（本次审查新增，dry-run/审查文档均未覆盖）

这三点是本次终审新发现的问题，不是对既有结论的推翻，而是"允许落地"的**前置条件**：

**陷阱 A：`safe_proposed` 的合并范围比"落地建议"文字描述的更宽**

`reports/dry-run-summary.md` 的落地建议原文是"旧键冻结、只追加新键：cup/tbsp/tsp/slice/piece/can
保持当前 catalog 值；**只插入当前没有的** thick/thin/regular/oz/fl_oz/cubic_inch/serving/qns"——
字面意思是旧键类目（不管当前有没有值）从不被新扫描填充，只有列出的 8 个新键类目可以被插入。

但 `fndds_dry_run.py` 里 `safe_proposed` 的实际代码：

```python
merged = dict(old)
for key, grams in new.items():
    merged.setdefault(key, grams)
```

对 `new`（即 `proposed[fdc_id]`，包含全部 14 种键，新旧不分）的**所有**键做 `setdefault`，
并没有把 `key` 限制在 `NEW_KEYS` 集合内。也就是说：如果某个 FNDDS 食物当前 catalog 里缺一个旧类目
键（比如只有 `cup`，没有 `piece`），而全量 FNDDS 扫描（非复合行）能解出这个 `piece` 值，安全叠加
**会**把它插进去——这不是复合双写那条窄例外通道，是对所有旧类目键的普遍放行。

已核实：**对当前 25 个 gold 食物，这个更宽的行为没有造成任何影响**（逐一检查
`gold.foods[*].added`，没有一个 gold 食物在非复合扫描下新增了旧类目键）。但它会影响其余
约 5370 个非 gold 的 FNDDS 食物，且这条放宽没有被写进任何文档、没有被审查过。

**要求**：落地实现 `build_fdc_catalog.py` 时必须明确二选一并写清楚：
- (a) 严格遵守文字描述——旧类目键只能被"冻结"或"复合双写补缺失一侧"两条路径写入，普通行永远不能
  新增缺失的旧类目键；
- (b) 有意放宽为"任何缺失的键（不分新旧类目）都可以被普通行填充，只有已存在的值不可覆盖"——如果选
  这条，需要在 `docs/llm-generated-exam-data.md` 或 ADR 里显式记录这个决定，并让 GPT 单独审查一遍
  它对非 gold 食物的影响面。

**陷阱 B：新键 `oz` 混合了两种语义不同的 FNDDS 行**

`_NEW_UNITS` 里的 `oz` 模式（`\boz\b(?!\s+(?:container|bag|bottle|package|cup)\b)`）会同时命中
`"1 oz, cooked"`（物理盎司，逐份称重）和 `"1 oz, yields"` / `"1 oz, raw (yield after cooking)"`
（熟后得率盎司，与生重的换算关系，数值上通常远小于 28.35g）——这正是审查文档 4.2 节明确警告的
"`oz_yield` 不应加入普通 `oz` 同义词"。实测 `survey.zip`：

```
2705856  1 oz, cooked=28.35            1 oz, raw (yield after cooking)=9.0
2705857  1 oz, raw (yield after cooking)=9.0    1 oz, cooked=28.35
2705859  1 oz, yield after cooking=27.0         1 oz, cooked=28.35
...（共 42 个食物存在此冲突，示例已列出前 8 个）
```

first-wins 会按 `seq_num` 任意决定这 42 个食物的 `oz` 键落在物理盎司还是得率盎司上——两者数值可以
差 3 倍以上。**当前 25 个 gold 食物都不在这 42 个之中**，且 `resolve_portion` 里 `oz` token 现在
走固定 `28.35g/oz`、根本不读 catalog 的 `oz` 键，所以这个键眼下是"死键"——**不影响本轮零漂移结论**。
但一旦以后按审查文档 4.2/4.3 节要求把 `oz` 接入 `UNIT_SYNONYMS`（这是"完整接入"计划里必然要做的
下一步），如果不先把两种语义拆开，会静默复现同样的混淆，且这次会真的被 resolver 读到、影响造题。

**要求**：落地时至少要么 (a) 把 `oz`/`oz_yield` 拆成两个键（如审查文档建议），要么 (b) 在
`_NEW_UNITS` 里显式排除 `yield` 相关描述、单独归类，不能让两者共用一个 `oz` 键。

**陷阱 C：`validate_oracle_grams` 已就绪但尚未接入任何实际 gate**

`validator.py` 新增的 `validate_oracle_grams(task)` 精确对应审查文档 gate 建议第 4 条，函数本身
写得对（复用已有的 `_matches_portion_table`，独立于 query↔Row 匹配，3 个单元测试全绿）。但
`grep -rn "validate_oracle_grams"` 全仓库结果显示，它**只在自己的测试文件里被调用**——
没有接入 `validate_draft`，没有接入 `materialize_split.py`，没有接入任何冻结新 split 前的检查路径。

**要求**：这是一把还没上膛的安全网。落地实施及后续 LLM 造题阶段开始前，必须把它接进实际会跑的 gate
（至少在 `materialize_split.py` 冻结新 split 之前调用一次），否则"独立校验 Oracle 克数"这条防线
名义上存在、实际上不生效。

---

## 3. 终审 `docs/llm-generated-exam-data.md` 最新版

- **banana 126g 修正**（"不是手写、也不是隐式 QNS"）：核对 `realizations.py:279` 一带的说法与文档
  描述一致，本次未发现新反例。
- **牛排 8 行修正**：已用 `survey.zip` 原始数据独立复核，**恰好 8 行**，字段值与文档表格逐一吻合
  （见 1.1 节）。
- **灰区用例三对**（sandwich 1.5×/lasagna 1.2×/omelet 2.0×）：文档里已正确保留为"judge 封 gate 前
  必须过"的前置条件，本次没有新证据要求修改这三个数字。
- **未发现新的事实错误**。第 7 节"建议执行顺序"里的第 1、2 步（完整 FNDDS 接入 dry-run、差距审计
  清单）现已完成，文档本身是前瞻性方案文档、不需要因为执行进度而改动——状态更新应该留在
  `docs/agent-orchestration.md` 或进度追踪文件里，不属于本次只读裁决的修改范围。
- 第 5 节"必须同步处理的三处隐患"的第 1 条（"validate_draft 反解检查只在 query 匹配到 Row 时生效…
  需抽成独立函数直接调用"）现状是**部分解决**：独立函数已经写出来了（`validate_oracle_grams`），
  但还没有被任何调用点使用（对应 2.4 节陷阱 C）。文档本身不需要改，但落地清单要把这条列进去。

---

## 4. 验收清单（进入"落地实施"前必须满足）

1. **旧键类目写入路径收口**：`build_fdc_catalog.py` 的安全叠加实现里，`cup/tbsp/tsp/slice/piece/can`
   六个旧类目键只能通过"冻结现有值"或"复合 piece/slice 双写补缺失一侧"两条路径获得新值；
   非复合行不得为当前缺失的旧类目键新增数值（对应第 2.4 节陷阱 A，除非显式决定放宽并留档）。
2. **`oz` / `oz_yield` 语义拆分**：新 `oz` 键（或等价机制）不得让"物理盎司"行和"熟后得率盎司"行
   first-wins 混淆；落地前重新跑一遍"哪些食物同时有这两类行"的专项检查，确认冲突食物已被正确拆分
   或排除（对应第 2.4 节陷阱 B，已知至少 42 个食物存在该冲突）。
3. **真实 phrase 重放，替代/补充数值反推**：对能在 `EVALUATE_ROWS`/`UPDATE_ROWS`/其他 Row 表按
   `query` 精确匹配到的冻结题，用旧 catalog 和候选新 catalog 各跑一遍
   `resolve_portion(food_id, phrase, catalog)`，要求逐条相等——落实审查文档 gate 建议第 2 条的
   字面要求，不止停留在 `infer_key` 数值近似（对应第 2.2 节）。
4. **`validate_oracle_grams` 接入实际 gate**：至少接入 `materialize_split.py` 冻结新 split 之前的
   检查路径（对应第 2.4 节陷阱 C）。
5. **`UNIT_SYNONYMS` / react.py 手册 / catalog schema 三者对称**：任何新键要进入 query 语法之前，
   必须同一个变更里补齐 `resolve_portion` 的解析规则和 `react.py` 手册说明，并补 phrase→key→grams
   测试（文档 4.3 节已有要求，本次核实现状完全空白，尚未开始）。
6. **落地后重新跑三项交叉检查**：
   - 240 条题目 `validate_draft(task) == []` 全绿；
   - 25 个 gold 食物 `old_key_zero_drift` 用第 3 条的真实 phrase 重放法重新确认为 True；
   - 全量测试套件（本次基线：210 passed, 0 failed）保持全绿。
7. **judge 灰区用例前置条件保留**：sandwich 1.5×/lasagna 1.2×/omelet 2.0× 三对灰区用例必须在
   judge 封 gate 前跑通，本次终审未发现理由取消这条（`docs/llm-generated-exam-data.md` 第 3 节已有要求，继续生效）。

---

## 附：本次终审做过的独立验证（可复现）

```
.venv/bin/python scripts/fndds_dry_run.py                 # 重跑，diff -q 与已提交文件字节相同
.venv/bin/python -c "..."                                  # 独立读 dry-run-drift.json 复算 stats/gold 数字
.venv/bin/python -c "..."                                  # 直接读 catalog.sqlite 验证 is_sr 启发式（13224=7793+5431）
.venv/bin/python -c "..."                                  # 直接读 survey.zip 验证 steak 8 行、apple/cheddar 排序根因
.venv/bin/python -c "..."                                  # 直接读 survey.zip 验证 42 个食物存在 oz/oz_yield 冲突
grep -rn validate_oracle_grams                              # 确认仅测试文件调用，未接入实际 gate
.venv/bin/python -m pytest -q                                # 210 passed, 0 failed（改动前后基线）
```
