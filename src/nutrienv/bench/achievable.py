"""Replay each Oracle through Env and report which items cannot be Passed.

This is the dynamic gate after freeze. ``validate_draft`` stays the static
draft-time gate. Callers pass a loaded split (not a path) and choose whether
to assert, print, or drop ids.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from nutrienv.env import NutriEnv
from nutrienv.world.daily_windows import derive_profile_windows, estimated_energy_requirement
from nutrienv.world.types import LedgerRow, Profile, normalize_tags

from .realize import FAMILIES, Oracle, Task, scored_oracles
from .scorer import Scorer
from .validator import fitting_plan

__all__ = ["AchievabilityReport", "SCORED_FEATURES", "check_achievable"]

# Oracle fields Scorer actually judges, plus body_facts on a scored profile
# (the 04 freeze hole). evaluated_plan and bound_labels are not scored.
SCORED_FEATURES = (
    "ledger_tail",
    "ledger",
    "last_plan",
    "plan_must_be_safe",
    "plan_must_fit_windows",
    "allow_empty_plan",
    "plan_windows",
    "last_verdict",
    "last_reasons",
    "update_band",
    "profile",
    "body_facts",
    "sub_oracles",
)


@dataclass(frozen=True)
class AchievabilityReport:
    unreachable: tuple[str, ...]
    by_family: dict[str, int]
    by_feature: dict[str, int]


def check_achievable(tasks: Sequence[Task]) -> AchievabilityReport:
    """Replay each Task's Oracle via legal Env actions. Never asserts."""
    scorer = Scorer()
    unreachable: list[str] = []
    families: Counter[str] = Counter()
    features: Counter[str] = Counter()
    for task in tasks:
        families[task.family] += 1
        for name in _features(task):
            features[name] += 1
        if not _reachable(task, scorer):
            unreachable.append(task.id)
    return AchievabilityReport(
        unreachable=tuple(unreachable),
        by_family={name: families[name] for name in FAMILIES},
        by_feature={name: features[name] for name in SCORED_FEATURES},
    )


def _reachable(task: Task, scorer: Scorer) -> bool:
    env = NutriEnv()
    env.reset(task.s0)
    for oracle in scored_oracles(task.oracle):
        if not _replay_oracle(env, task, oracle, scorer):
            return False
    return scorer.score(env.state(), task.oracle)["passed"] is True


def _replay_oracle(
    env: NutriEnv, task: Task, oracle: Oracle, scorer: Scorer
) -> bool:
    if not _replay_ledger(env, oracle):
        return False
    if not _replay_profile(env, oracle):
        return False
    if scorer.score(env.state(), oracle)["passed"] is True:
        return True
    if oracle.last_verdict == "reject":
        action: dict = {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
        }
        if oracle.last_reasons:
            action["reasons"] = list(oracle.last_reasons)
        stepped = env.step(action)
        if not stepped.get("ok"):
            return False
        return True
    if oracle.last_plan:
        stepped = env.step({"op": "submit_plan", "items": oracle.last_plan})
        if not stepped.get("ok"):
            return False
    elif oracle.allow_empty_plan:
        stepped = env.step({"op": "submit_plan", "items": []})
        if not stepped.get("ok"):
            return False
    elif (
        oracle.last_plan == []
        or oracle.plan_must_be_safe
        or oracle.plan_must_fit_windows
    ):
        allergies = env.state().profile.allergies
        if oracle.plan_must_fit_windows or oracle.plan_windows is not None:
            windows = (
                oracle.plan_windows
                if oracle.plan_windows is not None
                else env.state().profile.windows
            )
            plan = fitting_plan(task.s0.catalog, windows, allergies)
        else:
            plan = _any_safe_plan(task.s0.catalog, allergies)
        if plan is None:
            return False
        stepped = env.step({"op": "submit_plan", "items": plan})
        if not stepped.get("ok"):
            return False
    return True


_BODY_KEYS = frozenset({"sex", "age_y", "height_cm", "weight_kg", "activity", "phase"})


def _replay_ledger(env: NutriEnv, oracle: Oracle) -> bool:
    """Append the Oracle's new rows. Membership is not identity; duplicates count."""
    if oracle.ledger is not None:
        current = list(env.state().ledger)
        expected = list(oracle.ledger)
        if current == expected:
            return True
        if expected[: len(current)] != current:
            return False
        to_log = expected[len(current) :]
    elif oracle.ledger_tail:
        to_log = list(oracle.ledger_tail)
    else:
        return True
    for row in to_log:
        if not _log_row(env, row):
            return False
    return True


def _log_row(env: NutriEnv, row: LedgerRow) -> bool:
    stepped = env.step(
        {
            "op": "log_meal",
            "food_id": row.food_id,
            "grams": row.grams,
            "eaten_at": row.eaten_at,
        }
    )
    return bool(stepped.get("ok"))


