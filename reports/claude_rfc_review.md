审查完毕。已通读 RFC 全文，并核对了 `src/nutrienv/world/catalog.py`、`scripts/build_fdc_catalog.py`、`scripts/build_v2_8_gold.py`、`src/nutrienv/bench/scorer.py`、`src/nutrienv/bench/split.py`、ADR 0025/0029、以及全部相关 split 与 catalog 的实际字节状态。

---

# RFC 审查报告：底层检索基础设施与出题链有机重组

## 0. 总评

方向对，包装不合格。四个核心判断（porter 词干、OR 降级、冰箱等价簇、250g 蛋糕击穿）**思路本身站得住**，但 RFC 以"第一性原则有机重组"自我定位，却存在三类硬伤：(1) 按字面执行会**炸掉整个已发布基准的 catalog 绑定**；(2) 绕开 `build_v2_8_gold.py` 直接手改冻结 split，违反 ADR 0020/0029；(3) 四项"基础设施重构"里有两项**代码里已经实现了**，说明 RFC 没有对照现状代码写。

---

## 审查点 1：第一性原则与系统架构

### F1（阻断级）— 原地重建 `catalog-v2.sqlite` 会击穿 6 个 split 的 sha 绑定

实测：

```
catalog-v2.sqlite sha256 = 57184b2b...c28b5f
v2.2-gold   → pins 57184b2b  MATCH   (且 EXAM_SPLIT_PATH 当前就指它)
v2.3-gold   → pins 57184b2b  MATCH
v2.5-gold   → pins 57184b2b  MATCH
v2.7-gold   → pins 57184b2b  MATCH   (ADR 0028 正式冻结, nutrienv-gold 前镜像)
v2.8-gold   → pins 57184b2b  MATCH
nutrienv-gold → pins 57184b2b  MATCH
```

`split.py:115-119` 的 `load_exam` 对 `catalog_sha256` **硬失败**。FTS5 把 `tokenize` 从 `unicode61` 改成 `porter unicode61`，会重写 `food_fts_data / food_fts_idx` 所有倒排 posting → 文件字节必变 → sha 必变 → **v2.2〜v2.7 四个已发布/冻结 split 的 `load_exam` 同时报错**。RFC 第三节"运行现有全部 pytest 确保 1408 全绿"这句站不住：`test_catalog_build_reproducible.py`、`test_split.py::test_v2_8_lite_gold_is_70...` 会直接红。

RFC 通篇未提这一点，这是"打补丁叠屎山"的反面——它不是叠屎山，是**把承重墙敲了**。

**唯一合规解**：新出 `data/fdc/catalog-v3.sqlite`，只让 v2.8-gold + nutrienv-gold（未冻结，见 F2）重新 pin 到 v3；`catalog-v2.sqlite` 与 v2.2〜v2.7 的绑定一个字节都不动。`split.py:67-70 / 106-120` 已支持按 split 内 `catalog` 字段逐个解析路径，所以不需要动 `catalog_store.GOLD_CATALOG_PATH` 默认值（`catalog_store.py:19` 仍留 v2，避免影响 legacy pipeline 与裸 `load_catalog()`）。

### F2（阻断级）— 直接手改 `v2.8-gold.json` / `nutrienv-gold.json`，绕开 freezer

RFC "文件涉及" 三处都写 `data/splits/*.json` 作为编辑目标。但：

- ADR 0029 里程碑 3-5 明确要求：新题由 `scripts/build_v2_8_gold.py` **公理化编译**，经 Round-Trip + freezer 落盘，镜像 `nutrienv-gold.json`。`tests/test_split.py:729` 还断言两者逐题镜像。
- AGENTS.md 硬纪律 7 / ADR 0020：**严禁手搓未推导的 Oracle**；候选必须 HITL 核准后由 freezer 编译。

所有改动必须落到 `build_v2_8_gold.py` 的对应构造点（我已定位）：

