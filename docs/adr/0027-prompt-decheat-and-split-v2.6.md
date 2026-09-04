# ADR 0027: ReAct prompt de-cheat, `amend_meal` envelope, and Gold v2.6

- **Status**: Accepted
- **Date**: 2026-09-03
- **Scope**: `src/nutrienv/harness/react.py`, `tests/test_react.py`, `scripts/build_v2_6_gold.py`, `data/splits/v2.6-gold.json`, `data/splits/nutrienv-gold.json`
- **Related**: ADR 0021 (no cheat sheets in the published manual), ADR 0025 (errata mint a new named split), ADR 0026 (`amend_meal` in Env)

The published ReAct manual describes tool envelopes, world physics, and hand-in rules. It does not translate exam templates into action sequences. Frozen `react-v0` / `react-v1` stay replayable for the v2.5 60.9% / 57.0% traces. `react-v2` is the published manual: `amend_meal {index, grams, food_id?, eaten_at?}` is listed next to `log_meal`; the ate-then routing lines (`"what to eat next"` → `log_meal` then `submit_plan`; `"is this okay?"` → `log_meal` then `verdict=accept`) are gone. Multi-step queries still require every write (`update_profile then submit_plan`; never `log_meal` future recommendations). Word count stays ≤ 400.

A Gold item is legal only when a qualified reader can recover the scored `(food_id, grams)` from the query, catalog observations, and published scorer — not from an unpublished QNS default or an unsaid FNDDS twin. Parenthetical patches that name an unsaid FNDDS twin are not a repair. v2.5-gold is frozen. v2.6-gold (128 tasks: update 5, log 14, evaluate 39, recommend 23, composite 47) is the next named split and the public `nutrienv-gold.json` (NutriEnv v1.0):

| Id | Repair |
|---|---|
| `adr26-log-1309` | Replaces `adr20-log-8205`. Query: two hard-boiled eggs and an apple for breakfast. Oracle `2707154` @ 100 g (piece × 2) + `2709215` @ 165 g (piece) |
| `adr26-log-1310` | Replaces `adr20-log-5004`. Query: a glass of whole milk and a banana for breakfast. Oracle `2705385` @ 244 g (cup/glass) + `2709224` @ 126 g (piece) |
| `adr24-comp-8301` | Query names a serving of tripe (QNS 85 g) |
| `adr24-comp-8303` | Query names a serving of cooked fresh carrots (QNS 78 g) |
| `adr20-log-5005` | Query names a standard plate (QNS 305 g); food id already unique |
| `adr24-comp-9402` | Query names cooked split peas prepared with added fat (`2707421` @ 185 g) |
| `adr24-comp-9403` | Query names brown rice with vegetables and gravy made with no added fat (`2709123` @ 288 g) |
| `adr24-comp-9503` | Same fat-status dining speech as 9403 (`2709123` @ 288 g) |
| `adr25-eval-1003/1005/1006/1007` | Prospective "planned lunch" tense; `ledger=()` and `last_verdict=accept` unchanged |

Standalone Evaluate with an empty ledger must not use past-tense intake speech. Past-tense intake plus evaluate is Composite Log+Eval. The scorer is unchanged: `Pass ⇔ end state == Oracle`. Extra `log_meal` on a pure Evaluate is `log_miss`. Do not in-place edit `v2.5-gold.json`.
