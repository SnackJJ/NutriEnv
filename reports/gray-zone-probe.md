# judge 灰区用例实验

judge 封 gate 的前置验证（`docs/llm-generated-exam-data.md` 第 3 节；
`docs/adjudication-report.md` 验收清单第 7 条）。

复跑：

```
.venv/bin/python scripts/gray_zone_probe.py
```

模型 `deepseek-v4-flash`，每用例独立调用 K=5、temp 0.7，`ok` 比例 ≥ 0.6 判接受。
judge prompt 复用 `scripts/portion_judge_probe.py` 的 `JUDGE_SYSTEM`
（问的是「是否 plausible 的真实份量」，不是「是否等于 QNS」）。
`max_tokens=512`（见第 5 节）。未改任何生产代码。

## 1. catalog 实测（设计用例前核对）

`.venv/bin/python` + `load_catalog(data/fdc/catalog.sqlite)`：

| 食物 | fdc_id | catalog name | piece | qns | 比值 |
|---|---|---|---:|---:|---|
| sandwich | 2706880 | Sandwich, NFS | 175 | 115 | 1.52×（文档 1.5×） |
| lasagna | 2708750 | Lasagna with meat | 206 | 250 | 1.21×（文档 1.2×） |
| omelet | 2707198 | Egg omelet or scrambled egg, NS as to fat | 55 | 110 | 2.00×（文档 2.0×） |

三对与 claude 给出的灰区值一致。六个数字都是 catalog 里已有的 FNDDS 档位，不是错误值。

## 2. 用例

| 组 | 作用 |
|---|---|
| 灰区 6 个 | 合法档位值，judge **不得误杀**（`ok_frac ≥ 0.6`） |
| 荒谬对照 3 个 | 15/15 已知应拒：30g steak、10g banana、100g olive oil |
| 正常对照 2 个 | 15/15 已知应接受：160g steak、126g banana |

## 3. 结果

| 用例 | 食物 | 克数 | 来源档位 | ok 比例 | 判定 | 对/错 |
|---|---|---:|---|---:|---|---|
| sandwich-piece-175 | sandwich | 175 | FNDDS piece（fdc 2706880） | 1.00 | 接受 | ✓ |
| sandwich-qns-115 | sandwich | 115 | FNDDS qns（fdc 2706880） | 1.00 | 接受 | ✓ |
| lasagna-piece-206 | lasagna | 206 | FNDDS piece（fdc 2708750） | 1.00 | 接受 | ✓ |
| lasagna-qns-250 | lasagna | 250 | FNDDS qns（fdc 2708750） | 1.00 | 接受 | ✓ |
| omelet-piece-55 | omelet | 55 | FNDDS piece（fdc 2707198） | **0.40** | **拒绝** | **误杀** |
| omelet-qns-110 | omelet | 110 | FNDDS qns（fdc 2707198） | 1.00 | 接受 | ✓ |
| ctrl-steak-030 | steak (beef) | 30 | 15/15 荒谬对照（slice/piece=30，QNS=160） | 0.00 | 拒绝 | ✓ |
| ctrl-banana-010 | banana | 10 | 15/15 荒谬对照（piece/QNS=126） | 0.00 | 拒绝 | ✓ |
| ctrl-oil-100 | olive oil | 100 | 15/15 荒谬对照（约 7 tbsp） | 0.00 | 拒绝 | ✓ |
| ctrl-steak-160 | steak (beef) | 160 | 15/15 正常对照（QNS=160） | 1.00 | 接受 | ✓ |
| ctrl-banana-126 | banana | 126 | 15/15 正常对照（piece/QNS=126） | 1.00 | 接受 | ✓ |

灰区 5/6 接受；荒谬对照 3/3 拒绝；正常对照 2/2 接受。本轮 0 次 parse_fail。

误杀样本理由（3× suspect / 2× ok）：

