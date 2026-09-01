# v2 第二轮 sample 审阅（15 条，synthetic，entailment 已修）

审阅人：claude（Sonnet 5）· 日期：2026-08-27
材料：`.scratch/v2-samples/review-brief-round2.md` + `.scratch/v2-samples/samples.json`
参照：`src/nutrienv/harness/react.py`（v0/v1 手册）、`scripts/generate_samples.py`（本轮改）、
`src/nutrienv/bench/pipeline/sampler.py::spoken_display_name`（本轮新增）、
`src/nutrienv/bench/validator.py`、`src/nutrienv/bench/scorer.py`、`data/fdc/catalog-v2.sqlite`

范围：自然度 / 蕴含 / 同名一致性 / 量具匹配 / 手册对称性。克数、窗口、reason 数值本身不由本审判断。

---

## 0. 结论速览

| family | 上轮 | 本轮 | 一句话 |
|---|---|---|---|
| log | FAIL | **NITS** | 蕴含全修好；残留是自动命名的语感 + 量具挑得不贴食物（"a bowl of roast beef"、"16 g of seafood sauce"） |
| evaluate | FAIL | **NITS** | 蕴含全修好（accept 盘子可精确重建）；残留是 ≥3 段 FNDDS 名被拼成病句 + "240.0 g" 格式 + "a cup of 汉堡/牛肉" |
| recommend | PASS | **PASS** | 3 条模板句干净、无泄漏；batch 覆盖度 NIT 仍未处理 |
| update | PASS | **PASS** | 3 条都明说改哪个字段，未提字段留 S0 合理 |
| composite | FAIL | **NITS** | 蕴含全修好；log 半句量具 NIT 同 log family（comp.2 "a tablespoon of seafood sauce" 反而最干净） |

**根因已修（核对通过）**：`spoken_display_name` 保留全部判别 token、去掉 `/` 与 `with/and`、把中心词移到词尾
（"roast beef" / "pork cheese burrito" / "fontina cheese"），runner 增加 entailment gate
（Oracle 每个食物的 display token 必须全出现在 query）。用 query 里的原短语跑 `FoodCatalog.search`，
**15 条涉及的 8 个食物全部 rank #1**（见 §2 表）。上一轮"题面不蕴含答案"的 FAIL 不再存在。

**本轮所有非 PASS 都是 NITS，没有 FAIL。** 残留问题两类：
(a) `spoken_display_name` 对 ≥3 段描述的 FNDDS 名会产出语法不通的串（"cheese-filled tomato sauce
meatless manicotti"、"german chocolate cake or cupcake"）；
(b) 造题各处挑量具时不看食物本性（fit-plate 搜索 / synthetic rewriter / amount-path 知识都可能给出
"a cup of roast beef"、"16 g of seafood sauce"、"240.0 g of chocolate candy"）。

---

## 1. 逐条

### log — NITS

judge：`Scorer._score_one`，`end_state.ledger[-n:] == Oracle.ledger_tail`，food_id 字符串精确比。

#### log.1 — one-log-0002（seed=2, gym）— **NITS**
- query: `For lunch I had a bowl of roast beef.`；Oracle `2705847 "Beef, roast" @60g`（qns=slice=60）。
- 蕴含 ✅：`search("roast beef")` → `2705847` **#1**。
- 手册对称 ✅：`a bowl of X` → v1 "bowl … → portions.qns，fallback piece→slice→cup"；qns=slice=60，任取不漂。
- 自然度 ✅（帧）：`For lunch I had …` 是 `build_log_system_prompt` Style 里推荐的帧，比上轮 `Please log …` 强。
- **NIT（量具）**：roast beef 是切片/装盘的东西，不是"一碗"。`"a bowl"` 是 `unspecified` 路径写死的字符串
  （`generate_samples.py:89`）。同一食物有 `slice`（60g，克数相同），"a slice of roast beef" 更像人话。
- NIT：persona=gym 对 synthetic 文本零影响（帧固定）。