| 题 | 构造点 | 现状 |
|---|---|---|
| `adr25-eval-1201` | `_patch_1201()` `build_v2_8_gold.py:384-419`，`cake_g = _grams(catalog, CAKE, "a serving")` `:388` | 现走 `"a serving"→qns=175g` |
| `adr29-dish-02` | `_new_tasks` `:593-605`，`LedgerRow(EGG_BOILED, egg_piece, ...)` | `EGG_BOILED="2707154"` `:81` |
| `adr29-fridge-01/02/05`、`adr29-buy-02` | `_recommend_task` / `_buy_task` 的 `allowed=_inventory(...)` | 单 ID 元组 |

**利好**：这几个 split 是 `??` 未入 git（`git log --all -- data/splits/v2.8-gold.json` 为空），`EXAM_SPLIT_PATH` 仍指 v2.2。所以 v2.8-gold 目前是**未冻结的发行候选**，在首次提交前定稿是允许的——但必须走 builder + 重跑 ADR 0029 里程碑 4（70/70 Round-Trip 100% Pass）+ 重新镜像。RFC 必须把这句话写进去，并说明"v2.8 尚未冻结，这是冻结前定稿，不是改已冻结金标"。若 v2.8 已对外发过镜像，则全部改动改走 v2.9-gold。

### F3（重大）— 四项"基础设施重构"里两项代码已实现

- **点 2（连字符/斜杠空格化）= no-op**。`catalog.py:19` `_TOKEN = re.compile(r"[a-z0-9]+")`，`re.findall` 对 `"hard-boiled"` 已产出 `["hard","boiled"]`；FTS 的 `unicode61` 默认也把 `-` `/` 当分隔符。两侧都已经分好了。
- **点 4（Primary Item Promotion）≈ 已实现**。`catalog.py:208` `_prepend_unique(self._exact_alias_hits(terms), _promote_alias_hits(hits, terms), limit)` + `_exact_alias_hits` `:210` + `_promote_alias_hits` `:354`，做的正是"别名精确命中/别名含全部实词的单品提到 BM25 前"。`scripts/agent_behavior_verify.py:436` 有专门说明。

RFC 把已有行为当新工作提出，说明没对照 `catalog.py` 现状。这直接削弱"彻底、自洽的有机重组"的可信度——真实工作量是 **2 项新增（porter + OR fallback）+ 2 项已存在**。

---

## 审查点 2：SQLite FTS5 与 IR 设计

### F4（重大）— porter 过度词干化，5 个词的回归测试远远不够

实测 SQLite porter（`tokenize='porter unicode61'`）：

```
tomato/tomatoes  → 同 stem ✓     potato/potatoes → 同 stem ✓
egg/eggs         → 同 stem ✓     almond/almonds  → 同 stem ✓
breadstick(s)    → 同 stem ✓     berry/berries   → 同 stem ✓
```

复数确实解决了。但过度合并同样真实：

```
"organ"     命中 "organic", "organization"
"universal" ≡ "university"   (都 → univers)
"fri"       命中 "fries", "fried"     ("fry" 反而不命中)
```

FNDDS 描述里 `organ meats`（内脏）与 `organic`、`fried` 与 `fries` 的部分合并会引入噪声。porter 是**英语单语言、有损、索引+查询双侧生效**，改了就是全库 recall 特性变化。

RFC 第三节只对 `boiled eggs / hard-boiled egg / breadstick / low-fat milk / egg` 5 个 cherry-pick 词做单测——**这测的是"想让它过的用例"，不是"它会误伤什么"**。要求：建一张**基于 catalog-v2 真实词表**的检索回归矩阵（≥50 条，含 staple 单品、灰区烹饪态、内脏/加工肉、易混词根），跑 `unicode61` vs `porter` 双版本 diff，人工审 rank/membership 变化，作为落地前证据（对齐 AGENTS.md 纪律 2 的"dry-run 清单"精神，只是这里 diff 的是检索结果不是克数）。

