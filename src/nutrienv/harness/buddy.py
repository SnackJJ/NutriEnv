"""Policy plugins wrapping ReAct. Env, Oracle, and Scorer stay untouched.

Switchable layers, matching NutriBuddy product ideas without copying the
TypeScript gates:

- pin: keep profile allergies/windows at the front of the context (used
  when the context window slides; full-trajectory eval leaves it off)
- calc: attach a harness-computed sandbox sheet to each observation
- check: bounce allergen-unsafe / meal-window-violating *plans* (not logs)
  back to the model, at most ``max_regen`` times, then hand the last action
  to Env so the Oracle still judges it. Judged windows are meal-slot ∩
  ledger remainder (ADR 0007), not the daily profile hi.
"""

from __future__ import annotations

import contextlib
import copy
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from nutrienv.world.daily_windows import (
    MEAL_ENERGY_SHARE,
    SIX_WINDOW_KEYS,
    high_protein_pass,
    judged_ceiling,
    plan_windows_for_meal,
)
from nutrienv.world.plan_limits import plan_limits_view, plan_mass_pass
from nutrienv.world.types import normalize_reasons, normalize_tags

from .protocol import Harness
from .react import ReActHarness

__all__ = [
    "BASELINE_SCAFFOLD",
    "SCAFFOLDS",
    "BuddyHarness",
    "ObservationCache",
    "Verdict",
    "check_write",
    "ingest_observation",
    "judged_plan_windows",
    "occasion_from_query",
    "plan_key",
    "plan_preview",
    "preview_text",
    "sandbox_sheet",
    "scale_items",
    "track_ledger",
    "verify_plan",
]

WRITE_OPS = frozenset({"log_meal", "submit_plan", "update_profile", "update_plan", "amend_meal"})
SANDBOX_LINE = (
    "Observations may include a sandbox object with harness-computed nutrient totals and "
    "the 'plan_windows' the environment scores against (with a 'windows_basis' label "
    "saying how they were derived); use those numbers instead of mental arithmetic."
)

# Isolation matters here: the legacy `check` scaffold turns calc ON as well, so the
# published "+9 from gating" was never attributable to the gate alone. The scaffolds below
# separate the three policy layers so each one has a baseline that differs in exactly one flag.
#
# A run is identified by three axes. Each one has its own name because collapsing them is how
# two published readings were born (see ADR 0027, ADR 0030):
#   * `scaffold` (these keys) -- which policy layers wrap the loop. Baseline is `none`.
#   * `contract` (`text-json` | `native-tools`) -- how an Action is expressed and handed back.
#   * `prompt_version` + `prompt_fingerprint` -- the instructions the model received.
# `ReActHarness.label` is a fourth, narrower thing: the manual generation (`react-v2`).
#
# Vocabulary history, because reports are never rewritten: the scaffold axis was called "arm"
# until 2026-09-24, and its values carried the product prefix (`react`, `buddy-calc`, ...).
# Archived reports keep those keys; the mapping to today's names is
# `react`->`none`, `buddy-<layer>`->`<layer>`, `buddy-check`->`check`, `buddy-full`->`full`.
#
# ADR 0030 retires `pin` and `check` from the reference design: `pin` guards against constraint
# loss under a truncated context, which the full-context default removed, and `check` has no
# exposure to prevent (no allergen-carrying plan has reached the env in 93 recorded runs). They
# stay here as experiment and control code -- `resample` is still the "same extra completion,
# no verdict" control -- but no report may count them toward NutriBuddy's design.
# The scaffold a run is compared against. One name, imported by the ablation driver, so the
# baseline cannot drift into two literals.
BASELINE_SCAFFOLD = "none"

SCAFFOLDS: dict[str, dict[str, bool]] = {
    BASELINE_SCAFFOLD: {"pin": False, "calc": False, "check": False},   # baseline harness
    "pin": {"pin": True, "calc": False, "check": False},        # retired (ADR 0030)
    "calc": {"pin": False, "calc": True, "check": False},       # arithmetic sheet only
    "gate": {"pin": False, "calc": False, "check": True},       # retired (ADR 0030)
    "check": {"pin": False, "calc": True, "check": True},       # legacy: gate + sheet
    "pin-gate": {"pin": True, "calc": False, "check": True},
    "pin-calc": {"pin": True, "calc": True, "check": False},
    "resample": {"pin": False, "calc": False, "check": False, "resample": True},  # 2 extra completions
    "full": {"pin": True, "calc": True, "check": True},         # all three; not the reference
    # Verify-then-revise (DESIGN_v2 2026-09-25): the harness totals a recommendation plan
    # and bounces an out-of-window one with the numbers. The placebo bounces on the same
    # condition with no numbers, so verify - placebo is the value of the computed figures.
    "verify": {"pin": False, "calc": False, "check": False, "verify": True},
    "verify-placebo": {
        "pin": False, "calc": False, "check": False, "verify": True, "placebo": True,
    },
    # Submit preview (DESIGN_v3.1): before every non-empty hand-in the harness shows the plan's
    # totals and the graded range, with no verdict; the model repeats the plan to confirm it.
    "preview": {"pin": False, "calc": False, "check": False, "preview": True},
}

