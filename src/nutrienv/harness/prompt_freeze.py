#!/usr/bin/env python3
"""Frozen-prompt fingerprint: make a prompt drift impossible to miss.

The 2026-09-17 incident: the text harness's manual carried nine task-guidance sentences the
native tool-calling harness did not, so "text beats FC" could not be attributed to the protocol.
Worse, the manual was edited while a run queue was in flight, so one ablation straddled two
prompt versions.

This module closes both holes:

* :func:`prompt_fingerprint` hashes everything that shapes the model's instructions — the
  ReAct manual, the tool-calling system prompt and the native tool schemas.
* every report records it (``prompt_fingerprint``), so two runs can be compared on paper.
* :func:`assert_frozen` fails loudly when the hash moves, so changing a prompt is a
  deliberate act that must bump ``PROMPT_VERSION`` rather than a silent edit.
* ``compare_harness_modes.py`` refuses to print a delta across differing fingerprints, the
  same way it already refuses across differing splits or models.

    .venv/bin/python -c "from nutrienv.harness.prompt_freeze import prompt_fingerprint as f; print(f())"
"""

from __future__ import annotations

import hashlib
import json

__all__ = [
    "PROMPT_VERSION",
    "PROMPT_FINGERPRINT",
    "SHARED_TASK_SPEC",
    "prompt_fingerprint",
    "effective_fingerprint",
    "text_arm_sha256",
    "assert_frozen",
]

# Bump when a prompt or tool schema changes on purpose. Every report carries this string,
# so a bump also marks the boundary between two incomparable generations of results.
PROMPT_VERSION = "p8-published-meal-mass-limits"

# The hash of the frozen prompts. Regenerate deliberately:
#   .venv/bin/python -c "from nutrienv.harness.prompt_freeze import prompt_fingerprint as f; print(f())"
PROMPT_FINGERPRINT = "616dea69c32f9d469aac17b4ceafcadcf377d261934573ba9631c0f0cd75dfed"


# The fingerprint hashes both arms' prompts together, so a change to one arm moves it for reports
# of the other. These are earlier fingerprints whose text-json arm was byte-identical to today's,
# each with the hash of that arm (text_arm_sha256) when it was recorded. A text-json report
# carrying one counts as the current generation only while the arm still hashes the same, checked
# at use, so any edit to the text manual or its parse-error turns retires the entry by itself.
# p5 -> p6-amdr-window-ranges changed the shared task spec, so both arms moved and the p4 entry
# (p4-full-parity -> p5-fc-manual-lines, FC only) retired.
TEXT_EQUIVALENT_FINGERPRINTS: dict[str, str] = {}