def _any_safe_plan(catalog, allergies) -> list[dict] | None:
    """Any 1 g allergen-safe item Scorer can score. Windows are not judged."""
    try:
        banned = set(normalize_tags(list(allergies)))
    except ValueError:
        return None
    for food_id, entry in catalog.items():
        if not _scorer_legal_food(entry, banned):
            continue
        return [{"food_id": food_id, "grams": 1.0}]
    return None


def _scorer_legal_food(entry: object, banned: set[str]) -> bool:
    if not isinstance(entry, dict):
        return False
    try:
        tags = set(normalize_tags(entry.get("allergen_tags") or []))
    except ValueError:
        return False
    if tags & banned:
        return False
    nutrients = entry.get("nutrients")
    if not isinstance(nutrients, dict):
        return False
    for amount in nutrients.values():
        if (
            not isinstance(amount, (int, float))
            or isinstance(amount, bool)
            or not math.isfinite(amount)
        ):
            return False
    return True


def _replay_profile(env: NutriEnv, oracle: Oracle) -> bool:
    expected = oracle.profile
    if expected is None:
        return True
    current = env.state().profile
    if oracle.update_band:
        return _replay_band(env, current, expected, oracle.update_band)
    if current == expected:
        return True
    patch = _profile_patch(current, expected)
    if not patch:
        return True
    body_patch = {key: patch[key] for key in _BODY_KEYS if key in patch}
    if body_patch and derive_profile_windows(replace(current, **body_patch)) is not None:
        patch.pop("windows", None)
    stepped = env.step({"op": "update_profile", "patch": patch})
    return bool(stepped.get("ok"))


def _replay_band(
    env: NutriEnv, current: Profile, expected: Profile, band: str
) -> bool:
    patch = _profile_patch(current, expected)
    patch.pop("windows", None)
    if band == "cut" and "phase" not in patch:
        patch["phase"] = "cut"
    elif band == "muscle" and "phase" not in patch:
        patch["phase"] = "muscle"
    elif band == "fatigue" and "phase" not in patch:
        if current.phase == "cut":
            patch["phase"] = "maintain"
        else:
            eased = _fatigue_kcal(current)
            if eased is not None:
                patch["windows"] = {"kcal": list(eased)}
    if not patch:
        return True
    stepped = env.step({"op": "update_profile", "patch": patch})
    return bool(stepped.get("ok"))


def _features(task: Task) -> set[str]:
    names: set[str] = set()
    if task.oracle.sub_oracles:
        names.add("sub_oracles")
    for oracle in scored_oracles(task.oracle):
        if oracle.ledger_tail is not None:
            names.add("ledger_tail")
        if oracle.ledger is not None:
            names.add("ledger")
        if oracle.last_plan is not None:
            names.add("last_plan")
        if oracle.plan_must_be_safe:
            names.add("plan_must_be_safe")
        if oracle.plan_must_fit_windows:
            names.add("plan_must_fit_windows")
        if oracle.allow_empty_plan:
            names.add("allow_empty_plan")
        if oracle.plan_windows is not None:
            names.add("plan_windows")
        if oracle.last_verdict is not None:
            names.add("last_verdict")
        if oracle.last_verdict == "reject" or oracle.last_reasons:
            names.add("last_reasons")
        if oracle.update_band:
            names.add("update_band")
        if oracle.profile is not None:
            names.add("profile")
            if _has_body_facts(oracle.profile):
                names.add("body_facts")
    return names


def _has_body_facts(profile: Profile) -> bool:
    return any(
        getattr(profile, key) is not None
        for key in ("sex", "age_y", "height_cm", "weight_kg", "activity")
    )


def _fatigue_kcal(profile: Profile) -> tuple[float, float] | None:
    if (
        profile.sex is None
        or profile.age_y is None
        or profile.height_cm is None
        or profile.weight_kg is None
        or profile.activity is None
        or "kcal" not in profile.windows
    ):
        return None
    eer = estimated_energy_requirement(
        sex=profile.sex,
        age_y=profile.age_y,
        height_cm=profile.height_cm,
        weight_kg=profile.weight_kg,
        activity=profile.activity,
    )
    s0_hi = profile.windows["kcal"][1]
    eased = (s0_hi + eer) / 2.0
    return (eased, eased)


def _profile_patch(current: Profile, expected: Profile) -> dict:
    patch: dict = {}
    if expected.allergies != current.allergies:
        patch["allergies"] = list(expected.allergies)
    if expected.medications != current.medications:
        patch["medications"] = list(expected.medications)
    if expected.windows != current.windows:
        patch["windows"] = {
            key: list(bounds) for key, bounds in expected.windows.items()
        }
    if expected.plan_preset != current.plan_preset:
        patch["plan_preset"] = dict(expected.plan_preset)
    if expected.version != current.version:
        patch["version"] = expected.version
    for key in _BODY_KEYS:
        want = getattr(expected, key)
        if want != getattr(current, key):
            patch[key] = want
    return patch
