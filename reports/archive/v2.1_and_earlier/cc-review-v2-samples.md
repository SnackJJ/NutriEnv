# v2 首批 sample 审阅（15 条，synthetic）

审阅人：claude（Sonnet 5）· 日期：2026-08-27
材料：`.scratch/v2-samples/review-brief.md` + `.scratch/v2-samples/samples.json`
参照：`src/nutrienv/harness/react.py`（v0/v1 手册）、`scripts/generate_samples.py`、
`src/nutrienv/bench/pipeline/generate_one.py`、`src/nutrienv/bench/validator.py`、
`src/nutrienv/bench/scorer.py`、`data/fdc/catalog-v2.sqlite`

范围：只判自然度 / entailment / 同名一致性 / 手册对称性。克数、窗口、reason 数值本身不由本审判断
（但"agent 能否复现 reason 集"依赖 entailment，见 §2）。

---

## 0. 结论速览

| family | 判定 | 一句话 |
|---|---|---|
| log | **FAIL** | 口语食物名退化成通名（"Burrito" / "Beef"），`search_foods` 命不中 Oracle 的 food_id |
| evaluate | **FAIL** | 同上 + accept 需精确 plan 匹配；"a cup of Veggie burger patty" 等量具与食物打架 |
| recommend | **PASS** | 3 条模板句干净、无泄漏；仅 batch 覆盖度有 NIT |
| update | **PASS** | 3 条都明说要改什么，未提字段留 S0 合理 |
| composite | **FAIL** | log 半句继承 log family 的通名问题；连接句与 recommend 半句本身没问题 |

核心问题一句话：**synthetic 说话器把 FNDDS 长名截成第一个逗号前的词
（`name.split(",",1)[0]`），这些 FNDDS 食物都没有 alias，于是 query 里只剩
"Burrito"/"Beef"/"Cheese"/"Corn" 这种通名，指不回 Oracle 那一行。**
判分是 `end_state.ledger[-n:] == Oracle.ledger_tail`（food_id 字符串精确比），
所以这不是措辞瑕疵，是"题面不蕴含答案"。

---

## 1. 逐条

### log

约定：judge 用 `Scorer._score_one` → `end_state.ledger[-n:] != expected` 即 `log_miss`，
food_id 精确匹配，无 canonical 归并。手册要求 `food_id` 来自 `search_foods {q}` / `get_food`。