def text_arm_sha256() -> str:
    """Everything the text-json arm says to a model: its manual and its parse-error turns."""
    from nutrienv.harness.react import (
        PARSE_ERROR_FEEDBACK,
        PARSE_ERROR_RESAMPLE,
        react_manual,
    )

    blob = json.dumps(
        [react_manual("v2"), PARSE_ERROR_FEEDBACK, PARSE_ERROR_RESAMPLE], ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def effective_fingerprint(record: dict) -> str | None:
    """The generation a report's instructions belong to, as of the current prompts."""
    recorded = record.get("prompt_fingerprint")
    contract = record.get("contract") or record.get("harness_mode")
    arm = TEXT_EQUIVALENT_FINGERPRINTS.get(recorded) if contract == "text-json" else None
    if arm is not None and arm == text_arm_sha256():
        return PROMPT_FINGERPRINT
    return recorded


def _payload() -> dict:
    # Imported lazily: react.py and tools_schema.py import this module's users.
    from nutrienv.harness.prompt_freeze import SHARED_TASK_SPEC
    from nutrienv.harness.react import react_manual
    from nutrienv.harness.tools_schema import NUTRIENV_TOOLS, TOOL_SYSTEM_PROMPT

    return {
        "shared_task_spec": SHARED_TASK_SPEC,
        "react_manual_v2": react_manual("v2"),
        "react_manual_v0": react_manual("v0"),
        "react_manual_v1": react_manual("v1"),
        "tool_system_prompt": TOOL_SYSTEM_PROMPT,
        # Canonical form so key order in the source file cannot move the hash.
        "tools_schema": json.dumps(NUTRIENV_TOOLS, sort_keys=True, ensure_ascii=False),
    }


def prompt_fingerprint() -> str:
    """SHA-256 over every instruction the model receives from the harness."""
    blob = json.dumps(_payload(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def assert_frozen(record: dict | None = None) -> str:
    """Raise when the prompts drifted from the frozen hash.

    ``record`` may be an existing report dict; when it carries a fingerprint from a
    different version, mixing its numbers with fresh runs is a mistake, so say so.
    """
    actual = prompt_fingerprint()
    if PROMPT_FINGERPRINT != "PLACEHOLDER" and actual != PROMPT_FINGERPRINT:
        raise RuntimeError(
            "prompt drift: the harness prompts no longer match the frozen fingerprint.\n"
            f"  frozen : {PROMPT_FINGERPRINT} ({PROMPT_VERSION})\n"
            f"  current: {actual}\n"
            "If the change is intended, bump PROMPT_VERSION and set PROMPT_FINGERPRINT to "
            "the new value; every earlier report becomes a different generation."
        )
    if record is not None:
        recorded = effective_fingerprint(record)
        if recorded and recorded != actual:
            raise RuntimeError(
                f"report was produced with a different prompt generation "
                f"({recorded} vs {actual}); its numbers are not comparable"
            )
    return actual


# The shared task contract. Both harnesses receive exactly this text; only the way the
# tools are presented differs between them. It carries the *output contract* (vocabularies,
# state-machine semantics, defaults) and no strategy advice: a benchmark that hides the
# vocabulary its scorer matches against is testing guessing, while a benchmark that gives
# advice to one side only is testing the advice.
SHARED_TASK_SPEC = """Task contract, identical for every harness:
- Use declared ops/arguments. Writes apply immediately; finish or the step limit grades the
  end state. Writing nothing fails. Multi-step queries require every write: allergy change
  then dinner is update_profile then submit_plan; consumed food then evaluation requires
  logging and a verdict. Never log_meal a future recommendation.
- Use observed nutrients/portions, not prior knowledge. Nutrients are per 100 g. Explicit
  piece/slice/cup/tbsp/bar/pouch and other count units use their table keys times the count.
  Food nouns without units, and bowl/plate/glass/serving, use portions.qns. Missing keys or
  unsupported sizes require clarification, never substitution or invented grams.
- Allergies use catalog allergen_tags (shellfish, peanut), not food names. Unknown food_id
  changes nothing; slugs such as milk_whole resolve. Unmentioned fields keep opening values.
- amend_meal index is 0-based. Omitted eaten_at is now; named meals use today-breakfast,
  today-lunch, today-dinner, today-snack.
- get_profile daily windows are whole-day [min,max]. Subtract ledger nutrients from maxima
  for remaining caps. Daily minima are not single-meal floors. Meal energy shares:
  breakfast 25-30%, lunch/dinner 30-40%; snack has no share.
- Published plan_limits in reset/get_profile also cap total edible mass, including drinks:
  a main meal 1500 g, snack 500 g, whole day 4000 g. Splitting rows cannot evade this cap.
- Maintenance energy is Mifflin-St Jeor times activity; cut targets 300 kcal less. Ordinary
  AMDR: protein 10-35% (also at least 0.8 g/kg), carbohydrate 45-65%, fat 20-35% of target
  energy; convert with 4/4/9 kcal/g respectively. Muscle keeps maintenance energy with a
  separate 1.6-2.2 g/kg protein range. Read actual windows after changes.
- Explicit high-protein meals/snacks require at least 10 g protein and 20% protein energy
  (4 times protein grams), plus remaining caps. Muscle persona alone adds no meal floor.
- Spoken goals ("trying to cut", "tiring deficit", "I weigh 70 kg now", muscle): update_profile phase
  or facts, or adjust windows toward the goal; direct changes have no required step size.
  Stop the cut means maintain. Phase/body changes re-derive windows;
  otherwise unmentioned allergies/windows stay unchanged.
- submit_plan ends the episode; never update_plan afterwards. Recommend: safe fitting meal,
  no verdict. Evaluate: verdict=accept with the exact named meal, or verdict=reject with no
  items and applicable reasons: allergy, implausible_quantity, or <key>_hi/<key>_lo for kcal, protein_g, carb_g,
  fat_g, fiber_g, sodium_mg. If asked for a substitute, include replacement items in that
  same reject submission. A later verdict-free submission replaces the reject.
"""