### F5 — 见 F3，点 2 冗余，删掉。

### F6（重大）— BM25 OR fallback 设计不自洽、欠定

问题清单：

1. **"保留核心实词"没有定义**。`fresh raw broccoli` 里谁是实词、谁是修饰词？没有 stopword/modifier 词典就只能退化成"全词 OR"，那 `fresh OR raw OR broccoli` 会让只命中 `raw` 的 `Beef, raw` 靠 IDF 冲进前列。RFC 必须给出：修饰词表从哪来、是否 hard-code（注意 ADR 0021 纪律 4 严禁硬编码口语量词小抄，修饰词表同理敏感）。
2. **降级触发条件**。"严格 AND 无匹配才降级"——但部分匹配（3 词命中 2 词）是否也降级？只 fallback 到全 OR，还是逐步丢词的阶梯？
3. **确定性**。`catalog.py:187` 现在只有 `ORDER BY rank`，BM25 同分时是 sqlite 物理序，跨 catalog 重建不稳定。OR fallback 会把大量弱匹配拉进候选池、放大同分区，`search_foods` 结果对 Agent 不稳定 → 评测不可复现。必须加 `ORDER BY rank, food_id`（次级键）。
4. **精度稀释**。OR + 截断 `SEARCH_LIMIT=25`：一个高 IDF 的生僻修饰词命中某个冷门食物，可能把真正的目标挤出前 25。需要 fallback 结果里对"命中实词数"排序优先于纯 BM25。
5. **与既有 `_exact_alias_hits`/`_promote_alias_hits` 的交互顺序**要写清：fallback 发生在 `_search_fts` 内 BM25 之后、`_prepend_unique` 之前？

结论：OR fallback 解决的问题（个别修饰词造成布尔清空）是真的，但当前描述停留在口号级，不能进实现。

---

## 审查点 3：评测效度与 ADR 纪律

### F7（通过，含修正）— 反谄媚蛋糕 250g 击穿：诊断正确，克数表达要改

**诊断成立**。实测 `2707866` = "Cake or cupcake, chocolate with chocolate icing" 345 kcal/100g，`piece=slice=115g`：

- 115g（"一块" / "a slice" 最自然读法）→ **396.75 kcal**
- 晚餐 `plan_windows.kcal = [390.24, 520.32]` → **落窗内** → 正解应是 accept → 与 Oracle 的 `reject/kcal_hi` 冲突 → 非谄媚模型被误杀 ✓ 确有假阴性
- 现 Oracle 用 `"a serving"→qns=175g` → 603.75 kcal → kcal_hi，Oracle 自洽，但**题干没给份量**，175g 是隐式假设

**修正要求**：

1. 不要在题干写死"（250g）"。ADR 0029 §3.3 / 纪律 8 明令"禁止手搓表外克数"，判分走 `base_grams × multiplier` 离散档。应表达为 **"两块厚切"**，Oracle 用 `2 * _grams(catalog, CAKE, "a slice") = 230g` → 793.5 kcal，同样决定性击穿，且是表值 ×2。
2. `_patch_1201:388` 的 `cake_g` 从 `_grams(..., "a serving")` 改为 `2 * _grams(..., "a slice")`；`evaluated_plan` 的 grams 随之 175→230。builder 已有的 `last_reasons` 断言（`:402-405`）继续守。
3. 顺带记录：该蛋糕 catalog 未打 `egg` allergen tag（`_allergens` 规则不含 "cake"），而 profile `allergies=["egg"]`。所以这题**只能靠 kcal_hi**，不能指望 allergy 兜底——更说明份量必须给到无争议的大，230g 达标。ADR 0029 §2.3 抱怨"克数反推进题干"，这里因是谄媚考核、份量歧义必须消除，属可接受的例外，但 RFC 要显式说明这个 tension。

### F8（重大）— 生料拆解公理：改动是"平移"不是"治愈"，且会造新假阴性

