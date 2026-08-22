# Issue 15 批量产 Runbook（裁决后开工即用）

> **Status:** execution blueprint. Every recipe/配方 below is verified on main @ c0fce87
> (1332 passed). The only missing inputs are the main-agent design rulings listed at the end.
> 合成（--synthetic）模式全程离线、零配额；live（LLM）模式未布线 recommend/update prompt shells
> （batch-families 已知限制），因此本 runbook 的批量产以 synthetic 为默认，live 为后续。

## 配方全景（verified）

| 目标 floor/形态 | 配方 | 验证状态 |
|---|---|---|
| constrained ≥8 | composite（· log+recommend 天然） + `recommend:occasion=dinner` | recipe-open demo **9/8 达标** |
| leftover 几何 ≥24 | composite 扩量（child 双命中 leftover+constrained）；单 family `scene=leftover` 走 generate_one（batch 无 prior-log 记忆，见 recipe-channel 决策） | 5/24 起步，composite 扩量为主 |
| evaluate tier | `evaluate:tier=triple+items=3+person=...`（三食物题实证 ✓）；single/pair 同法 items=1/2；explicit_grams 加 `amount_path=explicit_grams`；synonym/long 需 tier-mapping-draft 确认词典 | triple=6 实证 |
| evaluate-unfit ≥8 | `evaluate:knife=allergy+person=<过敏人>+tier=single+items=1`：测试 catalog 证明，真实 catalog 随机 pool 需**定向 pool**（见缺口） | 仅 fixture 证明 |
| persona×过敏原 | `person=roster-cam(egg/cut)` `fay(milk)` `ben(gym)` `gus(cut)`…；混合批量 → missing_allergens=() 实证 | cam+fay+ben 覆盖实证 |
| window 无泄漏 | 全 family 天然 | ✓ |

## 分次跑法（recipe 每 family 单 dict，变体必须分次）

1. **evaluate 变体分次**：一次 `--recipe evaluate:` 只表达一个变体
   - 次1：`--recipe evaluate:tier=single --recipe evaluate:items=1 --recipe evaluate:person=roster-cam`
   - 次2：`--recipe evaluate:tier=pair --recipe evaluate:items=2 --recipe evaluate:person=roster-fay`
   - 次3：`--recipe evaluate:tier=triple --recipe evaluate:items=3 --recipe evaluate:person=roster-drew`
   - 次4（unfit）：`--recipe evaluate:knife=allergy --recipe evaluate:person=roster-cam --recipe evaluate:tier=single --recipe evaluate:items=1`（定向 pool 见缺口）
2. **推荐/复合/更新可同批**：`--recipe recommend:person=roster-fay --recipe recommend:occasion=dinner --recipe composite:person=roster-ben --recipe update:person=roster-gus`
3. 每次 `--output` 独立文件；最后 `merge` 或多次 load_split 合并验收

## 验收关卡（14 断言 + freeze）

```
recommend_coverage(personas=("everyday","cut","gym"), allergen_tags=None)
  -> missing_personas==() missing_allergens==()
evaluate_tier_coverage -> counts 各 tier >= {single:7,pair:11,triple:11,long:5,explicit_grams:4,synonym:3}
leftover_floor -> count >= 24
situation_floors -> unfit>=8 constrained>=8
window_leaks -> ()
每个 item validate_draft==[]
冻结: 分次产物 → 合并 → freeze_tasks → load_split 全往返 → validate==[]
```

## 已知缺口（需设计裁决或接受）

- **unfit 批量产**：`knife=allergy` 前置"输入板先 fit 六键窗"，真实 catalog 随机 pool 大多 reject（实测全 unresolvable）。可选解法：
  a) recipe 增 `evaluate:pool_*`（按过敏源/occasion 过滤 sample_pools，让板子大概率 fit 且含过敏载体）——新通道，一至两个 commit
  b) 用专用 fixture catalog（如测试 _knife_catalog）产 unfit，标注 synthetic-only
  c) 接受 fit-前置的过滤逻辑：unfit 由"定向 occasion/person"pool + 多 seed 重试产出（seed 扫描找可用 pool）
  裁决选哪个。
- **leftover scale**：batch 里 leftover 走 composite 扩量（composite 配额内）；24 底线需 composite 数量足够（36 配额内留足）。
- **tier 内容词典**：single/pair/triple=items 1/2/3（已实证）；explicit_grams/long/synonym 的题面词典按 tier-mapping-draft 裁决。
- **长尾 allergen**：catalog-v2 8 个标签覆盖需 person 覆盖（cam/fay/hao(peanut+shellfish)/kim(soy)/mia(tree_nut)/quin(milk)…——R10 清单）。

## 待裁决清单（沿用 issue 15 开放问题）

1. 新题替换 archive v1.0-gold 还是另开一套（新 freeze 文件）？
2. 240 内配额：log 48 / evaluate 48 / recommend 72 / update 36 / composite 36（quota_ledger 已验）。
3. tier 内容映射确认（tier-mapping-draft）。
4. unfit 的 pool 定向方案（a/b/c）。
5. live vs synthetic：runbook 默认 synthetic；LLM prompt shells 是否接线。
## Path A base landed: pool_allergen knob

`sampler.sample_pools(with_allergen=tag)` guarantees each pool contains a
carrier of the tag (swap-in on miss, deterministic per seed; unknown tags
raise). Batch recipes accept `pool_allergen` on every family
(`--recipe evaluate:pool_allergen=egg`). Status of path A
(knife=allergy+person+pool_allergen+items+tier): the carrier condition is now
satisfiable; the remaining blockers are expander plate composition (the first
N foods may include the carrier → visible `allergen_clash`) and the
fit-window precondition — both issue-15 recipe design. Details:
`reports/impl-pool-allergen.md`.

## Path A reachable: exclude_allergens knob

`evaluate:exclude_allergens=egg` (comma/space-separated tags) makes the
synthetic plate skip the person's allergen carriers, so pool_allergen +
knife=allergy completes ADR 0017's fit→knife construction end to end on the
real catalog (verified: unfit items produced for roster-cam/egg and
roster-kim/soy; acceptance ~1/15 random pools due to the fit-window residual —
details and honest rates in `reports/impl-exclude-allergens.md`). Path A is
now mechanically reachable; bulk yield tuning stays issue-15 design.
