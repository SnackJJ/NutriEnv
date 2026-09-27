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
PROMPT_VERSION = "p5-fc-manual-lines"

# The hash of the frozen prompts. Regenerate deliberately:
#   .venv/bin/python -c "from nutrienv.harness.prompt_freeze import prompt_fingerprint as f; print(f())"
PROMPT_FINGERPRINT = "260a1c5261a1678134460f0b5986f1b47aa322ff45c6a76cc334c05c1e36528a"


# The fingerprint hashes both arms' prompts together, so a change to one arm moves it for reports
# of the other. These are earlier fingerprints whose text-json arm was byte-identical to today's,
# each with the hash of that arm (text_arm_sha256) when it was recorded. A text-json report
# carrying one counts as the current generation only while the arm still hashes the same, checked
# at use, so any edit to the text manual or its parse-error turns retires the entry by itself.
TEXT_EQUIVALENT_FINGERPRINTS = {
    # p4-full-parity -> p5-fc-manual-lines changed only the native-tools arm.
    "c64584565b9348f993de38a1a391ea02d905cac02c57aa76b6d3ce764e78ac13": (
        "212c4f9478fb0663fbaca72854173fc95281d8f958bbdef86480454eec340d5e"
    ),
}


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
- Ops and their arguments are as declared above (or in the tool schemas).
- Writes apply immediately. The end state is graded, on finish or at the step limit; an
  episode that writes nothing fails.
- Multi-step queries need every step's write: an allergy change followed by a dinner ask is
  update_profile then submit_plan. Never log_meal a future recommendation.
- Nutrient numbers come from observations, not prior knowledge. Catalog energy is per 100 g.
- allergy fields carry catalog allergen_tags (e.g. shellfish, peanut), not food names.
- A food_id unknown to the catalog changes nothing; slugs such as milk_whole resolve.
- Fields the user does not mention keep the value from the opening profile and ledger.
- amend_meal's index is 0-based into the current ledger.
- log_meal without eaten_at is stamped as today's current meal; slot names look like
  today-breakfast, today-lunch, today-dinner, today-snack.
- Daily windows from get_profile are the whole day's budget, not a meal budget: subtract
  what the ledger already holds to get the remainder a plan must fit.
- A single planned meal targets its share of daily energy: breakfast 25-30%, lunch 30-40%,
  dinner 30-40%. A snack has no share.
- Spoken leaning ("trying to cut", "building muscle", "I weigh 70 kg now"): update_profile
  the phase or the numbers asked for, or move daily energy toward or below maintenance, or
  protein above 0.8 g/kg. There is no published step size. "Stop the cut" means phase
  maintain. Unmentioned allergies and window keys stay as they are.
- submit_plan is the hand-in: after it the episode ends, so do not update_plan afterwards.
- Evaluation tasks: either submit_plan with verdict=accept and the exact named meal, or
  verdict=reject with no items plus the reason codes that apply. The codes are 'allergy' or
  '<key>_hi' / '<key>_lo' for keys kcal, protein_g, carb_g, fat_g, fiber_g, sodium_mg. If the
  query also asks what to eat instead, send one submit_plan with verdict=reject, those codes
  and the replacement items. A later submit_plan without a verdict replaces the reject.
- Recommend tasks: submit_plan with a safe meal that fits the windows, and no verdict.
"""
