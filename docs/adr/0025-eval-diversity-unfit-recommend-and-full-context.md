# ADR 0025: Next exam is v2.3; v2.2 stays frozen

Published NutriEnv numbers are always a frozen split. Label errors and false negatives are fixed by minting the next version, not by rewriting the one people already cited.

**Status**: Accepted. Supersedes ADR 0024 only on the ban of Evaluate-unfit + Recommend as a Composite pair, and on treating 100 items as a ceiling.

## Versioning

v2.2-gold (100 items) is frozen. Hygiene, extra Evaluate accepts, and Evaluate-unfit + Recommend land in `data/splits/v2.3-gold.json` (118 items = 100 kept ids + 18 new). `EXAM_SPLIT_PATH` stays v2.2 until a v2.3 leaderboard is published. Build with `scripts/build_v2_3_gold.py`.

A frozen exam is not bug-free. HELM, MMLU, SWE-bench, and GSM8K all ship errata as a new named split. Silent in-place gold edits make old Pass rates unreproducible. Typos that do not change the oracle can be noted as errata; a changed food id, grams, or family is a new version.

## Decisions

1. **Do not squeeze v2.2 items.** New skills append. Log+Rec `adr24-comp-8239` / `adr20-comp-5044` stay.

2. **Evaluate-unfit + Recommend is a Composite pair** (8 new items `adr25-comp-1101`–`1108`). Query names a meal, asks if it works, and asks for a replacement if not. Env allows `submit_plan` with `verdict=reject` and non-empty `items`. The reject child omits `last_plan`; the recommend child is the empty-plan sentinel. Standalone Evaluate reject gold still requires an empty adopted plan, so old reject items do not start passing when an agent also hands in a substitute.

3. **More Evaluate accepts, mixed plate sizes.** Ten new accepts (`adr25-eval-1001`–`1010`): 1-, 2-, 3-, and 4-item restaurant plates, plus 1-item lunches. Existing 16/20 rejects stay; 1-item Evaluate remains, because a single named dish is still ordinary speech.

4. **Hygiene on the 100 copied ids** (bowl/plate → QNS, cherry pie not filling, plain granola bar, spoken scene for variants) applies only in v2.3. Plan grams use the ledger band (`±15%` and table). Published ReAct is full context; `--context-limit 12` is ablation; `--reuse-from` copies `n_steps <= 5` only when the live query still matches.

## Env impact on old items

Reject + items is a newly legal Action. Scorer still fails standalone Evaluate reject unless `last_plan` is empty. Recommend oracles ignore `last_verdict`, so a substitute plan that fits windows can still Pass a Recommend — same as omitting verdict. No v2.2 oracle changes.

## Item list

`docs/v2.2-gold-audit-followup.md` (v2.3 inventory).