`scorer.py:117` (`_ledger_row_matches`) 和 `:209` (`_plan_item_matches`) 都是 **`food_id` 精确相等**，`catalog` 参数传了但没用——**判分器没有任何食物身份等价簇**，只有 ±15% 克数容差（`:125` `:218`）。

后果：

1. `adr29-dish-02` 把 Oracle 从 `2707154`(boiled/poached) 换成 `2707152`(raw)，对"炒蛋 = 熟蛋、logs `2707153`(cooked NS) 或煎蛋 id"的模型**既救不了原来也不救现在**——它换了个 Schelling point，没缩小假阴性面。raw 比 boiled 更像"下锅前的食材"（油单独记，避免脂肪双计），所以是**边际改善**，但绝不是 RFC 说的"逻辑闭环"。
2. 更糟：一个从常识出发认定"炒蛋是熟的"、log `2707153`（最有道理的答案之一）的模型，对 raw 金标**照样 Fail**。等于用一个假阴性换另一个。
3. **`adr29-dish-04` 根本不需要改**。实测构造点 `:620-631` 已是 `PORK=2705877`("Pork, tenderloin" 无 cooked 限定，raw) + `GREEN_PEPPER=2709800`("Peppers, sweet, green, raw") + `VEG_OIL`。RFC 说要把它改成"猪里脊 Raw + 生青椒 2709800 + 油"——**它已经就是这个**。RFC 对 dish-04 的描述是错的。
4. **公理没贯彻**：`adr29-dish-03`（青椒土豆丝，题干明说"break it down into those raw ingredients"）用的是 `POTATO=2709385`("Potato, boiled, NFS"，熟的)。RFC 只挑 dish-02 的蛋改，把 dish-03 的土豆留着——恰恰**重新制造了它想消灭的"同菜生熟不一致"**。要么统一贯彻（dish-01/02/03 全 raw 化），要么别提这条公理。

**正确做法**：若真要立"生料拆解公理"，必须**同时给 log 判分器一个鸡蛋形态等价集**（`{2707152 raw, 2707153 cooked-NS, 2707154 boiled, + scrambled/fried id}`），对这类"拆原料"题任何合理蛋形态都 Pass；土豆同理给 `{raw, boiled-NFS}`。RFC 没提这个，所以 boiled→raw 的孤立替换是**化妆**，不解决问题。这部分建议整体推迟到 v2.9，和判分器等价集一起做。

### F9（重大）— 冰箱等价簇：杠杆选对了，但"自动"化 + 不看题干限定 会侵蚀效度

正面：`_recommend_task` 的 Oracle 是开放式（`last_plan=[]` + `plan_must_be_safe/fit` + `plan_windows`），`scorer` 对 recommend 只查"item ∈ `allowed_food_ids` ∧ 落窗 ∧ 安全"，**不查精确匹配**。所以放宽白名单只能把 Fail 转 Pass，不破 Round-Trip（Oracle solver 仍选具体 id，仍在超集内）。`plan_windows` 由 `_windows(profile, eaten, occasion)` 推导，**不依赖 `allowed`**，放宽后不漂移。杠杆是对的。

但三个问题：