- suspect：「55 g of omelet is a very small piece, more like a bite than a real meal portion.」
- ok：「A small one-egg omelet can weigh about 55g, which is a plausible portion.」

judge 把口语「omelet」理解成 2 蛋菜（对齐 QNS=110），把 FNDDS 的 piece=55（一颗蛋的炒蛋/蛋饼）看成半份。

## 4. 结论：gate 需调整，不能按 0.6 原样封

封 gate 的书面标准是：灰区 6 个合法档位值全部 `ok_frac ≥ 0.6`，且荒谬对照全部 `< 0.6`。
第二条过了，第一条没过——**`omelet-piece-55` 被误杀（0.40）**。

judge 作为「荒谬值过滤器」在 1.2× / 1.5× 安全（sandwich、lasagna 两侧都是 5/5 ok），
在 2.0× 的 omelet piece 上会否决一个合法 FNDDS 档位。不能把当前阈值直接封进流水线。

### 建议（按优先级）

1. **白名单 FNDDS 表值（主建议）**。克数若等于该食物 catalog 里某个档位
   （`piece` / `qns` / `cup` / `slice` / …），直接接受，不送 judge。
   judge 只过滤 LLM 发明的、表上没有的克数。这与铁律一致：
   克数锚点 = FNDDS 表值 / QNS，LLM 产出永远是候选，不是事实。
   omelet 55g 是表值，不该被常识否决。
2. **不要把阈值降到 0.4 来救这一例**。15/15 里最接近的荒谬值是 steak-500g
   （ok_frac=0.20）。0.40 与 0.20 只差一次采样，门槛会变得很薄。
   本例 3/5 suspect 是稳定的常识冲突，不是噪声。
3. **若必须让 judge 看表值**：日记里的食物名用 catalog 全名
   （`Egg omelet or scrambled egg`），不要只用「omelet」。这是补丁，不是架构。

误杀的代价按主文档是丢多样性、不会写错 Oracle。即便如此，gate 若会否决
合法档位，造题流水线会把 piece=55 的 omelet 题丢掉。白名单比降阈值干净。

## 5. 与 15/15 实验的关系

`scripts/portion_judge_probe.py` 的 15/15 全中，判别间隙干净（bad 0.00–0.20，
good 0.80–1.00）。那组全是极端对照（5.3×–12.6×）：steak 30 vs 160、banana 10 vs 126、
oil 14 vs 100。它证明 judge **能挡住明显荒谬值**，不能外推到 1.2–2.0×。

本组把那条外推补上了：

- 1.2×（lasagna 206/250）和 1.5×（sandwich 175/115）：两侧都是合法档位，judge 全接受——
  它不会在两个合法键之间做选择，这正是「过滤器」该有的行为。
- 2.0×（omelet 55 vs 110）：QNS 侧稳过，piece 侧误杀。15/15 的「间隙干净」在灰区
  不再成立；唯一掉进 0.40 的就是这一档。
- 极端对照与 15/15 逐条复现（30g steak / 10g banana / 100g oil 全 0.00；
  160g steak / 126g banana 全 1.00）。过滤器在极端端没有回退。

15/15 仍然有效，范围就是「极端荒谬」。灰区实验把它的证明范围收在该收的地方，
并标出封 gate 前必须先做的白名单（或等价策略）。

## 6. `max_tokens` 协议备注

`deepseek-v4-flash` 先把 completion 花在 `reasoning_content` 上。
15/15 脚本的 `max_tokens=120` 对极端用例够用；灰区思考更长，会 `finish_reason=length`、
正文为空。初次按 120 跑时，`omelet-piece-55` 和 `ctrl-oil-100` 的 5 次调用都是空串，
被算成 `ok_frac=0.00`——那是协议截断，不是 verdict。

本报告数字全部来自 `max_tokens=512` 的重跑（空回复会重试，本轮未触发）。
封 gate 时应用 512，不要沿用 15/15 的 120。