#### log.2 — one-log-0003（seed=3, everyday）— **NITS**
- query: `For lunch I had 16 g of seafood sauce.`；Oracle `2706452 "Seafood sauce" @16g`（tbsp=16）。
- 蕴含 ✅：`search("seafood sauce")` → `2706452` **#1**。
- 手册对称 ✅：explicit grams，"16 g" → 16。
- **NIT（量具/自然度）**：没人把蘸酱记成 "16 g of seafood sauce"。这条走 `explicit_grams` 路径
  （`AMOUNT_PATHS[3%3]`）。**同一食物在 composite.2 里被写成 "a tablespoon of seafood sauce"——那才是对的。**
  amount-path 轮转把"克数路径"配到了一个只会用勺量的调味料上。

#### log.3 — one-log-0004（seed=4, everyday）— **NITS**
- query: `For lunch I had a piece of bacon egg sandwich on english muffin.`；
  Oracle `2707317 "Egg sandwich on English muffin, with bacon" @225g`（piece=225）。
- 蕴含 ✅：`search("bacon egg sandwich on english muffin")` → `2707317` **#1**；
  "bacon" 把它和 plain / ham / sausage 版本分开。
- 手册对称 ✅：`a piece of X` → v1 直给键 `piece`=225。
- NIT（自然度）：三明治是整个吃的，"a piece of [a sandwich]" 略拗；"a bacon and egg English muffin"
  更自然。"a piece of X" 是 mill 的通用计数帧，勉强可接受。
- NIT：`english muffin` 小写专有名词（`spoken_display_name` 全小写）；`german` / `fontina` 同理。随手打字确实小写，轻。

### evaluate — NITS

judge：accept → `state.last_plan != oracle.last_plan`（food_id+grams 精确 list 比）；
reject → `set(state.last_reasons) != set(oracle.last_reasons)`。

#### evaluate.1 — one-eval-0000（seed=0, everyday, tier=single）— **NITS**
- query: `Evaluate this as my plan for lunch: a cup of pork cheese burrito and a cup of fontina cheese.`
  verdict=accept；last_plan=`[{2708539,120},{2705715,108}]`。
- 蕴含 ✅✅（**上轮 FAIL，本轮修好**）：`search("pork cheese burrito")` → `2708539` #1；
  `search("fontina cheese")` → `2705715` #1。agent 能把两个 id + 120/108g 精确重建 → accept 可过。
- 手册对称 ✅：`a cup of` → v1 直给键 `cup`；cup=120 / cup=108 都是餐桌值。
- **NIT（量具）**：卷饼是手持单位（"a burrito" / `piece`=190），不该用"杯"。fit-plate 搜索选了 120g（=cup）
  这个组合，`_phrase_for_grams` 只好回 "a cup"。live 提示词自带 "'a cup of' only for soup/rice/beans/…"，
  synthetic rewriter 不受这条约束。
- NIT：`a cup of fontina cheese`（108g）——擦丝奶酪按杯尚可，比卷饼那句轻。
- NIT：`pork cheese burrito` 词序像清单，但可读、可搜。

#### evaluate.2 — one-eval-0002（seed=2, gym, tier=single）— **NITS**
- query: `Evaluate this as my plan for lunch: a cup of roast beef and 240.0 g of peanut butter filled
  chocolate candy.` verdict=reject；reasons=`[kcal_hi]`；knife=over_slot；人=roster-ben（无过敏）。
- 蕴含 ✅：`search("roast beef")` → `2705847` #1；`search("peanut butter filled chocolate candy")`
  → `2710347 "Chocolate candy, peanut butter filled"` #1。
- 一致性 ✅：`2710347` 带 `allergen_tags=["peanut"]`，但 roster-ben 无过敏 → reasons 只有 `kcal_hi`，
  没有误报 `allergy`。对。
