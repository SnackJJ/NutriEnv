# Issue 15 设计裁决包（给主 agent，一次拍板）

> **用途**：把分散在 `ticket-draft-new-form-items.md`、`tier-mapping-draft.md`、
> `issue15-runbook.md`、`impl-*.md` 的信息浓缩为 5 个可拍板的决策。每个问题给
> 选项 + 技术现状 + 影响 + 推荐。全部技术验证已完成（1340 passed），裁决后可直接照
> `issue15-runbook.md` 开跑。

## 裁决 1 — 新题是替换还是扩展 archive v1.0-gold？

- 背景：v1.0-gold（20 题，log+evaluate-fit only）已归档；用户已表态"gold 是归档旧产物，讨论新形态"。
- 选项：
  a) **替换**：新形态题成为新的 240 exam（v2.0-gold 之类），archive v1.0-gold 保持归档（推荐，与你的表态一致）
  b) 扩展：与 v1.0-gold 并存另一套（语义重复，不推荐）
- 影响：决定冻结产物文件名、EXAM_SPLIT_PATH 是否切换、landing_verify 是否加新 exam 分支。
- **技术现状**：EXAM_SPLIT_PATH 现在指向 v0.5-gold（240 旧考试）；新 exam 走新文件即可。

## 裁决 2 — 240 内五 family 配额

- ADR 0016 表：recommend 72 / evaluate 48 / update 36 / composite 36 = 192 → **log = 48**（240-192）。
- 注意：ticket-draft 早期写的 "log 60" 是错的（会超 240）；quota_ledger 已按 48 验证满额接受。
- 选项：确认 log 48 / evaluate 48 / recommend 72 / update 36 / composite 36（推荐）；或调整数字。
- 影响：决定每次 generate_batch 的 `--count` 分配；floors 在 evaluate/recommend 内（unfit≥8、constrained≥8、leftover≥24）。

## 裁决 3 — Evaluate tier 六档的题面内容词典

- tier 数据通道已就绪（`tier=` + recipe `evaluate:tier`，freeze 往返保留）。
- **single/pair/triple = items 1/2/3**（已实证：triple 4/4 产三食物题）。
- **explicit_grams** = `amount_path=explicit_grams`（题面说克数，gram-exact 已实证）。
- **long / synonym** 需词典裁决：
  - long：定义何为"长话术"（多从句/杂讯的 evaluate query）——需确认接受"现有陈述式 query 算 long"还是需专门 shell。
  - synonym：用别名/俗名（PB ↔ peanut butter）——依赖 catalog 别名丰富度 + near_synonym 行；需确认 alias 覆盖策略。
- 影响：决定 tier 内容配方（recipes 怎么组合）；floors 底线 single 7/pair 11/triple 11/long 5/explicit_grams 4/synonym 3。

## 裁决 4 — Evaluate-unfit 的批量参数

- 技术现状：fit→knife 构造已打通（pool_allergen + exclude_allergens + knife=allergy + person + items=2），生产路径 **~4-6/30 unfit**（occasion 调到 breakfast 更高 6/30；items 递增 yield 增）。
- 需裁决：unfit 批量用哪些参数组合达标 8？
  - 推荐：多 person × seed 累积（cam/egg、kim/soy、fay/milk、hao/shellfish…）× items=2 + occasion=dinner，多批跑到 ≥8。
  - 或接受"homework 绕行"：unfit 用确定性 fixture catalog 产 + 标注 synthetic-only。
- 影响：决定 evaluate 配额里 unfit 的 recipe 配方与批次数。

## 裁决 5 — live 还是 synthetic 批量产

- synthetic：离线、零配额、可复现（seed 固定）；**runbook 默认**；recommend/update/composite 全通过。
- live（LLM expander）：需接 recommend/update prompt shells（batch-families 已知限制，**未布线**）；耗配额；文字更真实。
- 选项：
  a) **synthetic 全量 240 + 冻结**（推荐——管线能力已全验证，冻结产物是代码定锚）
  b) live 全量（需先接线 recommend/update shells —— 一个额外 issue）
  c) synthetic 产 + live 精选替换（混合）
- 影响：决定产出过程成本与产物品多样性来源。

## 裁决后的执行路径（照 runbook）

1. 按裁决 2 配额 × 裁决 1 的文件名，分次跑各 family/recipe 变体（evaluate 变体一次一个）。
2. 合并分次产物 → 跑 14 断言全验（constrained 达标实证、unfit 生产路径 3/8 已证、tier/persona/leftover 配方路径全通）。
3. 缺口扩量（seed 累积/occasion 调优）到 floors 全达标。
4. freeze → load_split 往返 → landing_verify → 14 断言最终验收。
5. 更新 EXAM_SPLIT_PATH（如需）与 issue 14 的 4 条 checkbox。
## 裁决 1 补充调查：landing_verify 落地面无惊

