# Borrow situation kinds; test Harness+Model via a thin runner

Foreign nutrition benches (NutriBench, NGQA, FoodBench) contribute *situation types* only—fuzzy portions, multi-item logs, condition-suitability, unit conversion. Their items, gold macros, and leaderboard metrics are not our V. Catalog remains a USDA/FNDDS snapshot. S0 is sampled by the Generator; an LLM may paraphrase the query once and the result is frozen—never used as judge.

The Runner is the only place Env, Harness, and Model meet. Env does not import a harness. Headline remains Pass rate / pass^k at a fixed env tag, not comparability with NutriBench MAE.

**Status**: accepted
