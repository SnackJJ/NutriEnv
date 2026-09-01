# Handoff — ship-04 收尾（2026-08-20）

一句话：**04 已全部落地，两个缺陷已修，测试从 436s 降到 63s；四件事等你拍板。**

`main` = `ffa2bb3`。工作树 `~/.herdr/worktrees/nutri-env/ship-04` 已删除。

---

## 1. main 上落了什么

| merge | 内容 |
|---|---|
| `3966879` | ship-04 — Mifflin×PAL 窗口、`phase`、ADR 0015 implicit Update bands |
| `7b5961d` | ship-04-fix — fatigue band 两个缺陷 + catalog 扫描成本 |
| `ffa2bb3` | ship-04-fix (2) — 漏掉的四处扫描 |

`.scratch/.../issues/04-window-rederive-update-bands.md` 已标 `Status: done`。

## 2. 修掉的两个缺陷（04 自带测试没抓到）

**(a) fatigue oracle 过不了 freeze → load 往返。**
`scorer.py` 把 `oracle.profile.windows` 当 S0 基线用，但 `split.py` 在 oracle 提到 phase 时会重导这些窗口。`s0_windows["kcal"][1]` 于是变成 maintain EER，band 判据退化成 `EER < kcal_hi <= EER`，恒假 —— **内存里 Pass，冻结后永远 Fail**。

修法：band oracle 保留 S0 窗口不重导（`split.py`），加两条加载期校验（band oracle 不得指名 windows、必须带 profile）。

**(b) 手册给两条路，scorer 只认一条。**
手册教 "patch phase, or move daily energy…"，但 scorer 精确比较 `phase`，agent 无从知道该走哪条。根因在 scorer 不在手册 —— ADR 0015 判的是窗口落点，phase 只是手段。现在 band 下 phase 自由；走错方向仍然 Fail，因为 Env 导出的窗口打不中 band。

**为什么原来没抓到（重要，同类洞会再犯）：**

| 保护层 | 为什么是盲的 |
|---|---|
| 240 零漂移 | v0.5 里 0 题带 body facts、0 题用 `update_band`，新路径根本不执行 |
| 04 的单元测试 | 用 `Oracle(profile=s0.profile, ...)` 在 Python 里直接构造，**绕过了 JSON 加载路径** |

缺陷正好落在两层之间。已补 `test_fatigue_band_survives_a_freeze_load_round_trip` 堵第二个洞；第一个洞要等 ticket 08 造出 band 题才能堵。

## 3. 测试提速 436s → 62.9s（1150 passed）

不是砍覆盖，是去掉重复计算。三个乘数叠在一起：

| 层 | 问题 | 修法 |
|---|---|---|
| `FoodCatalog.__getitem__` | clone 共享 `_base`，每读一个食物 deepcopy 一次；validator 全量扫描 = 每 task 拷 13k 条 | 新增 `iter_entries` 只读扫描；**五处**全量遍历改用它 |
| `load_catalog` | 每次调用重读 sqlite（0.17s），realizations 表 233 行 ≈ 40s | 按 `(path, mtime, size)` 缓存快照；clone 仍是独立 COW |
| `_food_identity_index` | 缓存 key 是 `id(catalog)`，每 task 新对象所以**永不命中**，且 id 复用会返回错索引 | 挂到 catalog 对象上 |

外加 4 处测试里 `validate_draft` 在 assert 和失败信息里各调一次。

单个最慢测试 81.5s → 3.1s。剩下 63s 里 top12 占 41s，其余 1138 个测试合计 21.5s。

## 4. 新提的三个 issue

| # | 标题 | 起因 |
|---|---|---|
| 11 | catalog entry 不可变，撤掉 COW | COW 现在只防「调用方就地改 entry」，而代码里没有这种写法 |
| 12 | Oracle 可达性是 Bench 的能力 | `achievable` 检查在 6 个测试文件里复制且**已分叉**（v03 按 family、v05 按 oracle 形状、v04 只覆盖 plan 类）；mill 冻结出新 split 后没有工具能问「这批题可达吗」 |
| 13 | catalog 构建可复现 | 同样原始数据重建两次，2014 条 portions 的 JSON key 顺序不同 → sha256 不同 → **数据等价的 catalog 会被拒绝加载** |

## 5. 等你拍板的四件事

