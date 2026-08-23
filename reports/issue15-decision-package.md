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

## Re-review (codex)

**Verdict: REV.** Six findings are resolved. The two catalog-identity Highs
are only partially fixed and still admit false verification paths.

### Standards

No documented-standard violation or new material code smell was found. The two
prior Low structure/name findings are resolved: `GateResult`, `LoadedSplit`,
focused `gate_*` functions, `run_gates`, and `render` leave `main` as the CLI
orchestrator; result variables are descriptive and the test middle-man is gone.

### Spec status

| # | Prior finding | Status | Evidence / remaining fix |
|---|---|---|---|
| 1 | High — catalog identity | **Not resolved** | The normal manifest path correctly verifies v0.5's recorded catalog and removes all spurious draft failures. However, `scripts/verify_issue15.py:114-128` accepts an explicit override when `catalog_sha256` is missing/non-string, because comparison is conditional on `isinstance(sha, str)`. Both branches also accept an existing non-`.sqlite` file; `load_catalog` then silently substitutes the 15-food demo catalog. Reproduced: a no-SHA v0.5 copy plus its explicit catalog loaded 240 tasks, and a hash-matched `catalog.txt` manifest loaded 240 tasks against the demo catalog. **Fix:** require a valid recorded SHA for overrides, require `.sqlite` on both paths, and use a strict loader that cannot fall back. |
| 2 | High — round-trip manifest identity | **Not resolved** | `gate_freeze_round_trip` preserves the input catalog fields and reloads without injection, but `load_split` does not verify `catalog_sha256`. I changed the output catalog field to a byte-different SQLite copy with identical food rows while leaving the old SHA; `scripts/verify_issue15.py:225-240` returned `PASS` with `content identical=True, validate clean=True`. **Fix:** reload the temporary output through `_load_verified(_path, None)` (or an equivalent manifest-identity verifier), then compare its tasks. |
| 3 | High — malformed input diagnostics | **Resolved** | Invalid JSON and empty items produce one concise `error:` line, rc 2, and no traceback. |
| 4 | Medium — temporary-file safety | **Resolved** | `TemporaryDirectory` provides an exclusive path and cleanup on success and exception paths; the positive test pins cleanup. |
| 5 | Medium — content equality | **Resolved** | Ordered normalized `task_to_item` payloads cover IDs, tiers, profiles, and oracles, alongside post-reload validation. This does not replace the still-missing manifest SHA check in finding 2. |
| 6 | Medium — smoke-test quality | **Resolved** | Seven tests now pin named PASS/FAIL rows, rc 0/1/2 behavior, malformed/schema diagnostics, input-manifest mismatch, positive content round-trip, and temp cleanup. Coverage should additionally pin the two fail-open catalog cases above and a byte-level output-manifest tamper. |
| 7 | Low — monolithic gate runner | **Resolved** | `GateResult` plus focused gate functions separate policy checks from orchestration and rendering. |
| 8 | Low — names/test middle-man | **Resolved** | Descriptive report names replaced `rc/tc/lf/sf`; tests call `vi.main` directly. |

No independent new production finding was introduced; the missing negative
tests are coverage gaps for the two unresolved High findings.

### Evidence

- `tests/test_verify_issue15.py`: **7 passed**; full suite: **1347 passed**.
- `v0.5-gold.json`: `validate_draft` PASS, tier and unfit floors FAIL honestly,
  rc 1.
- Malformed JSON and empty-items probes: concise rc 2, no traceback.
- Scope remains report + script + test only; no ADR, split, sqlite, scorer,
  validator, or quality-gates change.

Summary by review axis: **Standards 0 open (worst: none); Spec 2 open Highs
(catalog identity and round-trip manifest verification).**

## Fix round 2 (codex findings)