- 手册对称 ✅：`a cup` → 直给键；`240.0 g` → v1 "Grams … are already grams" → 240。
- **NIT（格式）**：`240.0 g` 带小尾巴 `.0`——`synthetic_rewriter` 的克数兜底是 `str(grams) + ' g'`
  （`generate_samples.py:151`），float 的 `str()` 留了 `.0`。应 `f"{grams:g} g"` → "240 g"。真人不写 "240.0 g"。
- **NIT（量具）**：糖果按颗/把吃（`piece`=8g），不按克秤。over_slot 把糖果放大到 240g，这个量不是任何
  quantity-1.0 餐桌项 → 只能回退成裸克数。
- NIT：`a cup of roast beef` 同 eval.1（有 `slice`=60，更自然）。

#### evaluate.3 — one-eval-0017（seed=17, everyday, tier=single）— **NITS（偏 borderline）**
- query: `Evaluate this as my plan for lunch: a piece of german chocolate cake or cupcake and a cup of
  cheese-filled tomato sauce meatless manicotti.` verdict=reject；reasons=`[allergy, kcal_hi]`；
  knife=allergy；人=roster-quin（过敏 milk）。
- 蕴含 ✅：`search("german chocolate cake or cupcake")` → `2707869` #1；
  `search("cheese-filled tomato sauce meatless manicotti")` → `2708776` #1。
- 一致性 ✅：`2708776` 带 milk tag，roster-quin 过敏 milk → `allergy` 触发；德式巧克力蛋糕 piece=200g
  + manicotti 235g → `kcal_hi`。两个 reason 都可复现（前提是 agent 用完整描述短语去 search，见 §2）。
- 手册对称 ✅：`a piece of` → piece=200；`a cup of` → cup=235（manicotti cup=qns=235，无离散单位）。
- **NIT（自然度）**：`german chocolate cake or cupcake` —— "or cupcake" 是 FNDDS 类目尾巴，
  `spoken_display_name` 只去 `with/and`，没去 `or`。人只会说 "german chocolate cake"。读着像数据库导出。
- **NIT（自然度）**：`cheese-filled tomato sauce meatless manicotti` —— 描述 token 被拼成病句
  （中心词移尾 + 逐段平铺）。人会说 "cheese manicotti" / "manicotti in tomato sauce"。可搜但不通顺。
- NIT：`german` 小写。

### recommend — PASS

#### recommend.1 / .2 / .3 — one-rec-0000 / 0001 / 0003 — **PASS**
- `What should I eat for lunch?` / `What's for dinner?` / `What should I eat for lunch?`
- 模板句（`templates.py`，冻结口径），不泄漏过敏原 / 剩余预算 / window 数字；
  手册 "Recommend: submit_plan a safe meal that fits the windows; omit verdict" 可复现。
- **NIT（batch 覆盖度，不改本条判定，与上轮相同、未处理）**：3 条里 2 条逐字相同
  （seed 0 与 3 都落 `shells[seed%3]==rec-lunch`）；`rec-named-dish`（"Thinking of {dish} tonight …"
  受限命名菜陷阱）在 seed%3==2 触发，但 seed=2→roster-ben 无过敏 → `_allergen_dish` 返回 None
  → `no_allergen_dish` 被拒（见 samples.json rejected）。该形态本批仍缺席。

### update — PASS

#### update.1 — one-upd-0000（seed=0, everyday, S0 过敏 tree_nut）— **PASS**
- `Add milk to my allergies.` 明说加什么；未提字段留 S0 合理
  （Oracle = `replace(profile, allergies=normalize_tags([tree_nut, milk]))`）。
- 手册 "Profile allergies are catalog allergen_tags (shellfish, peanut), not food names" 可复现：`milk` 是合法 tag。
- 软 NIT（不改判）：手册 allergen_tag 举例无奶制品项。

#### update.2 — one-upd-0001（seed=1, gym）— **PASS**
- `I weigh 71 kg now. Update my weight.` 与手册 "Body facts ('I weigh 70 kg now') … windows re-derive
  automatically" 几乎逐字对上。可复现。

