# Tests

Run from the repository root. `uv sync --extra dev` installs the test dependency; pytest
uses `src/` on its import path and excludes `tests/archive/` from default collection.

## Current release checks

```sh
uv run pytest -q tests/test_profile_and_plan_mass.py tests/test_goal_nutrition_contract.py \
  tests/test_scorer_ledger_variants.py tests/test_split_v1_1.py \
  tests/test_agent_authoring.py tests/test_v1_1_publication.py
uv run python scripts/build_split_v1_1.py --check
uv run python scripts/check_achievable.py --split data/splits/nutrienv-v1.1.json
uv run --extra plots python scripts/render_v1_1.py
```

The current exam binds `data/fdc/catalog-v3.sqlite`. Historical catalog/split fixtures remain
for compatibility tests; they are not default evaluation worlds. Recorded behavior fixtures
under `reports/archive/audit_and_probes/` are evidence inputs, not live model reruns.

## Full compatibility suite

Some ingestion/rebuild tests independently inspect the **raw USDA FNDDS ZIP**. It is ignored
and not shipped with the repository. Download it explicitly before running the full suite:

```sh
uv run python scripts/download_fdc.py --sets fndds
uv run pytest -q
```

Missing raw inputs fail loudly, rather than turn those tests into skipped or synthetic checks.
The builder also uses `scripts/archive/fndds_dry_run.py` as an independent portion verifier.
Archived v0.x/v2.x catalogs retain SR Legacy keys needed by legacy mill tests; do not rebuild
these immutable fixtures in place.

## Meaning of Pass

Pass is the binary task verdict: all required final-state checks must hold. Illegal actions
produce error observations without the invalid mutation; they are not themselves a completed
hand-in. Diagnostic tags explain failures but are not a separate quality score. The current
[v1.1 contract](../docs/review-v1.1-query-contracts.md) owns portions, target ranges, complete
ledger interpretations and mass envelopes. Historical results require their original ruler.