`scripts/landing_verify.py` 已通用化：`main --split <path>` 与
`verify_published_exam(path)` 都对任意 split 跑 `load_exam` + `validate_draft`
+ oracle-grams。新 exam（240，ADR 0016）落地 = 传新 split 路径，**无代码改动**。
唯一硬编码：`exam_n == _EXAM_N`（240，新 exam 同数所以不用改）；
`unexpected_oracle_grams_failures` 引用 `V05_ORACLE_GRAMS_EXEMPT_IDS`（v0.5
专属豁免，新 exam 无此 ID 天然不触发）。

## 裁决 5 补充证据 + 重要简化（2026-08-23）

**合成全量成本**：36-pool composite 批量 **0.67 秒**（32 accepted，4 诚实拒绝）；
合成 240 全量预计 <5 秒——synthetic 成本可忽略（裁决 5 建议 synthetic 全量的强证据）。

**floors 大幅简化**：仅 composite 配额 36 → 32 项**全部双命中** constrained=32（≫8）
+ leftover=32（≫24），validate 0。ADR 0016 的 composite 36 一个 family 就超额满足
constrained + leftover 两个 floors → bulk 产中这两个靠 composite 配额即可，其余
family 专注 tier / persona×过敏原 / unfit。

## Review (codex)

**Verdict: REV.** The quality-gate return values are interpreted correctly,
and the default persona set matches the runbook, but catalog binding and the
round-trip check can report against a different catalog than the frozen split.
Malformed existing inputs also escape as raw tracebacks rather than a usage
failure.

### Standards

No hard AGENTS.md violation was introduced: the commit does not change catalog
grams, split data, gray-zone logic, `react.py`, or scoring semantics.

- **Low (judgment call — Divergent Change):**
  `scripts/verify_issue15.py:58` puts argument parsing, all gate policies,
  freeze/load I/O, rendering, and exit-code aggregation in one `main`; every
  added admission assertion must modify the same function. **Fix:** introduce a
  small gate-result type and focused gate functions, leaving `main` to
  orchestrate and render.
- **Low (judgment call — Mysterious Name / Middle Man):** report variables
  `rc`, `tc`, `lf`, and `sf` at `scripts/verify_issue15.py:93-118` obscure four
  different domain results, while `tests/test_verify_issue15.py:17` merely
  delegates `_run` to `verify_main`. **Fix:** use descriptive result names and
  call `verify_main` directly.

### Spec

- **High — catalog identity is neither derived nor verified**
  (`scripts/verify_issue15.py:61-72`). The default always loads catalog-v2 and
  passes that object to `load_split`, bypassing the split's recorded `catalog`
  field and SHA. `load_catalog` also silently falls back to the demo catalog
  for a missing `--catalog` path. On `v0.5-gold.json`, the default catalog
  produced 38 draft failures; its declared catalog produced zero, proving the
  result depends on the unintended override. `allergen_tags=None` correctly
  derives tags from the attached catalog, but that is the wrong catalog in
  this path. **Fix:** default to `load_split(split, catalog=None)` so the
  manifest selects the catalog, validate its recorded path/digest (or use the
  published-exam loader contract), and make an explicit override fail closed
  unless its identity matches.
- **High — freeze round-trip can PASS while the frozen manifest is invalid**
  (`scripts/verify_issue15.py:130-136`). `freeze_tasks` defaults the output
  `catalog` field to catalog-v1 while this script defaults the actual object and
  digest to catalog-v2; reloading with `catalog=catalog` bypasses that bad field
  again. Consequently the claimed “safe to ship” check never proves the file
  can resolve and verify its own catalog. **Fix:** preserve the input's verified
  catalog field and digest, then reload without injecting a catalog and compare
  the relevant task/oracle content as well as count and validation.
- **High — malformed inputs crash before the gate table**
  (`scripts/verify_issue15.py:71-72`). Existing files containing invalid JSON
  or an empty `items` list raise a raw traceback and return process code 1,
  conflating malformed usage with an evaluated gate failure. **Fix:** catch
  catalog/read/JSON/schema errors around initial loading, print one concise
  diagnostic without a traceback, and return 2.