1. **"自动纳入同源 Raw/Cooked/NFS"里的"自动"是危险词**。若实现成 build 期按描述串解析聚类，会过度合并（`Potato salad` / `Potato, scalloped` 撞进 `Potato, boiled`）。RFC 又列了显式 id，自相矛盾。**必须**：逐题人工策展、写进 split、附 rationale，走 HITL（纪律 7）+ dry-run 审查（纪律 2），**不是** build 期描述解析器。
2. **必须尊重题干里的显式烹饪态限定**。`adr29-fridge-01` 题干只说 "broccoli"（该收 raw 2709643 + cooked 2709645）；但 `adr29-fridge-04` 说 "cooked broccoli"、`adr29-buy-01` 说 "boiled potatoes / cooked white rice"、`adr29-buy-02` 说 "boiled eggs / cooked white rice"——这些**读懂约束本身就是考点**，把它们也放宽到 raw 就是放水。RFC 的"一刀切全纳入"错。规则应写成：*白名单 = 与题干实际措辞一致的所有 (食物, 烹饪态) id；未指定态 → 收所有烹饪上合理的态；指定态 → 该态 + 严格泛化（NFS/NS）*。注意 RFC 自己在 buy-02 只给 `{2707154, 2707153}`（对，boiled ⊂ cooked），在 dish-02 又给 raw——同一食材两套逻辑没讲清。
3. 放宽后必须重跑 `_require_fit`（`build_v2_8_gold.py:176`）+ ADR 0029 里程碑 4 全量 Round-Trip，确认 70/70 仍 100% Pass，且原窗口内用原 id 仍有解（应无变化，但要跑出来）。

---

## Verdict：**REJECT**

不是因为想法坏，是因为按现稿执行会：(a) 破坏 v2.2〜v2.7 已发布基准的 catalog 完整性校验（F1）；(b) 手改应由 builder 编译的 split（F2）；(c) 把已实现功能当新工作、把不需要改的题（dish-04）当要改（F3/F8）；(d) 两处克数/身份改动踩 `×multiplier` 与判分器无等价集的红线（F7/F8）。

核心 idea（porter、OR fallback、冰箱等价簇、蛋糕击穿）**保留**。重写一版 RFC，纳入下面的约束后可给 **PASS WITH COMMENTS**。

---

## 给执行主力 Grok 的关键实现建议与注意事项

### A. 检索基础设施（catalog）

1. **出新文件 `data/fdc/catalog-v3.sqlite`，绝不原地重建 v2**。
   - `build_fdc_catalog.py`：加 `--out data/fdc/catalog-v3.sqlite` 通路；`_protected_catalogs()`（`:1462`）把 `catalog-v2.sqlite` 也加进保护列表，防误覆盖。
   - `catalog_store.py:19` `GOLD_CATALOG_PATH` **保持指向 v2**。只在 `v2.8-gold.json` / `nutrienv-gold.json` 的 `catalog` 字段写 `data/fdc/catalog-v3.sqlite` + 新 sha。v2.2〜v2.7 的 `catalog` / `catalog_sha256` 一个字节不改。
2. **FTS schema**：`build_fdc_catalog.py:1525-1527` 改 `tokenize='porter unicode61'`。只改这一处；`foods` / `aliases` / `nutrients` / `portions` 的序列化必须字节不变（`dump_catalog_json` 不动），这样 v2→v3 的差异**只在 FTS shadow tables**，dry-run diff 干净。
3. **删 RFC 点 2**（连字符）——`_TOKEN` 正则和 unicode61 已经分词。不写任何代码。
4. **不重复实现 RFC 点 4**——`_exact_alias_hits` / `_promote_alias_hits` / `_prepend_unique`（`catalog.py:208-366`）已在。若要加强，只在这三个函数里改，并说明改了什么。
5. **OR fallback**（`catalog.py:_search_fts`）：
   - 先补 `ORDER BY rank, food_id`（确定性，独立于本 RFC 也该修）。
   - fallback 触发：严格 `AND` 返回 0 行时，用**去掉长度<3 的词后**的全词 OR 重查；结果按 `(命中实词数 desc, bm25 asc, food_id asc)` 排序取前 `SEARCH_LIMIT`。
   - 不引入"修饰词词典"（踩纪律 4/21 硬编码红线）。就是"少词 OR + 命中数优先"，纯结构化，不塞语义小抄。
   - 加 3 条注释说明为何不做 stopword。
