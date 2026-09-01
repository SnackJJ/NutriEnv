# 母语者常用食物量词 / 自然份量短语词表

> 目标：为 expander 造题提供“母语者真正会说的份量词”，避免 `a cup of pasta`、`a serving of pork` 这类量杯/编码腔。
> 信源：FNDDS `food_portion.csv`（本地 22,046 条）+ catalog-v2 份量表 + `agy-oral-portion-deepdive.md` 中的 Reddit / MFP 社区表达。

---

## 1. FNDDS 高频份量描述（已去数量词归一）

FNDDS 是膳食调查编码手册，不是全部都能直接当口语，但高频项仍能看出母语者最常用的自然单位：`cup, slice, piece, can, bottle, sandwich, egg, bar, drink, packet`。

| 出现次数 | 归一化描述 |
|---|---|
| 3164 | `N cup` |
| 939 | `N fl oz` |
| 409 | `N large` |
| 374 | `N cubic inch` |
| 310 | `N tablespoon` |
| 267 | `N small` |
| 248 | `N medium` |
| 231 | `N piece` |
| 184 | `N slice` |
| 168 | `N oz yields` |
| 166 | `N surface inch` |
| 165 | `N oz, cooked` |
| 153 | `N regular` |
| 149 | `N can` |
| 147 | `N cup, cooked, diced` |
| 136 | `N large or thick slice` |
| 131 | `N bottle` |
| 131 | `N miniature/bite size` |
| 128 | `N cup, nfs` |
| 125 | `N sandwich` |
| 112 | `N miniature` |
| 112 | `N large single serving bag` |
| 109 | `N egg` |
| 107 | `N cup, cooked` |
| 107 | `N miniature/slider` |
| 100 | `N N calorie package` |
| 96 | `N individual container` |
| 88 | `N small or thin/very thin slice` |
| 88 | `N medium or regular slice` |
| 87 | `N small single serving bag` |
| 87 | `N medium single serving bag` |
| 85 | `N slice, crust not eaten` |
| 85 | `N piece, nfs` |
| 84 | `N small/regular fillet` |
| 84 | `N large fillet` |
| 74 | `N slice, snack-size` |
| 73 | `N medium slice` |
| 72 | `fl oz of beverage` |
| 72 | `N personal size pizza` |
| 71 | `N whole fish, any size` |
| 70 | `N drink` |
| 68 | `N pouch` |
| 68 | `guideline amount on regular sandwich` |
| 65 | `N package` |
| 63 | `N whole` |

---

## 2. 口语自然度 vs resolver 可解析性映射

我们的约束：`resolve_portion` 只认 `cup / tbsp / tsp / slice / piece / can / fl_oz / serving(portion/bowl/plate/order) / thick / thin / regular`，外加“食物名自带 dish noun”（sandwich/burger/taco/burrito/soup/salad/pizza...）和 bare food noun 按 `piece` 计数。

因此把母语者常说、且 resolver 能解析的单位分四类：

### A. 体积/容器类
- `cup`：适合米、豆、蔬菜、燕麦、酸奶、汤、饮料、果泥等“真的会用杯/碗计”的食物。
- `bowl`：适合 `soup / stew / ramen / pho / cereal / oatmeal / salad / pasta` 等碗装食物。
- `plate`：适合 `pasta / salad / casserole / curry / stir-fry` 等盘装混合菜。
- `fl oz`：适合饮料、咖啡、酒、奶。

### B. 可数食物件
- `piece`：适合鸡块、肉丸、寿司、糖果、口香糖等“按个/块”的食物。
- `slice`：适合 `pizza / bread / cheese / cake / pie` 等切片食物。
- `can`：适合罐头食品、听装饮料。
- `egg / sandwich / burger / taco / burrito / wrap / sub`：食物名自带 dish noun，口语直接说 `two eggs`、`a turkey sandwich`，resolver 按 default serving 解析。

### C. 份量兜底
- `serving`：万金油但最机械，只在没有更自然词时用。
- `order`：适合 `fries / onion rings / nachos` 等外食“一份”语境。
- `bowl / plate` 也可作为 default serving 的同义自然说法。

### D. 母语者常说但 resolver 目前不认（暂不放进题面）
- `glass of wine`、`mug of coffee`、`bottle of beer`、`handful of nuts`、`fist-sized sweet potato`、`palm-sized salmon`、`deck-of-cards steak`、`dollop of sour cream`、`splash of milk`、`drizzle of oil`。
- 这些更适合未来做 SFT / 真实语料压力测试，或扩展 resolver 的 hand-gesture 与容器同义词。

---

## 3. 社区语料中最高频的自然量词短语

来自 `agy-oral-portion-deepdive.md` 第 3 节：

- `a cup of` / `a bowl of` / `a plate of`
- `two slices of` / `a thick slice of` / `half an avocado`
- `a handful of` / `a small handful of` / `a generous handful of`
- `a scoop of`（蛋白粉、冰淇淋）
- `a dollop of`（酸奶油、酸奶、果酱）
- `a splash of`（牛奶、醋汁）
- `a drizzle of`（蜂蜜、糖浆、橄榄油）
- `a pat of`（黄油）
- `half a bag of` / `a side of` / `an order of`（薯条、洋葱圈）
- `palm-sized` / `fist-sized` / `deck-of-cards-sized`（肉、红薯）

---

## 4. 落到 expander 的最小改造

在 `build_user_prompt` 中，按食物名关键词给每个食物追加“自然口语份量提示”：

- `pasta / noodle / soup / stew / chili / curry / casserole / salad / cereal / oatmeal / grits` → 追加 `a bowl = <qns>g`、`a plate = <qns>g`
- `sandwich / burger / taco / burrito / wrap / sub` → 追加 `a <noun> = <qns>g`
- `fries / onion ring / nachos / tater tot` → 追加 `an order = <qns>g`
- 其他食物维持 `cup / slice / piece / serving` 优先，不强行塞 bowl/plate。

这样生成时模型看到的是“这些口语单位都等价、都可解析”，而不是只能从 `a cup` 和 `a serving` 里二选一。

---

*数据源：`data/fdc/raw/survey.zip` food_portion.csv；生成时间：2026-08-23*