# The Scorer's rounding slack on plan windows (scorer._PLAN_WINDOW_ROUNDING). The verify gate
# compares with the Scorer's own rule so that, on a correct state, it never refuses a plan the
# Scorer would pass; the ceiling slack itself comes from `judged_ceiling`.
_VERIFY_ROUNDING = 0.005
_UNITS = {"kcal": "kcal", "sodium_mg": "mg"}
VERIFY_HEADER = "Harness check: the plan was not submitted."
# Length-matched to the verify feedback (125 chars in full vs a measured 123-128 mean over 43
# replayed bounces), with no nutrient named and no number: the only difference left between the
# arms is which target failed and by how much.
VERIFY_PLACEBO_BODY = "Re-check it against the user's daily nutrient targets first."

_OCCASION_RE = re.compile(r"\b(breakfast|lunch|dinner|snack)\b", re.IGNORECASE)


@dataclass
class ObservationCache:
    """What the model has already seen. Never filled from the Oracle."""

    profile: dict = field(default_factory=dict)
    foods: dict[str, dict] = field(default_factory=dict)
    ledger_totals: dict[str, float] = field(default_factory=dict)
    # The ledger as rows (food_id, grams), kept by `track_ledger` for the verify gate. None
    # until an observation carries the whole ledger (reset does).
    ledger_rows: list[dict] | None = None
    plan_scope: str = "day"

    def clear(self) -> None:
        self.profile = {}
        self.foods = {}
        self.ledger_totals = {}
        self.ledger_rows = None
        self.plan_scope = "day"


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: tuple[str, ...] = ()
    # What the gate actually did. `ok` alone cannot separate "checked and clean" from "not a
    # checkable action" from "checked, but the windows were unverifiable" -- and without that
    # separation a gate that never ran reads as a gate that found nothing. The three
    # not_applicable paths below are the majority of calls (every non-submit_plan action), so
    # counting them as approvals would overstate the gate's activity by an order of magnitude.
    status: str = "approved"


def occasion_from_query(query: str) -> str | None:
    """Last spoken meal slot in the query. Composite prompts name lunch then dinner."""
    last = None
    for match in _OCCASION_RE.finditer(query or ""):
        last = match.group(1).lower()
    return last


def _as_totals(payload: object) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, float] = {}
    for key, amount in payload.items():
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            out[str(key)] = amount
    return out


def _store_food(cache: ObservationCache, food: dict) -> None:
    food_id = food.get("food_id")
    if not isinstance(food_id, str) or not food_id:
        return
    previous = cache.foods.get(food_id, {})
    cache.foods[food_id] = {**previous, **food}


def ingest_observation(cache: ObservationCache, observation: object) -> None:
    if not isinstance(observation, dict):
        return
    profile = observation.get("profile")
    if "plan_limits" in observation:
        scope = observation["plan_limits"]["scope"]
        plan_limits_view(scope)
        cache.plan_scope = scope
    if isinstance(profile, dict):
        cache.profile = profile
    totals = _as_totals(observation.get("ledger_totals"))
    if not totals:
        totals = _as_totals(observation.get("totals"))
    if totals:
        cache.ledger_totals = totals
    nested = observation.get("food")
    if isinstance(nested, dict):
        _store_food(cache, nested)
    if "nutrients" in observation or "allergen_tags" in observation:
        _store_food(cache, observation)
    for row in observation.get("results") or []:
        if isinstance(row, dict):
            _store_food(cache, row)
    if observation.get("op") == "log_meal":
        row = observation.get("row")
        if isinstance(row, dict):
            added, _tags, complete = scale_items([row], cache.foods)
            if complete:
                for key, amount in added.items():
                    cache.ledger_totals[key] = cache.ledger_totals.get(key, 0.0) + amount


def sandbox_sheet(cache: ObservationCache, query: str = "") -> dict:
    windows = cache.profile.get("windows") or {}
    # (f) Show the same window the gate and the Scorer judge against. Reporting
    # daily-minus-ledger instead handed the model numbers that did not correspond to
    # what it was scored on, so the calc arm was partly measuring misinformation.
    remaining: dict[str, list[float]] = {}
    basis = "daily_minus_ledger"
    judged = judged_plan_windows(cache, query) if query else None
    if judged:
        for key, (lo, hi) in judged.items():
            remaining[str(key)] = [lo, hi]
        basis = "meal_slot_intersection_remainder"
    elif isinstance(windows, dict):
        for key, bounds in windows.items():
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                continue
            try:
                lo, hi = float(bounds[0]), float(bounds[1])
            except (TypeError, ValueError):
                continue
            used = cache.ledger_totals.get(key, 0.0)
            remaining[str(key)] = [lo - used, hi - used]
    foods: dict[str, dict] = {}
    for food_id, food in cache.foods.items():
        foods[food_id] = {"nutrients_per_100g": food.get("nutrients") or {}}
    # Arithmetic only. Constraint recall (allergies / windows / allergen tags) is the
    # ``pin`` layer's job; duplicating it here made the two arms unidentifiable.
    return {
        "ledger_totals": dict(cache.ledger_totals),
        "plan_windows": remaining,
        "windows_basis": basis,
        "foods": foods,
    }