**(a) ADR 0014–0017 从未进版本控制。**
`realize.py:113`、`daily_windows.py:32`、`bench/README.md` 都引用 ADR 0015 当判分依据，但那四个文件是 untracked。已排除是 gitignore（`git check-ignore` 退出码 1、`core.excludesFile` 未设、`.git/info/exclude` 空、`git status --ignored` 里它们是 `??` 而非 `!!`）—— 纯粹没人 `git add` 过。要不要提交？（主仓还有一批 mill 相关 untracked WIP，未动。）

**(b) v0.5 什么时候归档。**
你提到「现在的开发有很多设计和之前路线不同，旧 test 挡路」。已核实：04 这轮**一次都没被 v0.5 挡过**（0 题走新路径）。但如果新设计要改的是判分语义或 Profile/split 结构，那是真冲突，该走归档。

归档的先例在 `test_exam_entry.py`：v1.0 被归档时测试不是删，而是反转成 `test_v10_pilot_is_not_on_the_formal_path`（断言它已不在 `data/splits/`），加载器再加拒绝规则。项目历史上**一个测试文件都没删过**（`git log --diff-filter=D -- tests/` 为空）。

需要你回答的是：**具体哪个设计撞上了？** 是 Profile 结构要变、判分规则要变、还是 split 的 JSON schema 要变。

**(c) v0–v0.4 的测试文件能不能删。**
包含链完整无损失：`v0(40) ⊂ v0.1(64) ⊂ v0.2(100) ⊂ v0.3(156) ⊂ v0.4(207) ⊂ v0.5(240)`。所以「历史增量检查」（`test_vXX_keeps_prev_items`）确实冗余。

但**不能直接删** —— 那些文件里还有 v0.5 测试文件没有的题库结构断言：

| 断言 | 在哪 | v0.5 有吗 |
|---|---|---|
| recommend 覆盖每个 persona × 每个过敏原标签 | v04 | 没有 |
| recommend 题面不泄漏窗口数字 | v04 | 没有 |
| evaluate 覆盖每个难度档 | v03 | 没有 |
| leftover 数量达 ADR 底线 | v02 | 没有 |
| constrain 保留两种机制 | v02 | 没有 |

该做的是**迁移而非删除**：把这五条提成 split-agnostic 检查（与 issue 12 同源），之后删历史增量断言才是零损失。要并进 12 还是单开一个 issue，未定。

**(d) ticket 08 要不要加一条验收。**
08 已要求造 band 题（"implicit intents use bands from 04"），但没要求「新造的题冻结后逐题验可达」。缺陷 (a) 正是「冻结后不可 Pass」，没这条门就会返工。未动 08 的既有验收条件。

## 6. 速查

**catalog 现状：还在 v1，v2 已构建但故意未启用**

| 文件 | 内容 | 构建时间 | 状态 |
|---|---|---|---|
| `catalog.sqlite` | 13224 条（SR Legacy 7793 + FNDDS 5431） | 2026-08-16 | **现役**，`GOLD_CATALOG_PATH` 指向它，sha `ff2f2632…` |
| `catalog-v1.sqlite` | 同上，重建版 | 2026-08-17 | 旁置（就是 issue 13 里 sha 对不上的那份） |
| `catalog-v2.sqlite` | 5431 条，FNDDS-only | 2026-08-18 | 已构建**未启用** |

v2 会大改克数：`cheddar` slice 21→9g、`tuna` can 165→75g、`tofu` cup 126→248g。240 题引用的 25 个 food_id 里 13 个会变，这 10 个 staple 在 split 里共 97 行。按 dry-run 的设计，**v2 不覆盖现役，v0.5 绑 sha 不受影响** —— v2 是给下一把尺子用的，落地方式是「新 split 用新 catalog 造」，不是「切换」。

**在 worktree 里跑测试**：`data/fdc/raw/` 和 `data/usda.db` 被 gitignore，只在主仓有。worktree 里跑全量前要软链接过去，否则 `test_catalog_v2_fndds_only.py` 的 6 个测试会报 `FileNotFoundError: fndds.zip`（看着像回归，其实是缺数据）。提交前记得 `rm` —— `.gitignore` 写的是 `data/fdc/raw/`（末尾斜杠只匹配目录），软链接不被忽略。

**240 零漂移是什么**：v0.5-gold.json 的 240 题是冻结的考卷（log 48 / recommend 72 / evaluate 48 / update 36 / constrain 36）。零漂移 = 改代码后这 240 题判分结果一个都不变。`test_v05_whole_exam_is_achievable` 是最硬的那个 —— 它把 Oracle 翻译成 Env 动作真跑一遍，recommend 分支还要现去 13k 食物里搜合规组合。它证明的是「尺子没被改坏」，**不证明新功能对不对**（见第 2 节的盲区）。
