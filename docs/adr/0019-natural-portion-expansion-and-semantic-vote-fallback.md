# ADR 0019: Natural Portion Expansion and Multi-Agent Vote Fallback

## Context & Problem
In previous iterations, LLM expanders were strictly constrained by system prompts to copy FNDDS database portion keys verbatim (`"Speak every chosen food's amount with exactly one phrase from the pool's own speakable portions list, verbatim"`). Because USDA FNDDS historically stored survey volume columns under the name `"cup"`, this mechanical constraint forced LLMs to generate unnatural expressions like `"a cup of roast beef"`, `"a cup of burrito"`, and `"a cup of pasta"`, despite `resolve_portion` already supporting natural container synonyms (`bowl`, `plate`, `order`, `serving`, dish nouns, `slice`, `piece`, `patty`).

Furthermore, real users often express fractional or colloquial portions (e.g., *"a generous portion"*, *"a slice and a half"*, *"two fist-sized potatoes"*). A rigid fail-closed parser without an escalation path rejects these realistic samples.

## Decisions

1. **Liberate LLM Phrasing (Colloquial First, No Verbatim Handcuffs)**:
   - Expanders and rewriters are instructed to write natural, conversational, dish-appropriate餐桌口语.
   - User prompts present speakable portions ordered by naturalness (`unit_naturalness_rank`: discrete > cooking > containers > generic).
   - Expanders are NOT forced to copy `"a cup"` for discrete solids or plated meals.

2. **Two-Tier Portion Resolution Architecture**:
   - **Tier 1 (Deterministic Parser `resolve_portion`)**: Fast, exact table lookup. Supports `piece`, `slice`, `patty`, `tbsp`, `tsp`, `bowl`, `plate`, `order`, `serving`, dish nouns, and number words. Zero drift.
   - **Tier 2 (Multi-Agent Vote Fallback `semantic_vote`)**: Triggered only when Tier 1 returns `None` on a novel/colloquial expression. Multiple LLMs/subagents receive the food's official FNDDS reference table (`base_unit -> grams`) and estimate `(base_unit, multiplier)` to compute `grams = base_grams * multiplier`.

3. **Human-in-the-Loop Review Assistance**:
   - LLM Vote results are NEVER silently written into the final exam split without review.
   - Vote outcomes produce structured consensus data (e.g. 3/3 consensus vs split vote) displayed in the Review Dashboard to assist human reviewers in approving or arbitrating edge cases.
   - Verified new colloquial phrases are backported into `portions.py` and `react.py` agent handbooks, closing the continuous improvement loop.

## Status
Accepted (2026-08-29)