def scale_items(
    items: object,
    foods: dict[str, dict],
    lookup: Callable[[str], dict | None] | None = None,
) -> tuple[dict[str, float], set[str], bool]:
    """Return (totals, allergen tags, complete). complete=False if a food lacks nutrients."""
    totals: dict[str, float] = {}
    allergens: set[str] = set()
    complete = True
    if not isinstance(items, list):
        return totals, allergens, False
    for item in items:
        if not isinstance(item, dict):
            complete = False
            continue
        food_id = item.get("food_id")
        grams = item.get("grams")
        if not isinstance(food_id, str) or not food_id:
            complete = False
            continue
        food = foods.get(food_id)
        # A search hit carries allergen tags but no nutrients, so "known but incomplete"
        # is the common case. Consult the catalog whenever the cached entry cannot supply
        # nutrients, not only when the food is entirely absent, otherwise the window check
        # degrades exactly on the path models actually take.
        if lookup is not None and (food is None or not food.get("nutrients")):
            try:
                resolved = lookup(food_id)
            except Exception:
                resolved = None
            if resolved is not None:
                merged = dict(food or {})
                if not merged.get("nutrients"):
                    merged["nutrients"] = resolved.get("nutrients") or {}
                if not merged.get("allergen_tags"):
                    merged["allergen_tags"] = resolved.get("allergen_tags") or []
                food = merged
        if food is None or not food.get("nutrients"):
            complete = False
            continue
        tags = food.get("allergen_tags") or []
        with contextlib.suppress(ValueError):
            allergens.update(normalize_tags(list(tags)))
        nutrients = food.get("nutrients")
        if not isinstance(nutrients, dict):
            complete = False
            continue
        if isinstance(grams, bool) or not isinstance(grams, (int, float)):
            complete = False
            continue
        factor = grams / 100.0
        for key, amount in nutrients.items():
            if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                continue
            totals[str(key)] = totals.get(str(key), 0.0) + amount * factor
    return totals, allergens, complete


def _daily_windows(cache: ObservationCache) -> dict[str, tuple[float, float]]:
    raw = cache.profile.get("windows") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, tuple[float, float]] = {}
    for key, bounds in raw.items():
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            continue
        try:
            out[str(key)] = (float(bounds[0]), float(bounds[1]))
        except (TypeError, ValueError):
            continue
    return out


def judged_plan_windows(
    cache: ObservationCache, query: str = ""
) -> dict[str, tuple[float, float]] | None:
    """Meal-slot ∩ remainder from what the model has seen. Never reads the Oracle."""
    daily = _daily_windows(cache)
    if not daily:
        return None
    occasion = occasion_from_query(query) or "snack"
    eaten = {key: cache.ledger_totals.get(key, 0.0) for key in SIX_WINDOW_KEYS}
    if all(key in daily for key in SIX_WINDOW_KEYS):
        full = {key: daily[key] for key in SIX_WINDOW_KEYS}
        return plan_windows_for_meal(full, eaten, occasion, last_meal=False)
    share_lo, share_hi = MEAL_ENERGY_SHARE[occasion]
    out: dict[str, tuple[float, float]] = {}
    for key, (daily_lo, daily_hi) in daily.items():
        used = cache.ledger_totals.get(key, 0.0)
        rem_hi = max(0.0, daily_hi - used)
        if key == "kcal":
            slot_lo = daily_lo * share_lo
            slot_hi = daily_hi * share_hi
        else:
            slot_lo = 0.0
            slot_hi = daily_hi
        hi = min(slot_hi, rem_hi)
        lo = slot_lo
        if lo > hi:
            return None
        out[key] = (round(lo, 2), round(hi, 2))
    return out