#### update.3 — one-upd-0002（seed=2, gym, S0 phase=muscle）— **PASS**
- `I'm cutting now.` 增肌期转 cut 合理。judge 走 `_implicit_update_ok`（phase patch 或直接挪窗口都收），
  手册 "Spoken cutting … patch phase … no published step size" 可复现。

### composite — NITS

`steps=("log","recommend")`，双 oracle。log 半句进 `_bind_log_foods`，recommend 半句不得点名 pool 食物。

#### composite.1 — one-comp-0002（seed=2, gym）— **NITS**
- query: `I had a cup of roast beef for lunch. What should I eat for dinner?`（Oracle log 行 `2705847`）
- 蕴含 ✅（"roast beef" → #1，上轮 FAIL 修好）；log 半句手册 ✅（cup=135）；recommend 半句干净、无泄漏；连接句自然。
- NIT：`a cup of roast beef` 量具/食物错配（有 `slice`）。

#### composite.2 — one-comp-0003（seed=3, everyday）— **PASS**
- query: `I had a tablespoon of seafood sauce for lunch. What should I eat for dinner?`（Oracle `2706452`）
- 蕴含 ✅；**量具 ✅——"a tablespoon" 正是调味料该用的单位**（对照 log.2 同一食物写成 "16 g"）；
  手册 ✅（v1 列了 "tbsp (tablespoon)"，tbsp=16）；recommend 半句干净；连接句自然。
- 本批最干净的 composite。

#### composite.3 — one-comp-0004（seed=4, everyday）— **NITS**
- query: `I had a piece of bacon egg sandwich on english muffin for lunch. What should I eat for dinner?`
  （Oracle `2707317`）
- 蕴含 ✅；手册 ✅（piece=225）；recommend 半句干净。
- NIT：`a piece of [sandwich]` 帧略拗 + `english` 小写（同 log.3）。

---

## 2. 横切发现

### 2.1 蕴含修复——核对通过

用 query 里点名该食物的**完整短语**跑 `FoodCatalog.search`（手册要求的 `search_foods {q}`）：

| query 里的说法 | Oracle food_id / 名称 | search rank |
|---|---|---|
| pork cheese burrito | 2708539 Burrito, pork, cheese | **#1** |
| fontina cheese | 2705715 Cheese, Fontina | **#1** |
| roast beef | 2705847 Beef, roast | **#1** |
| seafood sauce | 2706452 Seafood sauce | **#1** |
| bacon egg sandwich on english muffin | 2707317 Egg sandwich on English muffin, with bacon | **#1** |
| peanut butter filled chocolate candy | 2710347 Chocolate candy, peanut butter filled | **#1** |
| german chocolate cake or cupcake | 2707869 Cake or cupcake, German chocolate | **#1** |
| cheese-filled tomato sauce meatless manicotti | 2708776 Manicotti, cheese-filled, with tomato sauce, meatless | **#1** |

上轮 8 个通名里 7 个命不中；本轮 8/8 命中 #1。这是本轮的核心改善，log/evaluate/composite 因此从 FAIL 升到 NITS。

### 2.2 残留：entailment gate 校的是 token 覆盖，不是 search 排名

`generate_samples.py::_query_entails_food` = `set(display tokens) <= set(query tokens)`。
这是"search 命中 #1"的**必要非充分**条件。本批 8 条实测都 #1，但换个 catalog / 换个食物，
display token 全在、search 仍把兄弟条目排前面的情况会漏过 gate。

**建议**：gate 直接断言 `FoodCatalog.search(display_name, limit=1)[0]["food_id"] == oracle_food_id`
（就是本审 §2.1 跑的那个），而不是 token 子集。

另一半残留是 agent 侧：**只搜中心词仍命不中**——

| 只搜 | Oracle rank |
|---|---|
| manicotti | #3 |
| cheese | 不在 top-10 |
| burrito | #4 |
| beef | #5 |
| chocolate candy / cake or cupcake / egg sandwich | 不在 top-10 |

query 现在把判别词都给全了，勤快的 agent 复制完整短语就能 #1；但 react.py 手册没说"要带上所有修饰词"。
可在 v1 手册加一句，或靠 §2.2 的 search-排名 gate 兜底。