#### log.1 — one-log-0000（seed=0, everyday）— **FAIL**
- query: `Please log 120 g of Burrito for lunch.`；Oracle: `2708539 = "Burrito, pork, cheese" @120g`。
- **entailment 断裂**：catalog 有 31 行 `Burrito*`（21 行 `Burrito, …`）。
  `search_foods("burrito")` top-5 = Egg burrito / Burrito NFS / Burrito beef cheese / **Burrito pork cheese(#4)** / Burrito chicken cheese。
  agent 没有任何线索选到 #4 而不是 NFS。→ `log_miss`。
- 克数侧 OK：explicit grams，手册"Grams … are already grams"，120 就是 120。
- NIT（自然度）：`Please log {X} of {Y} for lunch.` 是模板机器腔；`build_log_system_prompt` 自己的 Style
  规则写了"prefer 'For lunch I had…' over robotic serving-of wording"、"Do not title-case foods"，
  synthetic 说话器两条都违反（"Burrito" 首字母大写、robotic frame）。persona=everyday 对文本零影响。

#### log.2 — one-log-0002（seed=2, gym）— **FAIL**
- query: `Please log a bowl of Beef for lunch.`；Oracle: `2705847 = "Beef, roast" @60g`（qns/slice 都是 60）。
- **entailment 断裂**：catalog 有 138 行 `Beef*`（81 行 `Beef, …`）。
  `search_foods("beef")` top-5 = Beef ground patty / Beef NFS / Beef oxtails / Beef shortribs / **Beef roast(#5)**。
  （`search_foods("roast beef")` 才会 #1 命中——但 query 里没有 "roast"。）→ `log_miss`。
- 量具侧 OK：`a bowl of X` → 手册 "bowl … → portions.qns，fallback piece→slice→cup"；qns=slice=60，任选都对。
- NIT（自然度）：没人把 roast beef 说成 "a bowl of Beef"；"Beef" 大写、通名。

#### log.3 — one-log-0003（seed=3, everyday）— **NITS（偏 FAIL）**
- query: `Please log 270 g of Egg sandwich on griddle/pancake for lunch.`；Oracle: `2707333 @270g`。
- entailment：`"Egg sandwich on griddle/pancake"` 已较具体，但 `search_foods(…)` top-2 =
  `2707332 Egg sandwich on griddle/pancake`（无肉，#1）/ `2707333 … with meat`（#2）。
  Oracle 是 "with meat" 那行，query 没说 "with meat" → agent 大概率取 #1 → `log_miss`。
- **自然度 FAIL 级**：`Egg sandwich on griddle/pancake` 是 FNDDS 原始描述，带斜杠 `griddle/pancake`
  是数据库产物，真人不会这样打字。应是 "an egg sandwich" 之类。
- 克数侧 OK：explicit grams，270=270。

### evaluate

约定：`_evaluate_from_items` → `search_fit_plate` 代码选盘 → `synthetic_rewriter` 用
`_phrase_for_grams`（找 quantity==1.0 且克数精确相等的餐桌项）配文。judge：
- accept：`state.last_plan != oracle.last_plan` 即 `wrong_goal`（food_id + grams 精确 list 匹配）。
- reject：`set(state.last_reasons) != set(oracle.last_reasons)` 即 `wrong_goal`。
`validator._validate_evaluate_verdict` 只校验"query 里出现了某个名字 token"，不校验歧义。

#### evaluate.1 — one-eval-0000（seed=0, everyday, tier=single）— **FAIL**
- query: `Evaluate this as my plan for lunch: a cup of Burrito and a cup of Cheese.`
  verdict=accept；last_plan=`[{2708539,120},{2705715,108}]`（`Burrito, pork, cheese` + `Cheese, Fontina`）。
- **entailment 双重断裂**：
  - "Burrito" → 见 log.1，命不中 2708539。
  - "Cheese" → `Cheese, Fontina` **不在 `search_foods("cheese")` top-10**（top-1 是 Cheddar）；
    catalog 有 107 行 `Cheese*`（61 行 `Cheese, …`）。
  - accept 需要精确交出这两个 id + 120/108 克 → 几乎不可能。→ `wrong_goal`。
- 量具侧 OK：`a cup of` → 手册直给键 `cup`；cup=120 / cup=108 都是餐桌值。
- NIT（自然度）：没人"a cup of Burrito"；live 侧提示词自己写了
  "Use 'a cup of' only for foods people really measure by the cup (soup, rice, beans, …)"，
  synthetic rewriter 不受这条约束，只按"克数正好等于某餐桌项"挑短语。
  "Cheese" 丢掉 "Fontina" 这个唯一判别信息。

#### evaluate.2 — one-eval-0001（seed=1, gym, tier=single）— **FAIL**
- query: `Evaluate this as my plan for lunch: a serving of Beef and noodles with gravy, a cup of Corn
  and a cup of Veggie burger patty.` verdict=reject；reasons=`[sodium_mg_hi]`；knife=over_slot。
- **entailment 断裂（Corn）**：Oracle 那行是 `2710046 = "Corn, scalloped or pudding"`（一道玉米布丁/焗菜），
  query 只说 "Corn"。`search_foods("corn")` top-5 = Corn dog / Tortilla corn / Corn nuts / Corn raw / Corn creamed，
  **"Corn, scalloped or pudding" 不在 top-10**（catalog 56 行 `Corn*`）。
  agent 取到普通玉米 → 钠总量变 → `sodium_mg_hi` 可能不触发 → reason 集不等 → `wrong_goal`。
- **自然度（Veggie burger patty）NIT/偏 FAIL**：`2707473` 自带 `patty` 键（一个 patty=100g），
  却因为 over_slot 后的克数=125 正好等于 `cup`（125g），rewriter 写成 "a cup of Veggie burger patty"。
  没人用"杯"量一块素肉饼。手册里 `patty` 是 count unit，本该说 "a patty" / "two patties"。
  （量具侧仍可复现：`cup` 是直给键。）
- `Beef and noodles with gravy` 这句读着还行（全名无逗号，没被截断）；`search_foods` 命中尚可。
- reason 数值本身不判，但"能否复现 `{sodium_mg_hi}`"因 Corn 歧义而不成立。

#### evaluate.3 — one-eval-0017（seed=17, everyday, tier=single）— **FAIL**
- query: `Evaluate this as my plan for lunch: a piece of Cake or cupcake and a cup of Manicotti.`
  verdict=reject；reasons=`[allergy, kcal_hi]`；knife=allergy；人=roster-quin（过敏 milk）。
- **自然度 FAIL 级**：`Cake or cupcake` 是 FNDDS 类目名，带 "or"。真人不会说 "a piece of cake or cupcake"。
  Oracle 是 `2707869 = "Cake or cupcake, German chocolate"`，判别词 "German chocolate" 被丢，"or" 被留。
- **entailment 断裂**：`search_foods("cake or cupcake")` top-5 全是 `Cake or cupcake, {NFS,apple,banana,carrot,coconut}`，
  **German chocolate 不在 top-10**（27 行近似同名）。agent 取到 NFS/其它口味 →
  German chocolate 的高热量不复现 → `kcal_hi` 可能不触发 → `wrong_goal`。
- allergy 侧尚可：`2708776 Manicotti, cheese-filled …` 带 `allergen_tags=["milk"]`，roster-quin 过敏 milk；
  `search_foods("manicotti")` 4 行里 3 行都带 milk，即便取错也大概率仍触发 allergy。
  但 reason 集要**精确** `{allergy, kcal_hi}`，kcal 侧不稳 → 整体 FAIL。
- 量具侧 OK：`a piece of` / `a cup of` 都是直给键；Cake piece=200、Manicotti cup=235 都是餐桌值。
- NIT：`a cup of Manicotti`（离散的芝士卷）不如 "a serving of manicotti" 自然（qns=cup=235，克数无差）。

### recommend

约定：模板句来自 `templates.py`（`docs/mill-query-templates.md` 冻结口径），mill 只填槽。
judge：`submit_plan` 一份 allergen-safe 且落在 `plan_windows` 内的 plan（`last_plan=[]` 哨兵）。

#### recommend.1 — one-rec-0000（seed=0, everyday, 过敏 tree_nut）— **PASS**
- query: `What should I eat for lunch?` 干净；不泄漏过敏原 / 剩余预算 / window 数字。
- 手册 "Recommend: submit_plan a safe meal that fits the windows; omit verdict" 可复现。

#### recommend.2 — one-rec-0001（seed=1, gym, 无过敏）— **PASS**
- query: `What's for dinner?` 同上，occasion=dinner 与判定窗口一致（shell=rec-dinner）。

#### recommend.3 — one-rec-0003（seed=3, everyday, 过敏 peanut+shellfish）— **PASS（带 NIT）**
- query: `What should I eat for lunch?` 本身没问题。
- NIT（batch 覆盖度，不影响本条判定）：3 条 recommend 里 2 条**逐字相同**
  （seed 0 与 seed 3 都落 `shells[seed%3]==rec-lunch`）。
  且 `_sample_recommend` 的 `rec-named-dish`（"Thinking of {dish} tonight …"，受限命名菜陷阱）
  在 seed%3==2 时才触发，但 seed=2→roster-ben 无过敏 → `_allergen_dish` 返回 None → 被拒
  （samples.json rejected: `no_allergen_dish`）。**这一形态在本批 15 条里完全没出现。**
  建议 batch 编排里让该 shell 只配有过敏原的 roster 人，或落空时换 seed 重试。

### update

约定：模板句 + `_update_from_template` 直接算 `expected` profile；judge 对 `oracle.update_band`
走 `_implicit_update_ok`（phase patch 或直接挪窗口都收）。

#### update.1 — one-upd-0000（seed=0, everyday, S0 过敏 tree_nut）— **PASS**
- query: `Add milk to my allergies.` 明确说了要加什么。未提到的字段留 S0：合理
  （Oracle = `replace(profile, allergies=normalize_tags([tree_nut, milk]))`，其余不动）。
- 手册 "Profile allergies are catalog allergen_tags (shellfish, peanut), not food names" 可复现：
  `milk` 是真实 allergen_tag。
- 软 NIT：手册举例只有 shellfish/peanut，没有奶制品 tag 的例子；理论上 agent 可能写成食物名。
  影响很小，不改判 PASS。

#### update.2 — one-upd-0001（seed=1, gym）— **PASS**
- query: `I weigh 71 kg now. Update my weight.` 与手册 "Body facts ('I weigh 70 kg now'):
  update_profile it; windows re-derive automatically" 几乎逐字对上。窗口自动重导，可复现。

#### update.3 — one-upd-0002（seed=2, gym, S0 phase=muscle）— **PASS**
- query: `I'm cutting now.` 从增肌期转 cut 是合理真实场景。
- 手册 "Spoken cutting … patch phase, or move daily energy below maintain …
  There is no published step size"；judge 走 `_implicit_update_ok`，phase patch 即可，可复现。

### composite

约定：`steps=("log","recommend")`，双 oracle（`compose_oracles`）。
`_composite_speech_spans` 按 `_REC_ASK` 切句：log 半句进 `_bind_log_foods`，recommend 半句
不得点名 pool 食物。judge 复合：任一子 oracle fail 即 fail。

#### composite.1 — one-comp-0000（seed=0, everyday）— **FAIL**
- query: `I had a cup of Burrito for lunch. What should I eat for dinner?`
- log 半句继承 log.1 的 **entailment 断裂**："a cup of Burrito" → 命不中 2708539 → log 子 oracle `log_miss`。
- 连接句自然、recommend 半句 `What should I eat for dinner?` 干净无泄漏——这部分 PASS。
- 量具侧 OK：`a cup of` → cup=120。

#### composite.2 — one-comp-0002（seed=2, gym）— **FAIL**
- query: `I had a cup of Beef for lunch. What should I eat for dinner?`
- "a cup of Beef" → 见 log.2；"Beef" 通名 + `search_foods("beef")` #1 是 Beef ground patty，
  命不中 `Beef, roast` → log 子 oracle `log_miss`。
- 另：roast beef 说成 "a cup of Beef" 自然度差（NIT）。
- recommend 半句没问题。

#### composite.3 — one-comp-0003（seed=3, everyday）— **FAIL / 自然度 FAIL**
- query: `I had a piece of Egg sandwich on griddle/pancake for lunch. What should I eat for dinner?`
- 同 log.3：`griddle/pancake` 斜杠原始描述 + `search_foods` #1 是无肉版、Oracle 是 "with meat" 版。
- recommend 半句没问题。

---

## 2. 横切发现（entailment，本次审阅的头号问题）

用**每条 query 里出现的原词**当 `q` 跑 `FoodCatalog.search`（agent 手册要求的 `search_foods {q}`）：

| query 里的说法 | Oracle food_id / 名称 | `search_foods` top-1 | Oracle 排名 |
|---|---|---|---|
| "Burrito" | 2708539 Burrito, pork, cheese | 2707343 Egg burrito | #4 |
| "Beef" | 2705847 Beef, roast | 2705855 Beef, ground, patty | #5 |
| "Cheese" | 2705715 Cheese, Fontina | 2705709 Cheese, Cheddar | 不在 top-10 |
| "Corn" | 2710046 Corn, scalloped or pudding | 2707044 Corn dog | 不在 top-10 |
| "Cake or cupcake" | 2707869 Cake or cupcake, German chocolate | 2707853 Cake or cupcake, NFS | 不在 top-10 |
| "Manicotti" | 2708776 …tomato sauce, meatless | 2708775 …no sauce | #3 |
| "Egg sandwich on griddle/pancake" | 2707333 …with meat | 2707332（无肉版） | #2 |
| "Veggie burger patty" | 2707473 …no bun | 2707473 | **#1 ✓** |

**8 个通名里 7 个 top-1 命不中 Oracle**，3 个连 top-10 都进不去。
判分是 food_id 字符串精确比（`Scorer._score_one` / `_score_verdict` / `_score_plan`），
所以这些 log / evaluate / composite 条目"照 query 写、按手册做"也拿不到 Pass。

根因链：
1. `generate_samples.py::synthetic_tracer` / `_spoken()` 取 `aliases[0] if aliases else name.split(",",1)[0]`。
2. 这批 FNDDS 食物 `aliases` 全空 → 只剩逗号前第一段。
3. FNDDS 命名法里第一段就是大类（"Beef," 下 81 行、"Cheese," 下 61 行、"Cake or cupcake," 下 27 行）。
4. `validator._validate_evaluate_verdict` 的"食物是否被提到"只查 token 出现，不查歧义；
   `validate_oracle_grams` 只校验"给定 food_id 的克数有餐桌锚点"，不校验 query→food_id。
   → 机械 gate 全过，但 `validator.py` 模块 docstring 自己写了
   *"Admitted exam items still need a human to check that the spoken query entails the scored end state."*
   —— 这次人审就是来干这个的。

对照：live 通道那条 `"two pieces of Pizza with a cup of Brussels sprouts"`（live-log.json）明显更自然，
且 live 提示词已含"不改菜名 / verbatim 餐桌措辞 / 不 title-case"。问题集中在 **synthetic 说话器**
没有对齐 live 的命名纪律，且 **catalog 对这些 FNDDS 食物缺 alias**。

---

## 3. 手册对称性（react.py v0/v1）结论

- **量具/克数侧：对称。** 15 条里所有出现的短语——`120 g` / `270 g`（explicit grams）、
  `a bowl`（→ qns，v1）、`a serving`（→ qns，v1）、`a cup` / `a piece`（v1 直给键）——
  都能被 v1 手册规则映射到 Oracle 克数。log.2 `a bowl of Beef` 即使走 fallback（piece→slice→cup），
  qns=slice=60，克数不漂。
- **食物身份侧：不对称。** 手册要求 `food_id` 从 `search_foods` 得到；上表 7/8 通名把 agent 引到别的
  food_id。这是本批唯一但致命的手册对称性破口，集中在 log / evaluate / composite。
- recommend / update 两族无手册对称性问题（模板句 + 手册对应条款齐全）。
- 附带：evaluate reject 需要**精确 reason 集**（`set` 相等）。即便食物可辨，
  `kcal_hi` / `sodium_mg_hi` 是否触发也依赖精确食物+克数——通名歧义把这层也带塌了
  （reason 数值本身按 brief 不由我判，但复现链在此断）。

---

## 4. Family 判定与理由

### log — FAIL
- log.1：`Please log 120 g of Burrito` 指不回 `Burrito, pork, cheese`（21 行同姓，`search` #4）。
- log.2：`a bowl of Beef` 指不回 `Beef, roast`（81 行同姓，`search` #5，#1 是 ground patty）。
- log.3：`Egg sandwich on griddle/pancake` 带斜杠原始描述（自然度 FAIL 级）；且 `search` #1 是无肉版，
  Oracle 是 "with meat" 版。
- 三条共有 NIT：`Please log {X} of {Y} for lunch.` 机器腔 + 食物名 title-case，违反
  `build_log_system_prompt` 自己的 Style 规则；persona 对 synthetic 文本零影响。

### evaluate — FAIL
- eval.1：`a cup of Burrito` + `a cup of Cheese` 两个通名都指不回 Oracle（Fontina 连 top-10 都不进）；
  accept 需精确 plan 匹配。
- eval.2：`a cup of Corn` 指不回 `Corn, scalloped or pudding`（连 top-10 不进）；
  `a cup of Veggie burger patty` 量具与食物打架（该食物自带 `patty` 键）。
- eval.3：`a piece of Cake or cupcake` —— FNDDS 类目名带 "or"（自然度 FAIL 级）；
  `German chocolate` 判别词丢失，`search` 连 top-10 不进；reject 需精确 `{allergy,kcal_hi}`。
- 共有 NIT：synthetic rewriter 只按"克数正好等于某餐桌项"挑短语，不管这食物是否真按杯/片来量。

### recommend — PASS
- rec.1 / rec.2 / rec.3 三条模板句自然、无 allergy / 预算 / window 泄漏，手册可复现。
- NIT（不改判）：2/3 条逐字相同；`rec-named-dish`（命名菜陷阱）形态本批缺席
  （seed=2 落到无过敏的 roster-ben 被 `no_allergen_dish` 拒）。batch 编排需修此配对。

### update — PASS
- upd.1 `Add milk to my allergies.` / upd.2 `I weigh 71 kg now. Update my weight.` /
  upd.3 `I'm cutting now.` 三条都明说要改的字段，未提字段留 S0 契约合理，均能对上 react.py 手册条款。
- 软 NIT（不改判）：手册 allergen_tag 举例无奶制品项；`milk` 实际是合法 tag，可复现。

### composite — FAIL
- comp.1 / comp.2 / comp.3 的 recommend 半句和连接句都没问题；
- 但 log 半句分别继承 log.1 / log.2 / log.3 的通名 / 斜杠问题 → log 子 oracle 必 `log_miss` → 复合 FAIL。

---

## 5. 建议（按优先级）

1. **synthetic 说话器对齐 live 命名纪律**：`_spoken()` 不能退到 `name.split(",",1)[0]`。
   至少保留到"足以在 `search_foods` 里排 #1"的判别段（"roast beef"、"scalloped corn"、
   "German chocolate cake"、"egg sandwich with meat"），或直接放弃无 alias 的 FNDDS 食物。
2. **catalog 补 alias**：给进池的 FNDDS 食物加人话 alias（像 `2706286` 那样有
   `('atlantic salmon','baked salmon','salmon')`）。没 alias 的食物不进 synthetic 池。
3. **gate 加一道 entailment 闸**：admit 前，用 query 里点名该食物的原词跑 `FoodCatalog.search`，
   要求 Oracle food_id 落在 top-K（K 小，比如 3）。这能挡住本批 7/8 条。
4. **evaluate rewriter 量具选择**：优先食物自己的 count unit（`patty`/`piece`/`slice`），
   `cup` 只留给真按杯量的食物；把 live 提示词那条 "'a cup of' only for soup/rice/beans/…" 也搬进 synthetic。
5. **FNDDS 原始串清洗**：`Egg sandwich on griddle/pancake`、`Cake or cupcake` 这类带 `/` 或 `or`
   的名字进 query 前要过一遍口语化（或直接排除）。
6. **recommend batch 覆盖**：`rec-named-dish` 只配有过敏原的 roster 人；避免 3 条里 2 条逐字重复。
7. update / recommend 两族当前形态可直接进下一轮；log / evaluate / composite 的 synthetic 产物
   在 §5.1–5.3 落地前不建议进 v2-gold 候选池。
