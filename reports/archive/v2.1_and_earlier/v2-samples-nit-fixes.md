# v2 sample NIT 修复记录（round2 审阅后）

审阅：reports/cc-review-v2-samples-round2.md（§5 建议 1/2/4/6）
本文件记录已落地项。round2 判定本轮 15 条无 FAIL，故无需三轮审阅；这些改动只消除 NIT。

## 已落地

1. **entailment gate 升级 → search 排名断言**（建议 1）
   - `scripts/generate_samples.py::_query_entails_food` 不再做 token 子集检查；
     改为 `catalog.search(spoken_display_name(food), limit=1)` 的 #1 必须等于 Oracle food_id。
   - 这是审阅唯一提到的"还可能漏坏题"的机械缺口。

2. **synthetic rewriter 克数格式**（建议 4）
   - `f"{grams:g} g"`（"240 g" 而非 "240.0 g"）。

3. **共享 collision-safe tracer**（修 CLI + 重跑 15 条所需）
   - 把"避免与池内他食物撞名 + 预检 gram 可解析"的选菜逻辑抽为
     `sampler.speakable_tracer_food()`；CLI 与 sample runner 共用，消灭两处重复。
   - 额外跳过逗号头含 `with/and/plus/&` 的食物（clause binder 无法把这类头词连续放回一个 clause）。
   - 修复了 `test_synthetic_log_seed_zero_writes_task_payload` 的回归（1 failed → 全绿）。

4. **recommend 覆盖**（建议 6）
   - `_sample_recommend` 的 `rec-named-dish` 只在采样人有过敏原时进入，否则退回 occasion shell。
   - 3 条 recommend 现在都是不同 shell（lunch/dinner/breakfast）。

## 未落地（记录，等 batch/catalog 阶段）

- 建议 2：`spoken_display_name` 对 ≥3 段 FNDDS 名产出病句——留到 catalog alias 补全 / 命名停止词再调。
- 建议 3：量具贴食物（离散单位优先于 cup；unspecified 按 bowl/plate/serving）——留到 batch 前。
- 建议 5：react.py v1 手册加"search 带上 query 全部修饰词"——由 search-rank gate 兜底，可后补。
- 建议 7：保留专有名词首字母大写，低优先级。

## 验证

- `pytest -q`：1374 passed。
- `scripts/generate_samples.py --count 3`：log 3/4 · evaluate 3/18 · recommend 3/3 · update 3/3 · composite 3/5，共 15 accepted。
- 15 条 query 见 `.scratch/v2-samples/samples.json`（已含 NIT 1/2 效果："240 g"、推荐三 shell 不同）。
