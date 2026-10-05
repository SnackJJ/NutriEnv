# Evaluation reports

## v1.1: internal ARK single runs

The three `ab_ark_*_v1.1-new_fc.json` files are the cited 63-task runs:

- `ab_ark_deepseek-v4.1-flash_v1.1-new_fc.json`: 60/63.
- `ab_ark_glm-5.3-flash_v1.1-new_fc.json`: 56/63.
- `ab_ark_doubao-seed-2.1-lite_v1.1-new_fc.json`: 37/63.

**Internal ARK, single run per model, not the official leaderboard.** The [README table](../README.md#v11-results)
and `assets/v1.1_internal_ark_*.png` use those exact reports. Temperature 0, full context,
serial native tools, no voids. Scorer `s10-meal-mass-envelope`, prompt
`p8-published-meal-mass-limits`, loop `l2-refused-handin-continues`.

`v1.1-provenance.json` records SHA-256 identities of the current split, catalog and original
report bytes. All 189 queries match the split; replay checks recorded action acceptance/refusal
and unchanged Pass/score tags. The original reports did not record split/catalog hashes at
run time; this manifest is explicitly a **current-artifact replay verification**, not invented
run-time provenance. It does not rerun a model or prove repeated-run stability.

```sh
uv run --extra plots python scripts/render_v1_1.py
```

## v1.0: historical

[Preserved published results](../README.md#v10-historical) use the original table and image
assets. `benchmark_commandcode_*_v1.0_fc_r*.json`, their text-json controls, the official
DeepSeek API result and the earlier nonparallel DeepSeek run remain unchanged. Additional
lab ARK and ablation traces are historical evidence, not interchangeable leaderboard runs.
Reproduce the released v1.0 protocol at revision `94c211a`; today's scorer does not reproduce
that ruler. Do not run the historical renderers over new reports and overwrite the old images.

## Provenance and retention

Only compare results with matching split contents/catalog, scorer, prompt fingerprint, loop,
transport, provider endpoint and sampling settings. Matching filenames or model names are
insufficient. Missing identity fields make historical comparisons unverified, not implicitly
compatible. `--resume` / reuse reject stale protocol identities. `rescore_report.py` requires a
compatible prompt/loop and faithful action replay; it cannot simulate different instructions.

`reports/archive/audit_and_probes/agent-behavior-*` are recorded inputs to compatibility tests.
Local, uncited process runs belong under `archive/local-*/`, not in the publication table.
The explicit `.gitignore` allowlist admits the three v1.1 traces and manifest; local runs do
not become publication evidence merely by appearing here. Tracked ablation write-ups and the
artifacts they cite remain available in lab.