- **Medium — the predictable temporary path is collision- and overwrite-prone**
  (`scripts/verify_issue15.py:133-134`). Two splits with the same stem, parallel
  runs, or a pre-existing file/symlink share `/tmp/verify-<stem>.gold.json`;
  `overwrite=True` clobbers it and the artifact is never cleaned up. The source
  split itself is not modified, and no repo data is written. **Fix:** use
  `TemporaryDirectory`/an exclusive temporary file and clean it in all paths.
- **Medium — round-trip equality is reduced to count plus validation**
  (`scripts/verify_issue15.py:137-139`). IDs, ordering, tiers, profiles, or
  oracle fields could change during serialization while the same number of
  individually valid tasks reload, and the gate would still PASS; the runbook's
  prior round-trip evidence explicitly included preserved IDs. **Fix:** compare
  ordered normalized task payloads (or all persistence-contract fields) before
  and after reload.
- **Medium — the smoke test only proves one aggregate failure code**
  (`tests/test_verify_issue15.py:21-46`). It never asserts stdout or an
  individual PASS row, has no rc-0 case, malformed-existing-file case, catalog
  identity case, or cleanup check. Its “clean composite” description is false
  under the actual run: captured output shows `validate_draft` and
  `freeze_round_trip` both FAIL because the script attaches catalog-v2 to the
  demo-catalog split. Any combination of broken gates can still satisfy
  `rc == 1`. **Fix:** pin named PASS/FAIL rows with captured output and add
  focused rc 0, rc 1, rc 2/malformed, manifest-catalog, and temp-cleanup cases.

### Evidence

- `tests/test_verify_issue15.py`: **1 passed**; full suite: **1341 passed**.
- `v0.5-gold.json` failed honestly on tier and unfit floors, but the default
  catalog also created spurious draft failures; using its declared catalog
  removed those draft failures.
- A synthetic composite run returned 1, but its table exposed draft and
  round-trip failures that the smoke test does not inspect. Invalid JSON and an
  empty-items split both emitted raw tracebacks. Missing paths return 2 as
  intended; argparse also retains usage exit 2.
- Commit scope is limited to the new script and test; no ADR, split, sqlite,
  scorer, validator, or quality-gates file changed.

## Fix round (codex findings)

- **High 1 — catalog identity derived + verified.** Default is now
  `load_split(split)` (manifest-selected); before any gate runs the recorded
  `catalog` file must exist and hash to the recorded `catalog_sha256`
  (demo-catalog fallback can never mask a broken manifest). An explicit
  `--catalog` override fails closed (rc 2) unless its bytes hash to the
  recorded digest. Verified: v0.5-gold now verifies against its OWN
  `data/fdc/archive/catalog.sqlite`; `--catalog catalog-v2` → clean rc 2
  "catalog identity mismatch".
- **High 2 — freeze round-trip proves the manifest.** The gate freezes with
  the input's VERIFIED `catalog_field`/`catalog_sha256`, reloads WITHOUT
  injecting a catalog (the frozen file must resolve its own), and compares
  ordered `task_to_item` payloads plus per-task validation — not just count.
- **High 3 — malformed inputs are usage failures.** JSON/schema/catalog errors
  around initial loading print one "error: cannot load split: …" diagnostic
  and return 2; no traceback reaches the terminal.
- **Medium 4** — freeze output goes to a private `TemporaryDirectory`
  (prefix verify-issue15-); cleaned on all paths; no collision-prone
  /tmp/verify-<stem> path.
- **Medium 5** — round-trip equality compares ordered normalized task
  payloads (`task_to_item`) before/after reload, alongside count and
  per-task validation.
- **Medium 6 — tests rebuilt** (tests/test_verify_issue15.py): malformed-json
  rc 2 without traceback; empty-items rc 2; manifest identity mismatch rc 2;
  named PASS/FAIL rows with captured stdout on v0.5-gold (validate_draft PASS,
  evaluate_tiers/situation_floors FAIL, RESULT: FAIL, no Traceback);
  consistent-manifest positive path (validate + freeze_round_trip PASS rows,
  temp cleanup asserted); rc-0 rendering via monkeypatched gates.
- **Low 7** — `GateResult` dataclass + focused `gate_*` functions;
  `main` parses, loads, orchestrates `run_gates`, renders.
- **Low 8** — descriptive names (`coverage`, `tier_report`,
  `leftover_report`, `floors_report`); tests call `vi.main` directly.

**v0.5-gold re-run:** validate_draft **PASS 0 issues** from its own recorded
catalog (spurious draft failures gone); evaluate_tiers FAIL, situation_floors
FAIL honestly (unfit 0/8); leftover_floor PASS 27/24; freeze_round_trip FAILs
honestly on legacy grams vs the current portion table (reported row, not a
crash); **rc 1**.