### 2.3 `spoken_display_name` 启发式对 ≥3 段 FNDDS 名产出病句

规则是"去 `/`、去 `with/and`、中心词移词尾、其余逐段平铺"。1–2 段名效果好
（roast beef / fontina cheese / pork cheese burrito / seafood sauce）；≥3 段就散架：

- `Manicotti, cheese-filled, with tomato sauce, meatless` → `cheese-filled tomato sauce meatless manicotti`（病句）
- `Cake or cupcake, German chocolate` → `german chocolate cake or cupcake`（"or cupcake" 是类目尾巴，没去掉）
- `Egg sandwich on English muffin, with bacon` → `bacon egg sandwich on english muffin`（尚可）

**建议**（任一）：
1. 停止词再加 `or` / `nfs` / `style` / `prepared` 之类；
2. 不做"中心词移尾"，保留 FNDDS 段序、只删逗号和停止词（"manicotti cheese-filled tomato sauce" 比现在通顺）；
3. 最稳：给进池的 FNDDS 食物补 curated alias（像 `2706286` 有 `('atlantic salmon','baked salmon','salmon')`），
   `spoken_display_name` 有 alias 就直接用。

### 2.4 量具挑选处处不看食物本性

- fit-plate 搜索（`search_fit_plate`）只按"窗口能不能 bind"选 quantity-1.0 组合，选中 135g 就逼出 "a cup of roast beef"；
- `synthetic_rewriter._phrase_for_grams` 只按"克数正好等于某餐桌项"回短语，克数放大后没匹配就回裸克数（"240.0 g"）；
- synthetic tracer 的 `unspecified` 路径写死 `"a bowl"`（"a bowl of roast beef"）；
- amount-path 轮转把 `explicit_grams` 配到调味料（"16 g of seafood sauce"）。

结果：`a cup of roast beef` / `a cup of pork cheese burrito` / `16 g of seafood sauce` /
`240.0 g of chocolate candy`，都是量具与食物打架。checklist 明确要求 "patty 用 piece，不应 cup"。

**建议**：造题挑量具时，食物若有离散单位（`piece`/`slice`/`patty`/`can`）优先于 `cup`；
把 live 提示词那条 "'a cup of' only for soup/rice/beans/oatmeal/yogurt/cereal" 也搬进 synthetic 两个说话器；
`unspecified` 路径按食物类别在 bowl/plate/serving 里选（`build_log_system_prompt` 已有 "plated mixed dishes
→ 'a plate of' / 'a bowl of'" 的意思）。

### 2.5 小项

- `synthetic_rewriter` 克数兜底 `str(grams) + ' g'` → "240.0 g"。改 `f"{grams:g} g"`。一行。
- composite 三条 payload 里 `family` 字段是 `"log"`（`_log_then_recommend` 传的 split-vocabulary tag）；
  review 材料里看着像串味，实际是内部标签，cosmetic。
- log.2（"16 g"）与 composite.2（"a tablespoon"）是同一食物 `2706452` 的两种说法——不是同一条题内的矛盾，
  但说明量具选择在 log 路径和 composite 路径下不一致。

---

## 3. 手册对称性（react.py v0/v1）结论

- **量具/克数侧：全对称。** 本批出现的 `a bowl`（→qns，v1）、`N g` / `240.0 g`（→grams）、
  `a cup` / `a piece` / `a tablespoon`（v1 直给键）都能被手册规则映到 Oracle 克数；
  log.1 走 fallback（bowl→qns→slice）克数不漂。
- **食物身份侧：本批 15 条全对称**——§2.1，8/8 search #1。上轮唯一的致命破口已闭合。
- **残留（NIT 级）**：agent 必须用 query 给的完整描述短语去 search；只搜中心词仍命不中（§2.2）。
  gate 校的是 token 覆盖而非 search 排名，换食物可能漏（建议 §2.2）。
