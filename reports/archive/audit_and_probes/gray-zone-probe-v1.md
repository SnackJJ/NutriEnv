# judge 灰区重验（v1.0 / issue 08）

Phase 3 封 gate 条件（`reports/v1.0-candidate-pipeline-roadmap.md`；
`docs/agent-orchestration.md` 纪律 2）：judge 默认模型换成
`deepseek-v4-flash-0731` 后，灰区三对必须过 ground truth。

复跑：

```
.venv/bin/python scripts/gray_zone_probe.py
```

失败（任一 ground truth 不成立）以非零退出。阈值与采样合同未改：
K=5、threshold=0.6、temp=0.7、`max_tokens=512`。

历史对照（旧默认 `deepseek-v4-flash`，omelet-piece-55 误杀 0.40）见
`reports/gray-zone-probe.md`。

## 0. 模型可用性

`deepseek-v4-flash-0731` **不是** `api.deepseek.com` 的合法 id。实测：

| 端点 | 模型 | 结果 |
|---|---|---|
| DeepSeek `api.deepseek.com` | `deepseek-v4-flash-0731` | HTTP 400 `invalid_request_error`（仅支持 `deepseek-v4-flash` / `deepseek-v4-pro`） |
| DeepSeek `api.deepseek.com` | `deepseek-v4-flash` | OK（旧默认） |
| DashScope 北京 | `deepseek-v4-flash-0731` | OK |
| DashScope 北京 | `qwen3.7-flash-2026-07-15` | OK（可注入备用） |

因此 `call_judge` 对默认模型走 DashScope + `DASHSCOPE_API_KEY`。旧官方 id
（`deepseek-v4-flash` 等）仍走 DeepSeek，供回退对照。未改 K / threshold。

## 1. 本次运行

| 项 | 值 |
|---|---|
| 日期 | 2026-08-17 |
| 模型 | `deepseek-v4-flash-0731`（DashScope） |
| catalog | `data/fdc/catalog-v1.sqlite` |
| K / threshold / temp / max_tokens | 5 / 0.6 / 0.7 / 512 |
| parse_fail | 0 |
| 脚本退出码 | 0 |

catalog-v1 三对与文档一致：sandwich 175/115（1.52×）、lasagna 206/250（1.21×）、
omelet 55/110（2.00×）。

## 2. 结果

| 用例 | 食物 | 克数 | 来源档位 | ok 比例 | 判定 | 对/错 | 旧模型 ok（flash） |
|---|---|---:|---|---:|---|---|---:|
| sandwich-piece-175 | sandwich | 175 | FNDDS piece（fdc 2706880） | 1.00 | 接受 | ✓ | 1.00 |
| sandwich-qns-115 | sandwich | 115 | FNDDS qns（fdc 2706880） | 1.00 | 接受 | ✓ | 1.00 |
| lasagna-piece-206 | lasagna | 206 | FNDDS piece（fdc 2708750） | 1.00 | 接受 | ✓ | 1.00 |
| lasagna-qns-250 | lasagna | 250 | FNDDS qns（fdc 2708750） | 1.00 | 接受 | ✓ | 1.00 |
| omelet-piece-55 | omelet | 55 | FNDDS piece（fdc 2707198） | **0.80** | 接受 | ✓ | **0.40 误杀** |
| omelet-qns-110 | omelet | 110 | FNDDS qns（fdc 2707198） | 1.00 | 接受 | ✓ | 1.00 |
| ctrl-steak-030 | steak (beef) | 30 | 15/15 荒谬对照 | 0.00 | 拒绝 | ✓ | 0.00 |
| ctrl-banana-010 | banana | 10 | 15/15 荒谬对照 | 0.00 | 拒绝 | ✓ | 0.00 |
| ctrl-oil-100 | olive oil | 100 | 15/15 荒谬对照 | 0.00 | 拒绝 | ✓ | 0.00 |
| ctrl-steak-160 | steak (beef) | 160 | 15/15 正常对照 | 1.00 | 接受 | ✓ | 1.00 |
| ctrl-banana-126 | banana | 126 | 15/15 正常对照 | 1.00 | 接受 | ✓ | 1.00 |

灰区 6/6 接受；荒谬对照 3/3 拒绝；正常对照 2/2 接受。

`omelet-piece-55` 样本：4× ok / 1× suspect。ok 理由：「55 g is roughly a
small one-egg omelet, small but still a plausible real portion.」

## 3. 结论：GATE CLOSED

书面标准全部成立：

- 灰区 6 个合法档位 `ok_frac ≥ 0.6`（含 omelet 55g，新模型 0.80，不再误杀）
- 荒谬对照 3 个 `ok_frac < 0.6`（全 0.00）
- 正常对照 2 个接受（全 1.00）

未改阈值、未回退模型。旧模型对照数字来自历史报告，本轮未再花预算重跑
`deepseek-v4-flash`（新模型已过 gate，回退条款不触发）。

## 4. 端点已统一 DashScope（2026-08-17）

`deepseek-v4-flash-0731` 经百炼重验灰区三对 → **全过**。

流水线（expander 注册 id / `call_judge` / review `_route`）不再走
`api.deepseek.com`。judge 默认仍是 `deepseek-v4-flash-0731`，只改端点。
未改 K / threshold / 模型。`NUTRIENV_JUDGE_MODEL` 只换模型 id，端点一律
DashScope。

复跑：`.venv/bin/python scripts/gray_zone_probe.py`（2026-08-18，exit 0）。

| 用例 | 克数 | ok 比例 | 判定 | 对/错 |
|---|---:|---:|---|---|
| sandwich-piece-175 | 175 | 1.00 | 接受 | ✓ |
| sandwich-qns-115 | 115 | 1.00 | 接受 | ✓ |
| lasagna-piece-206 | 206 | 1.00 | 接受 | ✓ |
| lasagna-qns-250 | 250 | 1.00 | 接受 | ✓ |
| omelet-piece-55 | 55 | **0.80** | 接受 | ✓ |
| omelet-qns-110 | 110 | 1.00 | 接受 | ✓ |
| ctrl-steak-030 | 30 | 0.00 | 拒绝 | ✓ |
| ctrl-banana-010 | 10 | 0.00 | 拒绝 | ✓ |
| ctrl-oil-100 | 100 | 0.00 | 拒绝 | ✓ |
| ctrl-steak-160 | 160 | 1.00 | 接受 | ✓ |
| ctrl-banana-126 | 126 | 1.00 | 接受 | ✓ |

灰区 6/6 接受（均 `ok_frac ≥ 0.6`）；荒谬对照 3/3 拒绝；正常对照 2/2 接受；
`parse_fail` = 0。`omelet-piece-55` 仍是 4× ok / 1× suspect（0.80），与
§2 同分布。GATE_SAFE，无需裁决。
