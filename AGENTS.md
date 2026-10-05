# NutriEnv — 公开主仓库

本目录 `/home/jzq/Projects/nutri-env` 是公开主仓库，GitHub 为 `SnackJJ/NutriEnv`，`main` 是发布主干。
实验仓在 `/home/jzq/Projects/nutri-env-lab`；两个仓库历史已分叉，按路径迁移内容，不合并 lab 分支历史。

- 中文回复，结论先行；代码、路径、命令和 Conventional Commits 保持英文。
- 必需输入缺失或非法时明确报错。演示数据仅在显式请求时使用；不吞异常、不静默兜底。
- 分批提交，一个关注点一个提交。split、catalog、prompt、评分口径独立提交，并说明可比性。
- 当前发布合同见 `docs/review-v1.1-query-contracts.md`；实验结果只在协议身份一致时比较。
- 保留 v1.0 历史报告和 `reports/assets/` 旧图；新图使用独立 v1.1 文件名并沿用旧图风格。
- v1.1 ARK 单次结果标为 internal ARK, single run, not the official leaderboard。
- 发布前展示提交摘要、README diff 和实测检查结果，等待用户确认后再推送。
- 续跑先核对 `git status`、提交和 `docs/release-v1.1-status.md`。

`AGENTS.md` 是项目记忆的唯一来源；`CLAUDE.md`、`GEMINI.md`、`.cursorrules` 和 `.github/copilot-instructions.md` 指向它。
