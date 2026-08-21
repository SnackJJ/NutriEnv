"""Replay each Oracle through Env and report which items cannot be Passed.

This is the dynamic gate after freeze. ``validate_draft`` stays the static
draft-time gate. Callers pass a loaded split (not a path) and choose whether
to assert, print, or drop ids.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from nutrienv.env import NutriEnv
from nutrienv.world.daily_windows import estimated_energy_requirement

from .realize import Oracle, Task, scored_oracles
from .scorer import Scorer
from .validator import fitting_plan

__all__ = ["AchievabilityReport", "SCORED_FEATURES", "check_achievable"]

SCORED_FEATURES = (
    "ledger_tail",
    "exact_plan",
    "any_plan",
    "allow_empty_plan",
    "plan_windows",
    "last_verdict",
    "update_band",
    "body_facts",
    "evaluated_plan",
    "bound_labels",
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
        by_family=dict(families),
        by_feature={name: features[name] for name in SCORED_FEATURES},
    )


def _reachable(task: Task, scorer: Scorer) -> bool:
    env = NutriEnv()
    env.reset(task.s0)
    for oracle in scored_oracles(task.oracle):
        if not _replay_oracle(env, task, oracle):
            return False
    return scorer.score(env.state(), task.oracle)["passed"] is True


def _replay_oracle(env: NutriEnv, task: Task, oracle: Oracle) -> bool:
    if oracle.ledger_tail:
        for row in oracle.ledger_tail:
            if row in env.state().ledger:
                continue
            stepped = env.step(
                {
                    "op": "log_meal",
                    "food_id": row.food_id,
                    "grams": row.grams,
                    "eaten_at": row.eaten_at,
                }
            )
            if not stepped.get("ok"):
                return False
    if not _replay_profile(env, oracle):
        return False
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
    elif oracle.last_plan == []:
        windows = oracle.plan_windows or env.state().profile.windows
        plan = fitting_plan(
            task.s0.catalog, windows, env.state().profile.allergies
        )
        if plan is None:
            return False
        stepped = env.step({"op": "submit_plan", "items": plan})
        if not stepped.get("ok"):
            return False
    return True


_BODY_KEYS = frozenset({"sex", "age_y", "height_cm", "weight_kg", "activity", "phase"})


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
    if _BODY_KEYS & patch.keys():
        patch.pop("windows", None)
    stepped = env.step({"op": "update_profile", "patch": patch})
    return bool(stepped.get("ok"))


def _replay_band(env: NutriEnv, current, expected, band: str) -> bool:
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
    if _has_body_facts(task.s0.profile):
        names.add("body_facts")
    for oracle in scored_oracles(task.oracle):
        if oracle.ledger_tail:
            names.add("ledger_tail")
        if oracle.last_plan:
            names.add("exact_plan")
        elif oracle.last_plan == []:
            names.add("any_plan")
        if oracle.allow_empty_plan:
            names.add("allow_empty_plan")
        if oracle.plan_windows:
            names.add("plan_windows")
        if oracle.last_verdict is not None:
            names.add("last_verdict")
        if oracle.update_band:
            names.add("update_band")
        if oracle.evaluated_plan:
            names.add("evaluated_plan")
        if oracle.bound_labels:
            names.add("bound_labels")
        if oracle.profile is not None and _has_body_facts(oracle.profile):
            names.add("body_facts")
    return names


def _has_body_facts(profile) -> bool:
    return any(
        getattr(profile, key) is not None
        for key in ("sex", "age_y", "height_cm", "weight_kg", "activity")
    )


def _fatigue_kcal(profile) -> tuple[float, float] | None:
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


def _profile_patch(current, expected) -> dict:
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
