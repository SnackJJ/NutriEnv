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

## What Pass means

**Pass** is the Bench headline: a binary Hand-in verdict for one Task. After the episode, the scorer compares the world's end state to the Generator's Oracle.

- Writes apply immediately. Pass ⇔ the Task's hard checks hold on that end state.
- The Oracle is derived from `(S0, query)`. Fields the query asks to change must match; fields it does not mention must stay as S0.
- Hard checks include allergen intersection on a submitted plan, minted food ids, the Task's nutrient windows, and the log/update contract.
- Diagnostic tags (`allergy`, `window`, `oracle`, …) explain a fail. They are not the headline and are not a 0–100 quality score.
- Illegal Actions (bad schema, unminted `food_id`) are Env physics: an error observation, no mutation, episode continues. They are not a Hand-in fail by themselves.

See `CONTEXT.md` and `docs/adr/0002-binary-pass-headline.md`.
