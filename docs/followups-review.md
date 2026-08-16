# 三个收尾待办终审

结论：**允许提交**。互斥修饰词测试、judge gate 与 `"1 oz dry"` 修复均满足本轮设计要求；全量测试、landing 验证及指定抽查全部通过。未发现会改变冻结 split、Oracle 或判分规则的改动。

审查固定点为当前 `HEAD`（`8269cf2`），对象是工作树中的指定五个实现/测试文件；`reports/followups-report.md` 仅作为待核实声明，不作为通过证据。

## Standards 轴

未发现违反 `AGENTS.md` 硬纪律或 `pyproject.toml` 约定的阻断项。克数白名单仍来自 catalog 的 FNDDS/QNS 档位，LLM 只裁决表外候选；本次没有修改 catalog、gold、Oracle、判分规则或 agent 手册中的可解析表达。

有两个代码质量判断项：

1. `grams_gate.py::_matches_portion_table` 逐行复制了 `validator._matches_portion_table`。当前候选集合完全一致，但以后规则若只改一处会发生白名单漂移。宜在后续把候选集合抽到不依赖 draft factory 的共享模块。
2. `plausibility_gate` 与 `gray_zone_probe.run_case` 仍分别维护 K 次采样、`parse_fail` 过滤、比例和阈值判定；本轮只共享了单次 judge 调用。当前语义一致，后续仍有双处漂移风险。

其余 smell baseline 未发现值得阻断或单列的问题。

## Spec 轴

### 1. `grams_gate.py`

- 白名单集合与 `validator._matches_portion_table` 一致：遍历该食物全部数值型且非 `bool` 的 `portions` 值，乘以 `{0.5, 1, 1.5, 2}`，以两位小数匹配，并加入固定 `2 oz = round(2 × 28.35, 2) = 56.7 g`。
- 白名单路径确实不调用 judge：`plausibility_gate` 在 `_matches_portion_table(...)` 命中后立即返回 `(True, "table")`，发生在默认 judge、label 解析和采样循环之前。注入会抛异常的 judge 对 steak 160 g、omelet 55 g 均未触发。
- 表外路径默认采样 `k=5` 次；每个样本经 `judge_once(..., parse_retries=1)`，空或不可解析回复最多补调一次；有效 verdict 中 `ok` 比例 `>= threshold` 才接受，默认阈值为 `0.6`。若一个有效 verdict 都没有则拒绝。
- `judge` 可注入；未注入时使用 catalog 全名（若存在）调用默认 DeepSeek judge。请求参数确认 `model=deepseek-v4-flash`、`temperature=0.7`、`max_tokens=512`。
- 比例分母采用灰区 probe 原有语义：排除重试仍失败的 `parse_fail`，以有效 verdict 数为分母。这与改动前 `gray_zone_probe.py` 一致，但公开 gate 尚未用测试锁定“部分样本重试耗尽”的行为，见非阻断项。

### 2. `gray_zone_probe.py`

- 正常模块导入通过；`confirm_catalog()` 通过，仍确认 sandwich `175/115`、lasagna `206/250`、omelet `55/110`，仍构造 11 个 case。
- 关键运行参数不变：`K=5`、`threshold=0.6`、`PARSE_RETRIES=2`、`model=deepseek-v4-flash`、`temperature=0.7`、`max_tokens=512`。网络重试、每个样本的解析重试、有效 verdict 分母、阈值判定和 reason 提取的主路径均保持。
- 未实际发起在线 judge 调用；因此本次确认到 import、catalog guard、case 构造、共享调用路径和参数层。完整联网 probe 不是提交许可的必要条件，因为本轮 gate 的白名单会绕过报告中已知的合法档位误杀。
- 有一处非严格等价：旧 parser 只接受 JSON verdict，新共享 `parse_verdict` 还接受裸 `ok` / `suspect`。符合 prompt 的 JSON 回复行为不变，但 malformed 裸回复过去会重试、现在会直接计票。列为非阻断行为扩展。

### 3. `portions.py` 与互斥修饰词

- `_REFUSED_AFTER_UNIT` 恰为 `{dry, dried, drying, raw, uncooked, uncook}`；`resolve_portion` 只把当前已命中的单位之后的 token 切片传给 `_refuses_after_unit`，所以新增状态词拒绝不会扫描单位之前。
- 单位前缀中的这些词仍可能被既有保守数量语法当作未知 token 而返回 `None`（例如 `dry 1 oz` 在本改动前后都不可解析）；这不是 `_REFUSED_AFTER_UNIT` 引入的新误伤，也没有把状态词混入 §2.1.2 的 size-modifier 路径。
- §2.1.2 的互斥修饰词仍由单位循环之前的 `_refuses_modifiers` 处理；本次三条回归断言覆盖 `thick thin` 和 `regular thin`。单位后的状态词检查发生在单位识别之后，两条路径没有键集合或职责冲突。
- `ns-oatmeal` 的 realization `phrase` 是 `"a cup"`；`"uncooked"` 只出现在完整 query 中，因此该行仍解析为 80 g。

## 独立复算

指定解析抽查：

| 输入 | 结果 |
|---|---:|
| pasta, `1 oz dry` | `None` |
| pasta, `2 oz raw` | `None` |
| pasta, `2 oz` | `56.7` |
| pasta, `150 g chicken` | `150.0` |
| oats, `a cup` | `80.0` |

指定 gate 抽查：

| 输入 | 结果 |
|---|---|
| steak 160 g，judge 为抛异常 stub | `(True, "table")`，stub 未调用 |
| omelet 55 g，judge 为抛异常 stub | `(True, "table")`，stub 未调用 |
| steak 30 g，judge 返回 `ok` | `(True, "judge")`，恰调用 5 次 |
| 单样本先空串、后 `ok` | 重试后得到 `ok` |

命令复核：

```text
.venv/bin/python -m pytest -q
271 passed in 143.66s

.venv/bin/python scripts/landing_verify.py
gold foods: 25
old-key drifts: 0
phrase replay: 178 equal, 0 differ, 145 items unmatched/no phrase
validate_draft: 240 items, 0 failing
oz/oz_yield conflicts in FNDDS: 42; unsplitting: 0
RESULT: PASS
```

`landing_verify.py` 继续证明冻结 split 上 0 漂移。当前 follow-up 对 `portions.py` 的唯一行为新增只涉及 realization phrase 中单位后的六个状态词；207 行集合中的 `ns-oatmeal` phrase 为 `"a cup"`，不是含 `uncooked` 的完整 query。因此它不改变此前已独立验收的 `202 equal / 5 differ` 结果或 §2.4.4 的五条差异。

## 非阻断项

1. 抽取 `_matches_portion_table` 为 validator 与 gate 的单一共享实现，消除未来白名单漂移风险。
2. 为 `k <= 0`、越界 threshold、以及部分样本在重试后仍 `parse_fail` 补契约和边界测试；当前默认参数与指定路径正确。
3. 若要求 probe 字面意义上的行为完全不变，应让其继续只接受 JSON verdict，或在报告中明确裸 `ok` / `suspect` 是有意扩展。

汇总：Standards 轴 0 个阻断项、2 个判断项；Spec 轴 0 个阻断项、3 个非阻断后续项。**允许提交。**
