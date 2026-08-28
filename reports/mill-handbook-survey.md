# LLM Benchmark Agent Handbook & System Prompt Survey

**Document Target:** `reports/mill-handbook-survey.md`  
**Purpose:** Inform the scope, length, and content boundaries of the NutriEnv agent handbook / system prompt (`react.py`).  
**Context:** We need a thin, rigorous handbook covering operational primitives, portion table conversion rules, and the ledger leftover calculation, avoiding a bloated "nutrition-law treatise".

---

## 1. Executive Summary & Benchmark Comparison

Published agent benchmarks consistently follow one core design rule: **The system prompt/handbook defines the interaction protocol, operational constraints, and domain-specific business policies, but deliberately excludes encyclopedic world facts, task solutions, and domain tutorials.**

| Benchmark / Framework | Approx Length (Words / Tokens / Lines) | Primary Inclusions | Key Deliberate Omissions | Primary Sources |
|---|---|---|---|---|
| **SWE-agent / SWE-bench** | 350–500 words<br>(~500–800 tokens, 30–50 lines) | ACI tool definitions (`open`, `edit`, `goto`), JSON/turn protocol, strict indentation rules, submission command (`submit`). | Python/programming syntax, debugging recipes, repo-specific heuristics, git internals. | [SWE-agent GitHub](https://github.com/SWE-agent/SWE-agent)<br>[SWE-bench Harness](https://github.com/SWE-bench/SWE-bench) |
| **$\tau$-bench (Sierra)** | 500–1,200 words<br>(~800–1,800 tokens, 60–130 lines) | Domain policy (`wiki.md` for Retail/Airline), authentication preconditions, cancellation/return rules, API schemas. | Full database dumps, user intent prediction, general business law treatises, step-by-step solutions. | [$\tau$-bench GitHub](https://github.com/sierra-research/tau-bench)<br>[arXiv:2406.12045](https://arxiv.org/abs/2406.12045) |
| **WebArena / BrowserGym** | 300–600 words<br>(~450–850 tokens, 40–70 lines) | Web action primitives (`click [id]`, `type`, `goto`, `stop`), AXTree observation format, Thought/Action contract. | Website navigation manuals (e.g. how to use GitLab/Shopify), full DOM trees, CSS selectors. | [WebArena GitHub](https://github.com/web-arena-x/webarena)<br>[BrowserGym GitHub](https://github.com/ServiceNow/BrowserGym) |
| **GAIA** | 50–120 words<br>(~70–160 tokens, 5–12 lines) | Assistant persona, strict `FINAL ANSWER: [...]` termination formatting rule, tool invocation tags. | Any domain rules, math recipes, file parsing tutorials, pre-computed facts. | [GAIA GitHub](https://github.com/facebookresearch/GAIA)<br>[arXiv:2311.12983](https://arxiv.org/abs/2311.12983) |
| **OSWorld** | 300–550 words<br>(~400–750 tokens, 35–65 lines) | OS action schemas (mouse click coordinates, keystrokes, shortcuts), execution loop contract, `done()` / `fail()`. | Software-specific manuals (LibreOffice formulas, VS Code guides, GIMP docs), system file hierarchies. | [OSWorld GitHub](https://github.com/xlang-ai/OSWorld)<br>[arXiv:2404.07972](https://arxiv.org/abs/2404.07972) |
| **NutriBench / NGQA** | 30–180 words<br>(~40–250 tokens, 5–20 lines) | Input meal schema, target macronutrient output format (JSON/table), graph traversal instructions. | Food composition databases (FNDDS/USDA), RDA/DRI tables, portion conversion dictionaries. | [NutriBench (Gu et al.)](https://arxiv.org/abs/2404.01314)<br>[NGQA (Zheng et al.)](https://arxiv.org/abs/2402.14304) |

---

## 2. Deep Dive by Benchmark

### 2.1 SWE-agent & SWE-bench

* **Length & Structure:**
  * Base system template (`config/default.yaml` / `sweagent.yaml`): ~250–350 words (~35 lines).
  * With command documentation injection (`{command_docs}`): ~600–900 words (~800–1,200 tokens).
* **What It Includes:**
  1. **Role & Mental Model:** Identifies the agent as an autonomous software engineer interacting with a specialized terminal interface.
  2. **Tool / Command Specifications:** Documents custom commands (`open`, `edit`, `scroll_up`, `scroll_down`, `search_dir`, `search_file`, `submit`) with exact parameter types and required formatting.
  3. **Strict Syntactic Invariants:** Emphasizes crucial failure modes (e.g. *"THE EDIT COMMAND REQUIRES PROPER INDENTATION"*).
  4. **Turn Contract:** Enforces output format (e.g. one `THOUGHT` and one `COMMAND` per response).
  5. **Grading & Termination Protocol:** Defines that changes must be made in the filesystem directly, and `submit` triggers evaluation.
* **What It Deliberately Omits:**
  * No Python syntax explanations or coding tutorials.
  * No guidance on how to fix specific bugs or which files to inspect first.
  * No external standard library documentation.
* **Primary Sources:**
  * Repo: [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent)
  * Repo: [SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench)
  * Paper: Yang et al., *SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering*, [arXiv:2405.15793](https://arxiv.org/abs/2405.15793)

---

### 2.2 $\tau$-bench (Sierra Research)

* **Length & Structure:**
  * Base system prompt: ~150–200 words (~20 lines).
  * Domain Policy Handbook (`wiki.md`):
    * `retail/wiki.md`: ~520 words (~700 tokens, 65 lines).
    * `airline/wiki.md`: ~850 words (~1,150 tokens, 95 lines).
  * Total initial context: ~1,000–1,600 tokens.
* **What It Includes:**
  1. **Domain Policy Rules:** Explicit business logic boundaries that cannot be guessed from common sense (e.g. user authentication rules: verify email or name+ZIP before reading profile; 30-day return window; payment combination rules).
  2. **API Operation Signatures:** Available database querying and mutating functions.
  3. **State Mutation Constraints:** Exact constraints on when database records can be updated or cancelled.
* **What It Deliberately Omits:**
  * No static database dumps (the agent must query users/orders dynamically via tools).
  * No scripted multi-turn dialogue workflows or pre-written conversational trees.
  * No encyclopedic retail/aviation industry background.
* **Primary Sources:**
  * Repo: [sierra-research/tau-bench](https://github.com/sierra-research/tau-bench)
  * Policy Files: `tau_bench/envs/retail/wiki.md`, `tau_bench/envs/airline/wiki.md`
  * Paper: Bar-Tal et al., *$\tau$-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*, [arXiv:2406.12045](https://arxiv.org/abs/2406.12045)

---

### 2.3 WebArena & BrowserGym / AgentLab

* **Length & Structure:**
  * System prompt (e.g. `wa_p_som_cot_id_actree_3s.json`): ~350–500 words (~500–750 tokens, 45 lines).
  * Few-shot examples (when enabled): ~1,500–2,000 tokens.
* **What It Includes:**
  1. **Primitive Actions:** Available web operations (`click [id]`, `type [id] [content] [enter_after]`, `hover [id]`, `scroll [direction]`, `goto [url]`, `stop [answer]`).
  2. **Observation Semantics:** How to interpret accessibility trees, element IDs, and bounding boxes.
  3. **Format Constraints:** Step-by-step reasoning (`Thought:`, `Action:`).
  4. **Stop / Termination Condition:** `stop [answer]` for informative tasks; `stop []` for state-changing navigation tasks.
* **What It Deliberately Omits:**
  * No website-specific instructions (e.g. does not explain where the "checkout" button is on Shopify or how to navigate GitLab repos).
  * No general web design encyclopedias.
* **Primary Sources:**
  * Repo: [web-arena-x/webarena](https://github.com/web-arena-x/webarena)
  * Repo: [ServiceNow/BrowserGym](https://github.com/ServiceNow/BrowserGym)
  * Paper: Zhou et al., *WebArena: A Realistic Web Environment for Building Autonomous Agents*, [arXiv:2307.13854](https://arxiv.org/abs/2307.13854)

---

### 2.4 GAIA (General AI Assistants)

* **Length & Structure:**
  * System prompt: 50–100 words (~70–140 tokens, 5–10 lines).
* **What It Includes:**
  1. **Role Statement:** General AI assistant capable of multi-modal reasoning and tool execution.
  2. **Strict Output Formatting:** `FINAL ANSWER: [YOUR FINAL ANSWER]`. Precise rules on brevity (number only, or minimum comma-separated words).
  3. **Tool Invocation Tags:** Tool call tags (if using non-native API formats).
* **What It Deliberately Omits:**
  * Omits all domain guidance, reference formulas, and file parsing instructions.
  * Deliberately forces the model to discover how to inspect PDF/Excel/audio files and compute solutions autonomously.
* **Primary Sources:**
  * Repo: [facebookresearch/GAIA](https://github.com/facebookresearch/GAIA)
  * Dataset: [huggingface.co/datasets/gaia-benchmark](https://huggingface.co/datasets/gaia-benchmark)
  * Paper: Mialon et al., *GAIA: A Benchmark for General AI Assistants*, [arXiv:2311.12983](https://arxiv.org/abs/2311.12983)

---

### 2.5 OSWorld

* **Length & Structure:**
  * System prompt / agent configuration: ~350–500 words (~500–700 tokens, 40–60 lines).
* **What It Includes:**
  1. **Execution Primitives:** Desktop automation actions (mouse move/click `(x, y)`, drag, text type, keyboard shortcuts `hotkey`, `wait`, `done()`, `fail()`).
  2. **Screen Coordinate System:** Definition of viewport dimensions (e.g. 1920x1080) and scaling factors.
  3. **Turn Protocol:** Formatting thought steps and exact executable action strings.
* **What It Deliberately Omits:**
  * No application manuals (e.g. does not explain LibreOffice Calc spreadsheet formulas, GIMP image filters, or VLC player hotkeys).
  * The agent must visually navigate application interfaces directly.
* **Primary Sources:**
  * Repo: [xlang-ai/OSWorld](https://github.com/xlang-ai/OSWorld)
  * Paper: Xie et al., *OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Operating Systems*, [arXiv:2404.07972](https://arxiv.org/abs/2404.07972)

---

### 2.6 Nutrition Domain Benchmarks (NutriBench, NGQA)

* **Length & Structure:**
  * Prompts: ~30–150 words (~40–200 tokens).
* **What It Includes:**
  1. **NutriBench:** Task framing requesting macronutrient estimates (Calories, Carbohydrates, Protein, Fat) from meal text, with a strict output format (JSON/table).
  2. **NGQA:** Graph query framing asking if a food is safe/healthy given medical conditions, or multi-hop path reasoning instructions.
* **What It Deliberately Omits:**
  * No USDA or FNDDS nutrient composition lookup tables in the prompt.
  * No DRI (Dietary Reference Intake) charts or clinical nutrition textbooks.
* **Primary Sources:**
  * NutriBench Paper: Gu et al., *NutriBench: Assessing LLMs on Nutrition Estimation*, [arXiv:2404.01314](https://arxiv.org/abs/2404.01314)
  * NGQA Paper: Zheng et al., *NGQA: Nutritional Graph Question Answering*, [arXiv:2402.14304](https://arxiv.org/abs/2402.14304)

---

## 3. Analysis of Current NutriEnv Handbook (`react.py`)

### Current Footprint in `src/nutrienv/harness/react.py`

* **`_SYSTEM` (v0 Base Manual):**
  * **Lines:** 27 lines (lines 33–59)
  * **Word count:** 241 words (~320 tokens)
  * **Contents:**
    * Role declaration & strict JSON turn schema (`{"op": "...", ...}`).
    * Catalog of 10 available ops (`search_foods`, `get_food`, `get_profile`, `get_ledger`, `get_dri`, `log_meal`, `submit_plan`, `update_profile`, `update_plan`, `finish`).
    * Grading contract: Writes apply immediately; text is not hand-in; unmentioned fields stay unchanged; `food_id` resolution; catalog energy per 100g.
    * Leftover math: Subtract ledger eaten nutrients from profile daily windows, then `submit_plan` for remainder.
    * Allergen tags vs food names; finish on completion.

* **`_SYSTEM_V1_TAIL` (Portion Conversion Extension):**
  * **Lines:** 9 lines (lines 61–69)
  * **Word count:** 191 words (~255 tokens)
  * **Contents:**
    * `portions` table lookup semantics on `get_food`.
    * Named keys (`cup`, `tbsp`, `tsp`, `slice`, `piece`, `can`, `fl_oz`).
    * Default serving resolution: "a serving/portion/bowl/plate/order of X" & dish nouns -> `portions.qns` (fallback `piece` -> `slice` -> `cup`).
    * Bare noun rule: "one apple" -> `piece`. Unquantified cut ("chicken breast") -> do not log.
    * Serving size variations: "thick", "thin", "regular" -> `portions.thick` / `thin` / `regular`.
    * Ounce constant: 1 oz = 28.35 g. "150 g" is already grams.
    * Ignored reference keys (`oz`, `oz_yield`, `cubic_inch`).

* **Total v1 Handbook:** 36 lines, 432 words, ~575 tokens.

---

## 4. Recommendations for NutriEnv v1 Handbook

### 4.1 Target Length Recommendation: **Keep roughly the same (~400–480 words, ~550–650 tokens)**

* **Comparison with Benchmarks:**
  * NutriEnv v1 (~575 tokens) sits in the sweet spot established by **SWE-agent** (~600–900 tokens) and **$\tau$-bench** (~700–1,200 tokens).
  * It is neither an under-specified prompt (which causes arbitrary agent guessing on interface conventions) nor a bloated nutrition textbook.

### 4.2 Content Section Assessment: What to Keep, Refine, Add, and Cut

| Section in Handbook | Decision | Rationale |
|---|---|---|
| **1. Role & JSON Schema Constraint** | **KEEP** | Standard across all tool-use benchmarks (SWE-agent, WebArena). Ensures zero parsing failures. |
| **2. Available Ops List (10 ops)** | **KEEP** | Fundamental interface description (matching SWE-agent command docs). |
| **3. Grading Rule / State Mutation** | **KEEP** | Critical protocol clarity: "Writes apply immediately; text is not hand-in; score is end state; finish to exit". |
| **4. Leftover Subtraction Rule** | **KEEP & TIGHTEN** | Necessary business logic: `remainder = daily_windows - sum(ledger_nutrients)`. Without this, agents cannot know whether `windows` are daily or per-meal. |
| **5. Meal Energy Share** | **ADD (1 line)** | Add the single standard distribution rule for single-meal planning: *"When planning a single meal without explicit bounds, target the meal energy share: breakfast 25–30%, lunch 30–40%, dinner 30–40% of daily EER."* |
| **6. Portion Table Conversion (`portions` table, `qns`, `piece`)** | **KEEP** | Core domain contract. Teaches the agent to read dynamic data from `get_food` instead of hallucinating prior-knowledge gram weights. |
| **7. Serving modifiers (`thick`, `thin`, `regular`)** | **KEEP** | Clear mapping to catalog keys (`portions.thick`, etc.) preventing confusion with slice thickness. |
| **8. Conversion constants ("1 oz = 28.35 g", "150 g = grams")** | **KEEP** | High-utility disambiguation preventing unit-conversion drift. |
| **9. Negative lists (`oz`, `oz_yield`, `cubic_inch`)** | **CUT / TIGHTEN** | Redundant. Stating *"Only use the named household keys; ignore unlisted reference metadata"* saves tokens without losing precision. |
| **10. Nutrition Law / Dietary Guidelines / Food Facts** | **DELIBERATELY OMIT** | **Do NOT add.** USDA catalog lookups and DRI endpoints (`get_dri`, `get_food`) provide all ground-truth facts. |

---

## 5. Summary Checklist for NutriEnv Handbook V1

1. **Protocol & Contract:** JSON output format, 10 ops, write-first state evaluation.
2. **Dynamic Grounding:** All gram conversions must come from `get_food.portions`; all nutrients from `get_food` / observations.
3. **Math Rules:** Leftover window subtraction (`profile.windows` minus ledger); 1-line meal energy share (25–30% breakfast, 30–40% lunch/dinner).
4. **Thin & Enforceable:** Kept strictly under 500 words / 700 tokens. Zero food-lore bloat.