def check_write(
    action: object,
    cache: ObservationCache,
    query: str = "",
    lookup: Callable[[str], dict | None] | None = None,
) -> Verdict:
    """Semantic pre-submit check. log_meal is never blocked (descriptive)."""
    if not isinstance(action, dict):
        return Verdict(ok=True, status="not_applicable")
    op = action.get("op")
    if op != "submit_plan":
        return Verdict(ok=True, status="not_applicable")
    if action.get("verdict") == "reject" and not action.get("items"):
        return Verdict(ok=True, status="not_applicable")
    items = action.get("items") or []
    totals, allergens, complete = scale_items(items, cache.foods, lookup=lookup)
    reasons: list[str] = []
    try:
        prohibited = set(normalize_tags(list(cache.profile.get("allergies") or [])))
    except ValueError:
        prohibited = set()
    if allergens & prohibited:
        reasons.append(
            "allergy: plan items carry "
            + ",".join(sorted(allergens & prohibited))
        )
    skipped: list[str] = []
    if not complete:
        # Partial nutrient data means the window check cannot be trusted. Staying silent
        # made the gate look inert; blocking on a gap would over-block instead. So skip
        # the check but report it, and let the arm summary expose how often this happened.
        skipped.append("window: unverifiable (incomplete nutrient data for the plan)")
    if complete:
        windows = judged_plan_windows(cache, query)
        if windows is None and _daily_windows(cache):
            reasons.append("window: no feasible meal-slot remainder")
        elif windows:
            for key, (lo, hi) in windows.items():
                amount = totals.get(key, 0.0)
                if amount > judged_ceiling(key, hi) + _VERIFY_ROUNDING:
                    reasons.append(
                        f"{key}_hi: plan {amount:.1f} exceeds {hi:.1f}"
                    )
                elif amount < lo - _VERIFY_ROUNDING:
                    reasons.append(
                        f"{key}_lo: plan {amount:.1f} below {lo:.1f}"
                    )
    if (complete and "high-protein" in query.lower()
            and action.get("verdict") != "accept" and not high_protein_pass(totals)):
        reasons.append("protein_share: requires at least 20% protein energy and 10 g protein")
    if items and complete and not plan_mass_pass(items, cache.plan_scope):
        reasons.append("implausible_quantity: plan exceeds the published total mass limit")
    if reasons:
        return Verdict(ok=False, reasons=tuple(reasons), status="violation")
    if skipped:
        return Verdict(ok=True, reasons=tuple(skipped), status="skipped")
    return Verdict(ok=True, status="approved")


def track_ledger(cache: ObservationCache, observation: object) -> None:
    """Keep ``cache.ledger_rows`` in step with the agent's own ledger.

    A whole ledger (reset, get_ledger) replaces the rows; an accepted log_meal appends its row
    and an accepted amend_meal replaces the row at its index. A refused action's observation is
    ``{"error": ...}`` and carries no row, so it changes nothing. Rows keep only food_id and
    grams: the observed row nutrients are already scaled by grams, and totals are recomputed
    per 100 g from the catalog.
    """
    if not isinstance(observation, dict):
        return
    whole = observation.get("ledger")
    if isinstance(whole, list):
        cache.ledger_rows = [
            {"food_id": row.get("food_id"), "grams": row.get("grams")}
            for row in whole
            if isinstance(row, dict)
        ]
        return
    row = observation.get("row")
    if cache.ledger_rows is None or not isinstance(row, dict):
        return
    entry = {"food_id": row.get("food_id"), "grams": row.get("grams")}
    op = observation.get("op")
    if op == "log_meal":
        cache.ledger_rows.append(entry)
    elif op == "amend_meal":
        index = observation.get("index")
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(
            cache.ledger_rows
        ):
            cache.ledger_rows[index] = entry


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    status: str  # not_applicable | skipped | approved | violation
    lines: tuple[str, ...] = ()
    totals: dict = field(default_factory=dict)
    windows: dict = field(default_factory=dict)
    occasion: str | None = None