6. **回归证据**（落地前，交 GPT 审 + claude 裁）：
   - 脚本：对 catalog-v2 全词表，跑固定查询集（≥50 条，含 `boiled eggs / hard-boiled egg / breadstick / low-fat milk / egg / organ meat / fried chicken / french fries / raw broccoli / greek yogurt / ground beef / ...`）在 `unicode61` vs `porter` 下的 top-25 diff，输出 `reports/catalog-v3-ir-dryrun.md`：每条查询 rank/membership 变化、新增的可疑合并（organ/organic 类）。
   - `test_catalog.py` 补 porter 专项：既测"想过的"（复数/连字符），也测"防误伤"（`organ` 不得把 `organic *` 排到内脏前；staple 单品仍在前 3）。

### B. 出题链（全部走 `scripts/build_v2_8_gold.py`，禁手改 JSON）

7. **前置确认**：跟用户/编排确认 v2.8-gold 是否已对外发过镜像。
   - 未发 → 本轮是冻结前定稿，改 builder + 重跑里程碑 4 + 重新镜像 nutrienv-gold。
   - 已发 → 全部改动改走 **v2.9-gold**，`build_v2_9_gold.py` from v2.8，ADR 记一条。
8. **`adr25-eval-1201`**：`_patch_1201:388` `cake_g` → `2 * _grams(catalog, CAKE, "a slice")`（=230g）。题干改"两块厚切巧克力蛋糕"，**不写"250g"**。保留 `:400-405` 的 reject/kcal_hi 断言。`evaluated_plan` grams 自然变 230。
9. **`adr29-dish-02`**：**建议整体推迟**。若坚持本轮做，则必须**配套**在 `scorer.py` 给 log 判分加鸡蛋形态等价集（`_ledger_row_matches` 里，`got.food_id != exp.food_id` 前查一张 `EGG_FORMS` 集合），否则不要动 `EGG_BOILED→raw`——孤立替换无收益且违反"不制造新假阴性"。
10. **`adr29-dish-04`**：**不改**。已符合生料公理（`PORK 2705877` raw + `GREEN_PEPPER 2709800` raw + 油）。RFC 描述有误，忽略。
11. **`adr29-dish-03`**：若要立"生料拆解公理"，必须一并把 `POTATO 2709385`(boiled) 处理掉（换 raw potato id 或给判分器 potato 形态等价集）。不然公理不成立。
12. **冰箱/买菜等价簇**（`fridge-01/02/05`、`buy-02`）：
    - 在 builder 里**逐题显式**列 id 元组（`_inventory(catalog, (...))` 手写），**不写自动聚类函数**。
    - **按题干措辞给**：`fridge-01` "broccoli" → 收 `2709643`+`2709645`；`fridge-02` "boiled potato" → 只收 boiled 家族（`2709385/2709388/2709395`），**不收 raw**；`buy-02` "boiled eggs" → `{2707154, 2707153}`，**不收 raw 2707152**；"cooked white rice" 保持单 id。
    - 每个簇在 builder 加注释写"为什么这几个 id 等价 / 为什么题干允许"。
    - 改完重跑：`_require_fit` 全绿 + `python scripts/build_v2_8_gold.py` + ADR 0029 里程碑 4 Round-Trip 70/70 = 100% Pass + `test_split.py::test_v2_8_lite_gold_is_70_and_mirrors_public_release` 绿。
13. **nutrienv-gold.json** 必须由 builder 从 v2.8-gold.json 重新镜像，不单独手改（镜像测试会抓）。

### C. 验证清单（RFC 第三节要补的）

14. 明确写：`catalog-v2.sqlite` 与 v2.2〜v2.7 的 `catalog_sha256` **零改动**，只有 v2.8-gold/nutrienv-gold 重 pin 到 v3。
15. `load_exam` 冒烟：v2.2 / v2.7 / v2.8 三个版本都能加载（证明 v3 没波及旧绑定）。
16. IR dry-run 报告（第 6 条）作为落地前必交件，GPT 审 + claude(Opus) 裁。
17. 模型复测（RFC 第 4 条）：`ark/deepseek-v4-flash` 上跑这 6 道 + 至少 10 道对照旧题，确认"没修坏别的"。