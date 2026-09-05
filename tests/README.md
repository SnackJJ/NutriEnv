# Tests

Smoke for the published tree: Env step physics, Pass scoring, v1.0 exam load.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
```

The mill / split-history suite is not in this clone. The published catalog is
`data/fdc/catalog.sqlite` (FNDDS-only). Rebuild:

```bash
python scripts/download_fdc.py --sets fndds
python scripts/build_fdc_catalog.py --fndds-only --out data/fdc/catalog.sqlite
```