def verify_plan(
    action: object,
    cache: ObservationCache,
    query: str = "",
    lookup: Callable[[str], dict | None] | None = None,
) -> VerifyResult:
    """Total a recommendation plan and compare it with the meal's windows.

    Only a ``submit_plan`` without a verdict is checked: an evaluate hand-in is scored against a
    pinned window and an exact candidate, which this check does not model. Windows come from the
    agent-visible profile and ledger through `judged_plan_windows`, never from the Oracle. Any
    gap in the data (a food without nutrients, an unknown ledger, an empty window intersection)
    skips the check: the gate may miss a violation but must not invent one.
    """
    if not isinstance(action, dict) or action.get("op") != "submit_plan":
        return VerifyResult(ok=True, status="not_applicable")
    if action.get("verdict") is not None:
        return VerifyResult(ok=True, status="not_applicable")
    plan, allergens, complete = scale_items(action.get("items") or [], cache.foods, lookup=lookup)
    lines: list[str] = []
    try:
        prohibited = set(normalize_tags(list(cache.profile.get("allergies") or [])))
    except ValueError:
        prohibited = set()
    if allergens & prohibited:
        lines.append("allergy: plan items carry " + ",".join(sorted(allergens & prohibited)))
    if not complete or cache.ledger_rows is None:
        if lines:
            return VerifyResult(ok=False, status="violation", lines=tuple(lines))
        return VerifyResult(ok=True, status="skipped")
    eaten, _tags, eaten_complete = scale_items(cache.ledger_rows, cache.foods, lookup=lookup)
    if not eaten_complete:
        if lines:
            return VerifyResult(ok=False, status="violation", lines=tuple(lines))
        return VerifyResult(ok=True, status="skipped")
    occasion = occasion_from_query(query)
    view = ObservationCache(profile=cache.profile, foods=cache.foods, ledger_totals=eaten)
    # No meal named: `judged_plan_windows` falls back to the snack share (0-100% of the day),
    # which is the daily remainder cap with no energy floor. It can miss a plan below a meal's
    # floor, never refuse one inside it.
    windows = judged_plan_windows(view, query)
    if not windows:
        if lines:
            return VerifyResult(ok=False, status="violation", lines=tuple(lines))
        return VerifyResult(ok=True, status="skipped")
    label = f"{occasion} " if occasion else "daily remaining (no meal named) "
    for key, (lo, hi) in windows.items():
        amount = plan.get(key, 0.0)
        unit = _UNITS.get(key, "g")
        if amount > judged_ceiling(key, hi) + _VERIFY_ROUNDING:
            lines.append(f"{key}: plan {amount:.1f} {unit} exceeds the {label}ceiling {hi:.1f} {unit}")
        elif amount < lo - _VERIFY_ROUNDING:
            lines.append(f"{key}: plan {amount:.1f} {unit} is below the {label}floor {lo:.1f} {unit}")
    if "high-protein" in query.lower() and not high_protein_pass(plan):
        lines.append("protein_share: requires at least 20% protein energy and 10 g protein")
    if not plan_mass_pass(action["items"], cache.plan_scope):
        lines.append("implausible_quantity: plan exceeds the published total mass limit")
    status = "violation" if lines else "approved"
    return VerifyResult(
        ok=not lines,
        status=status,
        lines=tuple(lines),
        totals={k: round(v, 3) for k, v in plan.items()},
        windows={k: [round(lo, 3), round(hi, 3)] for k, (lo, hi) in windows.items()},
        occasion=occasion,
    )


PREVIEW_HEADER = "Harness preview -- the plan was not submitted yet."
PREVIEW_FOOTER = "To submit it, repeat the same submit_plan; otherwise emit a different action."


def plan_preview(
    action: object,
    cache: ObservationCache,
    query: str = "",
    lookup: Callable[[str], dict | None] | None = None,
) -> dict | None:
    """Totals and graded range for a non-empty hand-in, or None when there is nothing to show.

    Unlike `verify_plan` this never judges: it returns numbers only, and it covers evaluate
    hand-ins too (an accept, or a reject carrying replacement items). The upper bound is the
    one the Scorer grades against (`judged_ceiling`), so a plan that passes never reads as over.
    """
    if not isinstance(action, dict) or action.get("op") != "submit_plan":
        return None
    items = action.get("items")
    if not isinstance(items, list) or not items:
        return None
    totals, _tags, complete = scale_items(items, cache.foods, lookup=lookup)
    if not complete or cache.ledger_rows is None:
        return None
    eaten, _tags, eaten_complete = scale_items(cache.ledger_rows, cache.foods, lookup=lookup)
    if not eaten_complete:
        return None
    view = ObservationCache(profile=cache.profile, foods=cache.foods, ledger_totals=eaten)
    windows = judged_plan_windows(view, query)
    if not windows:
        return None
    return {
        "occasion": occasion_from_query(query),
        "mass": {"total_grams": sum(item["grams"] for item in items),
                 **plan_limits_view(cache.plan_scope)},
        "totals": {key: round(totals.get(key, 0.0), 3) for key in windows},
        "range": {
            key: [round(lo, 3), round(judged_ceiling(key, hi), 3)]
            for key, (lo, hi) in windows.items()
        },
    }


def preview_text(preview: dict) -> str:
    def amount(key: str, value: float) -> str:
        unit = _UNITS.get(key, "g")
        return f"{value:.1f}" if unit == "kcal" else f"{value:.1f} {unit}"

    totals = ", ".join(f"{key} {amount(key, v)}" for key, v in preview["totals"].items())
    mass = preview["mass"]
    totals += f", total mass {mass['total_grams']:.1f} g / {mass['max_total_grams']:.1f} g maximum"
    bounds = []
    for key, (lo, hi) in preview["range"].items():
        bounds.append(
            f"{key} {amount(key, lo)}-{amount(key, hi)}" if lo > 0 else f"{key} <= {amount(key, hi)}"
        )
    occasion = preview.get("occasion")
    label = f"{occasion.capitalize()} allowed range" if occasion else (
        "Daily remaining allowed range (no meal named)"
    )
    return (
        f"{PREVIEW_HEADER}\nPlan totals: {totals}\n{label}: {', '.join(bounds)}\n{PREVIEW_FOOTER}"
    )


