# Tests

## How to run

From the repo root, in a local virtualenv (do not use system-site packages):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
```

`pyproject.toml` already points pytest at `tests/` and puts `src/` on `pythonpath`.

The published exam is `data/splits/nutrienv-v1.0.json`.
The default world catalog is `data/fdc/catalog-v2.sqlite` (FNDDS-only).
`data/fdc/archive/catalog.sqlite` and `catalog-v1.sqlite` stay in the tree as
mill / v0.x fixtures (SR portion keys that catalog-v2 drops). Rebuild the
active catalog with:

```bash
python scripts/download_fdc.py --sets fndds
python scripts/build_fdc_catalog.py --fndds-only --out data/fdc/catalog-v2.sqlite
```

The legacy snapshot is rebuilt with:

```bash
python scripts/download_fdc.py --sets sr_legacy fndds
python scripts/build_fdc_catalog.py
```

Branded foods (Lay's, etc.) are optional and large:

```bash
python scripts/download_fdc.py --sets branded
python scripts/build_fdc_catalog.py --branded
```

## What Pass means

**Pass** is the Bench headline: a binary Hand-in verdict for one Task. After the episode, the scorer compares the world's end state to the Task Oracle (from the frozen split, or from `realize(material, query)` in tests).

- Writes apply immediately. Pass ⇔ the Task's hard checks hold on that end state.
- The Oracle is derived from `(S0, query)`. Fields the query asks to change must match; fields it does not mention must stay as S0.
- Hard checks include allergen intersection on a submitted plan, minted food ids, the Task's nutrient windows, and the log/update contract.
- Diagnostic tags (`allergy`, `window`, `oracle`, …) explain a fail. They are not the headline and are not a 0–100 quality score.
- Illegal Actions (bad schema, unminted `food_id`) are Env physics: an error observation, no mutation, episode continues. They are not a Hand-in fail by themselves.

See [`docs/glossary.md`](../docs/glossary.md).