- **High 1 — override identity no longer fail-open.** An explicit
  `--catalog` is only verifiable when the split records a string
  `catalog_sha256`; without one the override is refused ("split records no
  catalog_sha256…", rc 2). Both catalog paths (override and manifest) must be
  `*.sqlite` (`_require_sqlite`), and existence+extension are validated before
  any `load_catalog` call, so the demo-fixture fallback is unreachable.
  Tests: `test_override_without_recorded_sha_is_refused`,
  `test_non_sqlite_catalog_is_refused` (override and manifest branches).
- **High 2 — round-trip verifies the frozen manifest's identity.**
  `gate_freeze_round_trip` now reloads the temporary output through the same
  strict verifier (`_load_verified(_path, None)`): the output's recorded sha
  must match its recorded catalog file's bytes, or the gate returns FAIL with
  "sha256 mismatch" in its evidence. Tests:
  `test_round_trip_fails_when_output_manifest_sha_is_broken`
  (byte-different sqlite copy + old sha → gate FAIL row / loader refusal),
  `test_tampered_split_manifest_is_refused_at_entry` (tampered input → rc 2,
  clean diagnostic — fail-closed at both layers).
```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1351 passed in 52.39s        # 0 failed (was 1347; +4 tests)
```

## Final re-review (codex)

**FINAL verdict: REV.** Both remaining catalog-identity High findings are
resolved, but the stricter loader exposes one uncaught malformed-catalog path
that still violates the tool's rc-2/no-traceback contract.

### Standards

No documented AGENTS.md violation or production-code smell was introduced.
One non-blocking test-quality judgment remains: the name
`test_round_trip_fails_when_output_manifest_sha_is_broken`
(`tests/test_verify_issue15.py:269`) overstates what it asserts. It invokes
`gate_freeze_round_trip` only before tampering and asserts PASS; after tampering
it calls `_load_verified` directly, then ends after a comment claiming a
`main` check that is not present. **Fix:** inject the tampered manifest into the
gate (for example by monkeypatching `freeze_tasks`) and assert a failed
`GateResult` with SHA-mismatch evidence, or rename the test to its narrower
loader contract.

### Spec status

| # | Finding | Final status | Evidence |
|---|---|---|---|
| 1 | High — catalog override identity | **Resolved** | A non-empty recorded string SHA is now mandatory for overrides; both manifest and override paths require an existing `.sqlite` before loading. No-SHA override and hash-matched `catalog.txt` probes return concise rc 2. |
| 2 | High — round-trip manifest SHA | **Resolved** | The temp output reloads through `_load_verified(_path, None)`. A byte-different SQLite copy with identical food rows plus the old SHA returns `GateResult(passed=False)` with a SHA-mismatch diagnostic. |
| 3 | High — malformed JSON/empty items | **Resolved for the pinned cases** | Invalid JSON and empty items still return concise rc 2 without traceback. See the new malformed-catalog finding below. |
| 4 | Medium — temp safety | **Resolved** | Private `TemporaryDirectory`, cleanup retained. |
| 5 | Medium — content equality | **Resolved** | Ordered normalized payload comparison retained after verified reload. |
| 6 | Medium — smoke coverage | **Resolved, with the Low test nit above** | Eleven tests cover the intended rc and catalog cases; the named gate-tamper test itself should be strengthened. |
| 7 | Low — gate structure | **Resolved** | Focused gate functions and orchestration remain intact. |
| 8 | Low — names/middle-man | **Resolved** | Descriptive production names and direct `vi.main` test calls remain intact. |

### New finding

- **Medium — a corrupt `*.sqlite` catalog still crashes with a raw traceback**
  (`scripts/verify_issue15.py:161`, `scripts/verify_issue15.py:312-316`).
  `_require_sqlite` verifies only the suffix; a manifest whose SHA correctly
  matches an invalid SQLite file reaches `load_catalog`, which raises
  `sqlite3.DatabaseError`. `main` does not catch `sqlite3.Error`, so it emits a
  traceback/process rc 1 instead of the promised concise usage diagnostic and
  rc 2. Reproduced with a file containing `not a sqlite database` and its exact
  recorded SHA. **Fix:** catch `sqlite3.Error` in the initial-load error path
  (or translate it inside the strict catalog loader) and add a corrupt-SQLite
  rc-2/no-traceback regression test.

### Evidence

- Targeted: **11 passed**. Full suite: **1351 passed**.
- v0.5-gold remains honest: `validate_draft` PASS; tier/unfit floors FAIL;
  rc 1.
- Commit scope is report + script + test only; no ADR, split, sqlite, scorer,
  validator, or quality-gates change.

Summary by review axis: **Standards 1 non-blocking Low (test naming/coverage);
Spec 1 new Medium blocker (corrupt SQLite diagnostic path).**

## Fix round 3

- **Medium — corrupt *.sqlite no longer crashes.** The initial-load error path
  now also catches `sqlite3.Error`: a manifest whose SHA matches a non-SQLite
  file produces the concise "error: cannot load split: file is not a database"
  diagnostic and rc 2, no traceback. Regression:
  `test_corrupt_sqlite_catalog_returns_2_without_traceback` (hand-built
  payload + matching SHA over a text body; live probe reproduced: rc 2).
- **Low — tamper test strengthened.**
  `test_round_trip_fails_when_output_manifest_sha_is_broken` now injects the
  broken manifest INTO the gate via a `freeze_tasks` wrapper that rewrites the
  temp output's catalog field (keeping the old sha) and asserts a failed
  `GateResult` with "sha256 mismatch" evidence; through `main` it surfaces as
  the FAIL freeze_round_trip row with rc 1. The narrow `_load_verified`
  side-door assertion was removed.
```
$ .venv/bin/python -m pytest -q
........................................................................ [100%]
1352 passed in 52.65s        # 0 failed (was 1351; +1 test)
```

## Final verdict (codex)

**FINAL verdict: ACC.** Both round-3 findings are resolved; no correctness or
release blocker remains.

### Standards

No documented AGENTS.md violation or production-code smell was introduced.
The prior misleading tamper test is substantively corrected: it now injects a
broken catalog reference through a monkeypatched `freeze_tasks` wrapper and
asserts that `gate_freeze_round_trip` returns failure with SHA-mismatch
evidence.

Two optional test-cleanup judgments do not affect release: the additional
`_load_verified` special case for `V05_GOLD` in the CLI portion of that test is
unnecessary (the valid generated split could be passed directly), and stdout
capture boilerplate remains duplicated across negative tests. The tamper-test
docstring also says it pins corrupt-SQLite handling, although the following
dedicated test owns that assertion.

### Spec

| Finding | Status | Evidence |
|---|---|---|
| Medium — corrupt SQLite traceback | **Resolved** | `scripts/verify_issue15.py:312-324` catches `sqlite3.Error` in the initial-load path. A hash-matching corrupt `.sqlite` probe returned rc 2 with `error: cannot load split: file is not a database` and no traceback; the dedicated regression pins it. |
| Low — tamper test bypassed the gate | **Resolved** | `tests/test_verify_issue15.py:269` monkeypatches `freeze_tasks`, rewrites the gate's temporary manifest to reference a byte-different SQLite catalog while retaining the old SHA, and asserts both a failed `GateResult` with SHA-mismatch evidence and the CLI FAIL row/rc 1. |

No new spec or production finding was found. v0.5-gold remains honest:
`validate_draft` PASS, evaluate-tier and unfit floors FAIL, rc 1.

### Evidence

- Targeted: **12 passed**.
- Full suite: **1352 passed**, 0 failed.
- Commit scope is report + script + test only; no ADR, split, sqlite, scorer,
  validator, or quality-gates change.

Summary by review axis: **Standards pass (optional test cleanup only); Spec
pass (0 open findings).**

verify_issue15.py admission gate released.
