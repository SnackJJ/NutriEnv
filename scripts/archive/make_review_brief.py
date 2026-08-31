import os, json, datetime
from pathlib import Path

run_id = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
out_dir = Path(f'.scratch/reviews/{run_id}')
out_dir.mkdir(parents=True, exist_ok=True)

with open('data/splits/v2.1-gold.json') as f:
    v21 = json.load(f)

items = v21['items']

pruned = ['adr20-log-5000', 'adr20-eval-5011', 'adr20-upd-5030', 'adr20-upd-5032', 'adr20-upd-5033']
retained = [it for it in items if it['id'] not in pruned]

brief = f"""# Review Brief: Audit of 35 Retained Tasks from v2.1-gold for v2.2-gold Benchmark

**Run ID**: `{run_id}`
**Objective**: Audit the 35 candidate tasks proposed to be retained from `v2.1-gold.json` and carried over into the new ADR 0024 100-Task Benchmark (`v2.2-gold.json`).

---

## 1. Proposal & Retention Scope

Under ADR 0024, NutriEnv is upgrading to a 100-Task Standard Suite with hierarchical allergy scoring, non-meal condiment filter, and decoupled step budgets.
From the 40 tasks in `v2.1-gold.json`, we propose retaining 35 high-quality tasks and pruning 5 problematic/excess tasks:

### Pruned Tasks (5 items):
1. `adr20-log-5000`: "I had a small bowl of sweet potato paste for lunch." (Bad Case: paste as standalone meal + bowl mapping to 20g QNS anchor).
2. `adr20-eval-5011`: "Can you evaluate my planned lunch: two tablespoons of Korean dressing or marinade?" (Bad Case: standalone marinade/dressing evaluated as a full meal).
3. `adr20-upd-5030`, `adr20-upd-5032`, `adr20-upd-5033`: Excess update tasks (ADR 0024 sets Update quota to exactly 5 tasks; keeping the best 5).

### Retained Tasks Under Audit (35 items):
- **Update (5 items)**: 5026 (add peanut), 5027 (add egg), 5028 (remove peanut), 5029 (active moderate), 5031 (muscle phase).
- **Log (7 items)**: 5001 (tongue + cornbread), 5003 (mixed veg), 5004 (burger + popcorn), 5005 (fish noodles cheese sauce), 5006 (fried tomatoes), 5007 (3-egg omelet), 5008 (savoy cabbage).
- **Evaluate (7 items)**: 5009 (almond butter sandwich - allergy veto), 5010 (burrito + wine), 5012 (pasta + pecans + pizza), 5013 (steamed haddock), 5015 (corned beef + chicken salad sandwich), 5016 (ham rice mushroom sauce), 5017 (salmon cake + adobo + pistachios).
- **Recommend (8 items)**: 5018 to 5025 (breakfast, lunch, dinner planning).
- **Composite (8 items)**: 5034, 5038, 5041, 5044, 5047, 5048, 5050, 5052 (Note: `family` label is fixed from "log" to "composite").

---

## 2. Binding Constraints & Invariants

1. **ADR 0024 & AGENTS.md Hard Invariant**: Gram anchors MUST strictly match FNDDS / QNS / `matches_portion_table`. No direct LLM gram invention.
2. **Meal Feasibility Gate (ADR 0024)**: No single-item paste/sauce/oil/condiment as a standalone meal.
3. **Hierarchical Allergy Scoring (ADR 0024 & Scorer P0)**: If `allergy` is in `oracle.last_reasons`, agent reporting `reject` with `allergy` is sufficient for Pass.
4. **End-State Compatibility (ADR 0016 / 0024)**: All composite tasks must have mutually satisfiable sub-oracles.
5. **Round-Trip Solvability (ADR 0023)**: All 35 items have passed `check_achievable` (`unreachable: ()` and `Scorer.score() -> Pass`).

---

## 3. Detailed Task Definitions for All 35 Retained Tasks

"""

for idx, it in enumerate(retained):
    tid = it['id']
    fam = 'composite' if tid.startswith('adr20-comp') else it['family']
    q = it['query']
    persona = it.get('persona', {})
    oracle = it['oracle']
    brief += f"""### Task {idx+1:02d}: `{tid}` [{fam}]
- **Query**: "{q}"
- **Persona**: `{persona}`
- **Oracle**:
```json
{json.dumps(oracle, indent=2)}
```

"""

brief += """
---

## 4. Output Contract for Reviewers

Please review the 35 retained tasks against:
1. Grounding validity & common sense (are any remaining queries ambiguous or absurd?).
2. Allergen & DRI window consistency.
3. Family tagging & Oracle structure soundness.

Write your review to the assigned file. Format:
## Verdict
one line: approve / revise / reject — plus single strongest reason

## Findings
- [blocking|major|nit] item-id / claim: what is wrong, and what would fix it

## Assumptions
what you took as given
"""

with open(out_dir / 'brief.md', 'w') as f:
    f.write(brief)

print('RUN_ID:', run_id)
print('Brief written to:', out_dir / 'brief.md')