def plan_key(action: object, lookup: Callable[[str], dict | None] | None = None) -> tuple | None:
    """What makes two hand-ins the same plan for Env and the Scorer, or None if not a plan.

    Grams are summed per canonical food (order and split rows do not matter); with items, a
    missing verdict is an accept; reasons count only on a reject, compared as closed codes.
    """
    if not isinstance(action, dict) or action.get("op") != "submit_plan":
        return None
    grams: dict[str, float] = {}
    for item in action.get("items") or []:
        if not isinstance(item, dict):
            continue
        food_id = str(item.get("food_id"))
        entry = lookup(food_id) if lookup is not None else None
        if isinstance(entry, dict) and entry.get("fdc_id") is not None:
            food_id = str(entry["fdc_id"])
        amount = item.get("grams")
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            grams[food_id] = grams.get(food_id, 0.0) + float(amount)
    verdict = action.get("verdict") or ("accept" if grams else None)
    reasons: tuple = ()
    if verdict == "reject":
        try:
            reasons = normalize_reasons(action.get("reasons") or [])
        except ValueError:
            reasons = tuple(sorted(str(r) for r in action.get("reasons") or []))
    return (tuple(sorted((k, round(v, 6)) for k, v in grams.items())), verdict, reasons)


class BuddyHarness(Harness):
    """ReAct plus optional pin / calculator / pre-submit regenerate."""

    def __init__(
        self,
        inner: Harness,
        *,
        pin: bool = False,
        calc: bool = False,
        check: bool = False,
        max_regen: int = 2,
        resample: int = 0,
        food_lookup: Callable[[str], dict | None] | None = None,
        label: str | None = None,
        verify: bool = False,
        placebo: bool = False,
        preview: bool = False,
    ) -> None:
        if max_regen < 0:
            raise ValueError("max_regen must be >= 0")
        if resample < 0:
            raise ValueError("resample must be >= 0")
        self.inner = inner
        self.pin = pin
        self.calc = calc
        self.check = check
        self.max_regen = max_regen
        self.resample = resample
        self.food_lookup = food_lookup
        self._label = label
        self.verify = verify
        self.placebo = placebo
        self.preview = preview
        # The last plan shown in a preview: repeating it confirms it, and what reaches Env is
        # this stored plan, not the model's re-statement.
        self._previewed: tuple | None = None
        # One entry per verify bounce, written before `revise` replaces the action: the bounced
        # plan is what the counterfactual replay submits, and nothing else records it.
        self.verify_events: list[dict] = []
        self.verify_status: dict[str, int] = {}
        # Bounces after which the model answered with something other than a hand-in (a read,
        # a log): the treatment then changed the trajectory, not just the plan.
        self.verify_drift = 0
        self.cache = ObservationCache()
        self._pinned = False
        self._pin_message: dict | None = None
        self.regen_fired = 0     # gate rejections observed
        self.regen_used = 0      # extra completions actually spent
        self.gate_exhausted = 0  # bounced with no re-ask left, or budget spent
        # Tally of what the gate did, by Verdict.status. Without it an arm cannot tell a gate
        # that checked and found nothing from one that could not check at all.
        self.gate_status: dict[str, int] = {}
        # Which hand-in shapes the gate refused, keyed `submit_plan:verdict` vs `submit_plan`.
        # `Verdict.status` says what the check did, not what it did it to -- and an evaluate
        # submit carries a verdict and is scored against a pinned candidate, so a bounce there
        # costs more than a bounce on a recommendation. Without the shape, that rate is not
        # measurable from a run.
        self.gate_fired_shapes: dict[str, int] = {}
        self._apply_sandbox_line()

    def set_step_budget(self, max_steps: int) -> None:
        """Forward to the wrapped harness: its prompt is the one that renders the budget."""
        self.inner.set_step_budget(max_steps)

    @property
    def label(self) -> str:
        if self._label:
            return self._label
        bits = ["buddy"]
        if self.pin:
            bits.append("pin")
        if self.calc:
            bits.append("calc")
        if self.check:
            bits.append("check")
        return "-".join(bits) if len(bits) > 1 else "buddy"

    def clone(self) -> BuddyHarness:
        inner = self.inner.clone() if hasattr(self.inner, "clone") else self.inner
        # Every field that changes behaviour must be carried over: run_ablation clones one
        # template per task, and a dropped food_lookup/resample silently disabled the
        # catalog-aware gate and the resample control in every real episode.
        return BuddyHarness(
            inner,
            pin=self.pin,
            calc=self.calc,
            check=self.check,
            max_regen=self.max_regen,
            resample=self.resample,
            food_lookup=self.food_lookup,
            label=self._label,
            verify=self.verify,
            placebo=self.placebo,
            preview=self.preview,
        )

    def reset(self, task: object | None = None) -> None:
        reset = getattr(self.inner, "reset", None)
        if callable(reset):
            reset(task)
        self.cache.clear()
        self._pinned = False
        self._pin_message = None
        self.regen_fired = 0
        self.regen_used = 0
        self.gate_exhausted = 0
        # Per episode, like the counters above it. A caller that reuses one harness for several
        # episodes (the runner's `fresh=False` path with k > 1) otherwise reads the previous
        # episode's checks as this episode's.
        self.gate_status = {}
        self.gate_fired_shapes = {}
        self.verify_events = []
        self.verify_status = {}
        self.verify_drift = 0
        self._previewed = None
        self._apply_sandbox_line()

    def act(self, observation: dict, query: str, history: list) -> dict:
        ingest_observation(self.cache, observation)
        track_ledger(self.cache, observation)
        ensure_task = getattr(self.inner, "ensure_task", None)
        if callable(ensure_task):
            ensure_task(query)
        if self.pin:
            self._ensure_pin()
        presented = self._enrich(observation, query) if self.calc else observation
        action: dict = self.inner.act(presented, query, history)
        revise: Callable[[str], dict] | None = getattr(self.inner, "revise", None)

        if self.preview:
            return self._preview(action, query, len(history), revise)
        if self.verify:
            return self._verify(action, query, len(history), revise)

        if self.check:
            for _ in range(self.max_regen):
                verdict = check_write(
                    action, self.cache, query=query, lookup=self.food_lookup
                )
                self.gate_status[verdict.status] = self.gate_status.get(verdict.status, 0) + 1
                if verdict.ok:
                    return action
                self.regen_fired += 1
                self._tally_fired_shape(action)
                if not callable(revise):
                    # Bounced, but nothing can re-ask: the action goes to the env as-is.
                    self.gate_exhausted += 1
                    return action
                action = revise(self._bounce_text(verdict.reasons))
                self.regen_used += 1
            # Budget spent: the last action reached the env without a final verdict.
            self.gate_exhausted += 1
            return action

        if self.resample > 0:
            # Non-semantic control arm: spend the same number of extra completions with no
            # verdict at all, so "more sampling" is separable from "semantic gating".
            for _ in range(self.resample):
                if not callable(revise):
                    break
                action = revise("Emit one JSON action.")
                self.regen_used += 1
        return action

    def _verify(self, action: dict, query: str, env_steps: int,
                revise: Callable[[str], dict] | None) -> dict:
        """Bounce out-of-window recommendations at most ``max_regen`` times per episode.

        The cap is per episode, not per step: a model that keeps re-submitting would otherwise be
        bounced on every later step, and the treatment would become "unbounded refusals".
        """
        attempt = 0
        while True:
            result = verify_plan(action, self.cache, query=query, lookup=self.food_lookup)
            self.verify_status[result.status] = self.verify_status.get(result.status, 0) + 1
            if result.ok:
                return action
            if len(self.verify_events) >= self.max_regen or not callable(revise):
                self.gate_exhausted += 1
                return action
            if self.placebo:
                text = f"{VERIFY_HEADER}\n{VERIFY_PLACEBO_BODY}\nEmit one JSON action."
            else:
                text = f"{VERIFY_HEADER}\n" + "\n".join(result.lines) + "\nEmit one JSON action."
            self.verify_events.append(
                {
                    "env_steps_before": env_steps,
                    "attempt": attempt,
                    "action": copy.deepcopy(action),
                    "lines": list(result.lines),
                    "totals": result.totals,
                    "windows": result.windows,
                    "occasion": result.occasion,
                    "feedback": text,
                }
            )
            self.regen_fired += 1
            action = revise(text)
            self.regen_used += 1
            attempt += 1
            if not (isinstance(action, dict) and action.get("op") == "submit_plan"):
                self.verify_drift += 1

    def _preview(self, action: dict, query: str, env_steps: int,
                 revise: Callable[[str], dict] | None) -> dict:
        """Show each new non-empty hand-in's numbers before Env sees it; at most max_regen times.

        Repeating the previewed plan commits the stored plan. A different plan is previewed
        again while previews remain; after that it goes to Env as-is. Any other action goes to
        Env as a normal step. Events are written before `revise`, as for verify.
        """
        while True:
            key = plan_key(action, self.food_lookup)
            if key is None:
                return action
            if self._previewed is not None and key == self._previewed[0]:
                self._tally_status("confirmed")
                return copy.deepcopy(self._previewed[1])
            shown = plan_preview(action, self.cache, query=query, lookup=self.food_lookup)
            if shown is None:
                self._tally_status("skipped")
                return action
            if len(self.verify_events) >= self.max_regen or not callable(revise):
                self._tally_status("cap_reached")
                return action
            text = preview_text(shown)
            self.verify_events.append(
                {
                    "kind": "preview",
                    "env_steps_before": env_steps,
                    "action": copy.deepcopy(action),
                    "totals": shown["totals"],
                    "range": shown["range"],
                    "occasion": shown["occasion"],
                    "feedback": text,
                }
            )
            self._tally_status("previewed")
            self._previewed = (key, copy.deepcopy(action))
            self.regen_fired += 1
            action = revise(text)
            self.regen_used += 1
            if not (isinstance(action, dict) and action.get("op") == "submit_plan"):
                self.verify_drift += 1
                return action

    def _tally_status(self, status: str) -> None:
        self.verify_status[status] = self.verify_status.get(status, 0) + 1

    def _tally_fired_shape(self, action: object) -> None:
        """Count a refusal by hand-in shape: an evaluate submit carries a verdict."""
        op = action.get("op") if isinstance(action, dict) else None
        verdict = action.get("verdict") if isinstance(action, dict) else None
        shape = f"{op}:verdict" if verdict else str(op)
        self.gate_fired_shapes[shape] = self.gate_fired_shapes.get(shape, 0) + 1

    def _apply_sandbox_line(self) -> None:
        if not self.calc:
            return
        messages = getattr(self.inner, "messages", None)
        if not isinstance(messages, list) or not messages:
            return
        first = messages[0]
        if not isinstance(first, dict) or first.get("role") != "system":
            return
        content = str(first.get("content") or "")
        if SANDBOX_LINE in content:
            return
        messages[0] = {**first, "content": content + "\n" + SANDBOX_LINE}

    def _ensure_pin(self) -> None:
        """Insert the pinned constraints, and refresh them when the profile changes.

        A pin written once goes stale the moment an update task edits the profile, and the
        arm would then be measuring "stale memory" rather than "memory". The existing
        message is rewritten in place; if a context slide dropped it, it is re-inserted.
        """
        if not self.cache.profile:
            return
        messages = getattr(self.inner, "messages", None)
        if not isinstance(messages, list):
            return
        payload = {
            "allergies": sorted(self.cache.profile.get("allergies") or []),
            "windows": self.cache.profile.get("windows") or {},
        }
        text = "Pinned constraints:\n" + json.dumps(payload, default=str)
        if self._pin_message is not None and any(
            m is self._pin_message for m in messages
        ):
            if self._pin_message.get("content") != text:
                self._pin_message["content"] = text
            return
        pin = {"role": "user", "content": text}
        insert_at = 1
        if (
            len(messages) > 1
            and messages[1].get("role") == "user"
            and str(messages[1].get("content", "")).startswith("Task:")
        ):
            insert_at = 2
        messages.insert(insert_at, pin)
        self._pin_message = pin
        self._pinned = True

    def _enrich(self, observation: dict, query: str = "") -> dict:
        enriched = copy.deepcopy(observation)
        enriched["sandbox"] = sandbox_sheet(self.cache, query=query)
        return enriched

    @staticmethod
    def _bounce_text(reasons: tuple[str, ...]) -> str:
        joined = "; ".join(reasons) if reasons else "plan failed a harness check"
        # Strip numeric targets: quoting the exact bounds turned the gate into a hint.
        joined = re.sub(r"-?\d+(?:\.\d+)?", "·", joined)
        return (
            "Harness check rejected the previous action before it reached the "
            "environment. Do not repeat it. Emit one new JSON action.\n"
            f"Reasons: {joined}"
        )


