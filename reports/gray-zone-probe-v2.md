# judge 灰区重验 v2 — 冻结前置探针（硬纪律 3）

> 配套：`reports/gray-zone-probe-v1.md`（Phase 3 封 gate 的记录）、
> `docs/agent-orchestration.md` 纪律 3、issue 09 的 freeze-blocker 记录
> （"`reports/gray-zone-probe-v2.md` 必须在任何冻结之前存在"）。

## 目的

issue 09 收尾时冻结前置项：在 **合并后 main** 上，对 live `grams_gate`
路径重跑 three staple first-wins anchors —— **chicken-piece-105 /
tuna-can-75 / beef-piece-65** —— 并在同一轮确认灰区三对（sandwich 1.5× /
lasagna 1.2× / omelet 2.0×）与荒谬/正常对照。这验证 issue 09 的 review
harness 结构调整没有破坏 grams gate 的判分路径。

## 运行

```
.venv/bin/python scripts/gray_zone_probe.py     # exit 0 = gate safe
```

- 模型：`deepseek-v4-flash-0731`（DashScope 端点，K=5、threshold=0.6、
  temp=0.7、max_tokens=512，合同未改）
- catalog：`data/fdc/catalog-v2.sqlite`
- 主 checkout @ `6039070`（ship-09/ship-10 合并后 + ADR 注记 + quality_gates 镜像）

## 脚本修复（本轮）

`scripts/gray_zone_probe.py` 的 `main()` 打印循环假设每个 confirmed 条目
都有 `piece/qns/ratio` 键，但 staple anchors（chicken/tuna/beef）存的是
`key/grams` 键 —— 探针在 judge 前 `KeyError: 'piece'` 崩溃（第一次运行发现）。
已修复打印分支（staple 用 `key=grams` 行打印），`build_cases` 与
`confirm_catalog` 的 staple 逻辑本就正确未动。

## 结果（2026-08-22，live judge）

| 用例 | 克数 | ok_frac | 判定 | 对/错 |
|---|---:|---:|---|---|
| sandwich-piece-175 | 175 | 1.00 | 接受 | ✓ |
| sandwich-qns-115 | 115 | 1.00 | 接受 | ✓ |
| lasagna-piece-206 | 206 | 1.00 | 接受 | ✓ |
| lasagna-qns-250 | 250 | 1.00 | 接受 | ✓ |
| omelet-piece-55 | 55 | 1.00 | 接受 | ✓ |
| omelet-qns-110 | 110 | 1.00 | 接受 | ✓ |
| **chicken-piece-105** | 105 | 1.00 | 接受 | ✓ |
| **tuna-can-75** | 75 | 1.00 | 接受 | ✓ |
| **beef-piece-65** | 65 | 1.00 | 接受 | ✓ |
| ctrl-steak-030 | 30 | 0.00 | 拒绝 | ✓ |
| ctrl-banana-010 | 10 | 0.00 | 拒绝 | ✓ |
| ctrl-oil-100 | 100 | 0.00 | 拒绝 | ✓ |
| ctrl-steak-160 | 160 | 1.00 | 接受 | ✓ |
| ctrl-banana-126 | 126 | 1.00 | 接受 | ✓ |

灰区 **9/9 接受**（含三对 staple anchors）、荒谬 **3/3 拒绝**、正常 **2/2
接受**；`parse_fail` = 0。`omelet-piece-55` 本轮 `ok_frac=1.00`（v1 时为
0.80——5 次采样全过，分布符合预期）。`reason` 样本均判为"typical
single-serving portion"，与 ground truth 一致。

## 结论：GATE_SAFE，冻结前置项满足

`grams_gate` 在合并后 main 上对全部合法 FNDDS 灰区值（含 issue 09
freeze-blocker 的 chicken/tuna/beef 三对）接受，对荒谬值拒绝，对正常对照
接受。issue 09 的冻结前置条件（`reports/gray-zone-probe-v2.md` 存在且
覆盖 chicken-piece-105 / tuna-can-75 / beef-piece-65、在 live `grams_gate`
路径上跑）**满足**。可进入冻结流程。