- recommend / update 无手册对称性问题。
- evaluate reject 需精确 reason 集——本批 `kcal_hi` / `allergy, kcal_hi` 的复现链在食物可辨后成立，
  但仍依赖 agent 带全描述词搜对食物。

---

## 4. Family 判定与理由

### log — NITS
- log.1：蕴含/手册/帧都过；NIT = "a bowl of roast beef"（切片食物写成一碗；同克数有 `slice` 更自然）+ persona 无影响。
- log.2：蕴含/手册过；NIT = "16 g of seafood sauce"（调味料被 explicit_grams 路径逼出裸克数；composite.2 同食物用 "a tablespoon" 才对）。
- log.3：蕴含/手册过；NIT = "a piece of [三明治]" 帧略拗 + `english` 小写专有名词。

### evaluate — NITS
- eval.1：蕴含修好（accept 盘子可精确重建）；NIT = "a cup of pork cheese burrito"（卷饼按杯量）+ 词序像清单。
- eval.2：蕴含/一致性/手册过；NIT = "240.0 g"（float 尾巴，应 "240 g"）+ 糖果按克秤 + "a cup of roast beef"。
- eval.3：蕴含/一致性/手册过；NIT = "german chocolate cake or cupcake"（"or cupcake" 类目尾巴）
  + "cheese-filled tomato sauce meatless manicotti"（描述词拼成病句）+ 小写。

### recommend — PASS
- 3 条模板句自然、无 allergy/预算/window 泄漏、手册可复现。
- NIT（不改判，与上轮同、未处理）：2/3 逐字重复；`rec-named-dish` 形态因 seed 配到无过敏 roster 人而缺席。

### update — PASS
- 3 条都明说要改的字段，未提字段留 S0 契约合理，均对得上 react.py 手册条款。
- 软 NIT（不改判）：手册 allergen_tag 举例无奶制品；`milk` 实为合法 tag，可复现。

### composite — NITS
- comp.1：蕴含修好；NIT = "a cup of roast beef"（同 log/eval）。
- comp.2：**PASS**——蕴含 + 量具（"a tablespoon"）+ 手册 + 衔接全对，本批最干净。
- comp.3：蕴含修好；NIT = "a piece of [三明治]" 帧 + `english` 小写（同 log.3）。

---

## 5. 建议（按优先级）

1. **entailment gate 升级为 search-排名断言**：`search(display_name, limit=1)[0]["food_id"] == oracle_food_id`，
   取代当前的 token 子集检查（§2.2）。这是唯一还可能让坏题漏过的机械缺口。
2. **`spoken_display_name` 处理 ≥3 段名**：停止词加 `or/nfs/style/prepared`；或保留 FNDDS 段序不移中心词；
   或给进池 FNDDS 食物补 curated alias 并优先用之（§2.3）。
3. **量具挑选贴食物**：有离散单位（piece/slice/patty/can）优先于 cup；把 live 的 "cup only for
   soup/rice/beans/…" 规则搬进 synthetic 两个说话器；`unspecified` 按类别在 bowl/plate/serving 里选（§2.4）。
4. **`synthetic_rewriter` 克数格式**：`f"{grams:g} g"`，去掉 "240.0 g" 的尾巴（一行，§2.5）。
5. **react.py v1 手册**加一句"search 时带上 query 里给的全部修饰词"，或直接靠建议 1 兜底（§2.2）。
6. **recommend batch 覆盖**：`rec-named-dish` 只配有过敏原的 roster 人；避免 3 条里 2 条逐字重复（与上轮同）。
7. 大写：`spoken_display_name` 可保留原名里已大写的 token（English / German / Fontina），低优先。

**总评**：上一轮的 FAIL 根因（题面不蕴含答案）已确实修复并核对通过。本轮 15 条无 FAIL；
log / evaluate / composite 的 NITS 都属"能过题但读着像机器/数据库导出"，不阻塞进 batch 试跑，
但建议 §5.1–§5.4 落地后再冻 v2-gold。recommend / update 可直接进下一轮。