def build_scaffold(
    scaffold: str,
    *,
    inner: ReActHarness | None = None,
    food_lookup: Callable[[str], dict | None] | None = None,
    **react_kwargs,
) -> Harness:
    """Wrap a ReAct loop in one policy scaffold. Unknown names raise.

    ``food_lookup`` is handed to the gate so it can score a plan naming a food the model
    never fetched; without it the gate silently degrades to "only what the model saw".
    """
    if scaffold not in SCAFFOLDS:
        raise ValueError(f"unknown scaffold {scaffold!r}; choose from {sorted(SCAFFOLDS)}")
    flags = SCAFFOLDS[scaffold]
    kwargs = dict(react_kwargs)
    kwargs.setdefault("version", "v2")
    react = inner if inner is not None else ReActHarness(**kwargs)
    if scaffold == "none":
        return react
    # Named arguments, not **flags: the table says *whether* a scaffold resamples, and this
    # is where the count lives. Unpacking would hide which key is which at the call site.
    return BuddyHarness(
        react,
        label=scaffold,
        food_lookup=food_lookup,
        pin=flags["pin"],
        calc=flags["calc"],
        check=flags["check"],
        resample=2 if flags.get("resample") else 0,
        verify=bool(flags.get("verify")),
        placebo=bool(flags.get("placebo")),
        preview=bool(flags.get("preview")),
    )
