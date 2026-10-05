# v1.1 release checkpoint

## State

Content migration is from `/home/jzq/Projects/nutri-env-lab` to the public repository
`/home/jzq/Projects/nutri-env`; histories are not merged. The public base is `94c211a`.
`backup-main-local` retains the former local main (`8c6a0c5`); the reasoning-effort feature is
included in the migrated evaluator, and the historical DeepSeek report already exists upstream.

**Push is not authorized yet.** Present the commits, README diff and checks; wait for the
user's confirmation before `git push origin main`. Do not push the lab history.

## Verified artifacts

- Split: `nutrienv-v1.1-mass-envelopes-20261005`; scorer `s10-meal-mass-envelope`;
  prompt `p8-published-meal-mass-limits`; loop `l2-refused-handin-continues`.
- `build_split_v1_1.py --check`: exam and all three reductions are up to date.
- `check_achievable.py --split data/splits/nutrienv-v1.1.json`: 63 items, 0 unreachable.
- All 189 ARK task queries match; action acceptance, Pass and score tags replay unchanged.
  Internal single-run results are 60/63, 56/63 and 37/63, not an official leaderboard.
- Catalog rebuild from the raw FNDDS ZIP is byte-identical:
  `63e5da2cbd33b5df376067be15a0897f70000be6494bd45e42647b0beab7cb5f`.
- Main and lab: `uv run pytest -q`, 1672 passed each. Full ingestion tests require the
  explicit raw USDA ZIP, which remains ignored and is not published.
- `uvx pyright --pythonpath .venv/bin/python scripts/render_v1_1.py scripts/rescore_report.py`:
  0 errors. The nullable module-docstring access was replaced with the same literal CLI description.
- Publication script/tests pass Ruff. Three new figures were visually inspected;
  four original public PNGs retain their pre-migration SHA-256 values.

## Cleanup and retained evidence

The interrupted session copied historical experiments indiscriminately. Unused imported
builders/probes, archived tests, old proposals and temporary split files are excluded from
public publication. Existing main-only local experiments remain in the external backup.
Canonical historical report bytes and old images are unchanged. The legacy parser module/CLI,
independent FNDDS verifier and compatibility fixtures remain because live callers/tests use them.
In particular, `build_fdc_catalog.py` dynamically loads `scripts/archive/fndds_dry_run.py`;
removing it was detected and corrected before completion.

Uncited ignored root reports were moved, not deleted: 90 in lab and 10 in main, under
`reports/archive/local-20261005/`. Tracked write-ups and their cited evidence remain. Local
archives are ignored explicitly; new publication reports are explicitly allowlisted.

Local recovery material is outside both repositories:
`/home/jzq/Projects/nutri-env-migration-backups/20261005-resume/` contains file snapshots
(excluding credentials), original dirty patches, excluded-file inventories, prior public
README/CHANGELOG, the old image hash manifest, rebuilt catalog and test logs. Do not publish
this recovery directory or credentials. No `reset --hard`, force-push or blanket clean was used
in this continuation.

Search recall, search ranking/truncation and p9 protocol changes remain deferred. Historical
v1.0 numbers require their own original ruler, not today's scorer over an old split.
