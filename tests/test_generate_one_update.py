"""Ticket 08: generate_one Update mill — template fills + implicit bands."""

from __future__ import annotations

import pytest

from nutrienv.bench.pipeline.generate_one import generate_one
from nutrienv.bench.pipeline.roster import ROSTER
from nutrienv.bench.scorer import Scorer
from nutrienv.env import NutriEnv
from nutrienv.world.daily_windows import derive_profile_windows
from nutrienv.world.types import Profile


def _food(name, portions, aliases=(), allergen_tags=(), nutrients=None):
    return {
        "name": name,
        "portions": dict(portions),
        "aliases": list(aliases),
        "allergen_tags": list(allergen_tags),
        "nutrients": dict(nutrients or {}),
    }


def _catalog() -> dict:
    return {
        "shrimp": _food("Shrimp, cooked", {"piece": 25.0}, ("shrimp",), ("shellfish",)),
        "milk_whole": _food("Milk, whole", {"cup": 244.0}, ("milk",), ("milk",)),
    }


def _run(**overrides):
    kwargs = dict(
        catalog=_catalog(),
        family="update",
        seed=0,
        person=ROSTER[3],
    )
    kwargs.update(overrides)
    return generate_one(**kwargs)


def _replay_to_pass(task, actions) -> None:
    env = NutriEnv()
    env.reset(task.s0)
    for action in actions:
        out = env.step(action)
        assert out.get("ok"), action
    assert Scorer().score(env.state(), task.oracle) == {
        "passed": True,
        "tag": "pass",
    }


def test_add_allergy_shell_fills_spoken_food_and_expands_the_tag() -> None:
    result = _run(shell="upd-add-allergy", slots={"food": "shrimp"})
    assert result.rejected is None
    task = result.accepted
    assert task.family == "update"
    assert task.query == (
        "I just found out I'm allergic to shrimp. Add that to my profile."
    )
    expected = Profile(
        user_id=task.s0.profile.user_id,
        allergies=("shellfish",),
        windows=task.s0.profile.windows,
        sex=task.s0.profile.sex,
        age_y=task.s0.profile.age_y,
        height_cm=task.s0.profile.height_cm,
        weight_kg=task.s0.profile.weight_kg,
        activity=task.s0.profile.activity,
        phase=task.s0.profile.phase,
    )
    assert task.oracle.profile == expected
    assert task.oracle.update_band is None
    _replay_to_pass(task, [{"op": "update_profile", "patch": {"allergies": ["shrimp"]}}])


def test_rm_allergy_removes_only_that_tag() -> None:
    ada = ROSTER[0]
    result = _run(
        person=ada, shell="upd-rm-allergy", slots={"allergen": "peanut"}
    )
    assert result.rejected is None
    task = result.accepted
    assert task.query == (
        "I got tested — I'm not actually allergic to peanut. "
        "Take that off my list."
    )
    assert task.oracle.profile.allergies == ()
    _replay_to_pass(task, [{"op": "update_profile", "patch": {"allergies": []}}])


def test_weight_update_rederives_windows_in_the_world() -> None:
    result = _run(shell="upd-weight", slots={"n": "70"})
    assert result.rejected is None
    task = result.accepted
    assert task.query == "I weigh 70 kg now. Update my weight."
    expected = Profile(
        user_id=task.s0.profile.user_id,
        allergies=task.s0.profile.allergies,
        windows=derive_profile_windows(
            Profile(
                user_id=task.s0.profile.user_id,
                sex=task.s0.profile.sex,
                age_y=task.s0.profile.age_y,
                height_cm=task.s0.profile.height_cm,
                weight_kg=70.0,
                activity=task.s0.profile.activity,
                phase=task.s0.profile.phase,
            )
        ),
        sex=task.s0.profile.sex,
        age_y=task.s0.profile.age_y,
        height_cm=task.s0.profile.height_cm,
        weight_kg=70.0,
        activity=task.s0.profile.activity,
        phase=task.s0.profile.phase,
    )
    assert task.oracle.profile == expected
    _replay_to_pass(task, [{"op": "update_profile", "patch": {"weight_kg": 70.0}}])


def test_explicit_kcal_shift_is_an_exact_window_oracle() -> None:
    result = _run(shell="upd-kcal-explicit", slots={"n": "200"})
    assert result.rejected is None
    task = result.accepted
    assert task.query == "Raise my calorie range by 200 at both ends."
    lo, hi = task.s0.profile.windows["kcal"]
    expected = Profile(
        user_id=task.s0.profile.user_id,
        allergies=task.s0.profile.allergies,
        windows={**task.s0.profile.windows, "kcal": (lo + 200.0, hi + 200.0)},
        sex=task.s0.profile.sex,
        age_y=task.s0.profile.age_y,
        height_cm=task.s0.profile.height_cm,
        weight_kg=task.s0.profile.weight_kg,
        activity=task.s0.profile.activity,
        phase=task.s0.profile.phase,
    )
    assert task.oracle.profile == expected
    _replay_to_pass(
        task,
        [
            {
                "op": "update_profile",
                "patch": {"windows": {"kcal": [lo + 200.0, hi + 200.0]}},
            }
        ],
    )


def test_implicit_cut_uses_the_cut_band() -> None:
    result = _run(person=ROSTER[3], shell="upd-phase-cut")
    assert result.rejected is None
    task = result.accepted
    assert task.query == "I'm cutting now."
    oracle = task.oracle
    assert oracle.update_band == "cut"
    # Band baseline: S0 windows unchanged, phase names the intent.
    assert oracle.profile.windows == task.s0.profile.windows
    assert oracle.profile.phase == "cut"
    assert oracle.profile.allergies == task.s0.profile.allergies
    _replay_to_pass(task, [{"op": "update_profile", "patch": {"phase": "cut"}}])


def test_implicit_muscle_uses_the_muscle_band() -> None:
    result = _run(person=ROSTER[3], shell="upd-phase-muscle")
    assert result.rejected is None
    task = result.accepted
    assert task.query == "I want to start building muscle."
    assert task.oracle.update_band == "muscle"
    assert task.oracle.profile.windows == task.s0.profile.windows
    _replay_to_pass(task, [{"op": "update_profile", "patch": {"phase": "muscle"}}])


def test_fatigue_on_a_cut_person_uses_the_fatigue_band() -> None:
    cutter = ROSTER[2]
    result = _run(person=cutter, shell="upd-fatigue")
    assert result.rejected is None
    task = result.accepted
    assert task.query == "I've been exhausted. Can we ease the deficit a bit?"
    assert task.oracle.update_band == "fatigue"
    assert task.oracle.profile.windows == task.s0.profile.windows

    # Doing nothing fails: the deficit is not eased.
    env = NutriEnv()
    env.reset(task.s0)
    assert Scorer().score(env.state(), task.oracle)["passed"] is False

    # Easing the deficit (phase back to maintain re-derives windows) passes.
    _replay_to_pass(task, [{"op": "update_profile", "patch": {"phase": "maintain"}}])

    # A direct kcal move inside the band also passes.
    from nutrienv.world.daily_windows import estimated_energy_requirement

    eer_hi = task.s0.profile.windows["kcal"][1]
    maintain_eer = estimated_energy_requirement(
        sex=cutter.sex,
        age_y=cutter.age_y,
        height_cm=cutter.height_cm,
        weight_kg=cutter.weight_kg,
        activity=cutter.activity,
    )
    eased = (eer_hi + maintain_eer) / 2.0
    _replay_to_pass(
        task,
        [{"op": "update_profile", "patch": {"windows": {"kcal": [eased, eased]}}}],
    )


def test_stop_the_cut_is_an_exact_maintain_update() -> None:
    cutter = ROSTER[2]
    result = _run(person=cutter, shell="upd-phase-maintain")
    assert result.rejected is None
    task = result.accepted
    assert task.query == "Stop the cut — maintain for a while."
    assert task.oracle.update_band is None
    expected = Profile(
        user_id=task.s0.profile.user_id,
        allergies=task.s0.profile.allergies,
        windows=derive_profile_windows(task.oracle.profile),
        sex=task.s0.profile.sex,
        age_y=task.s0.profile.age_y,
        height_cm=task.s0.profile.height_cm,
        weight_kg=task.s0.profile.weight_kg,
        activity=task.s0.profile.activity,
        phase="maintain",
    )
    assert task.oracle.profile == expected
    _replay_to_pass(task, [{"op": "update_profile", "patch": {"phase": "maintain"}}])


def test_short_allergy_and_gym_person_slots_fill_verbatim() -> None:
    hao = ROSTER[7]
    short = _run(
        person=hao, shell="upd-add-allergy-short", slots={"allergen": "egg"}
    )
    assert short.accepted is not None
    assert short.accepted.query == "Add egg to my allergies."
    assert set(short.accepted.oracle.profile.allergies) == {"peanut", "shellfish", "egg"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"person": ROSTER[3], "shell": "upd-rm-allergy", "slots": {"allergen": "peanut"}},
        {"person": ROSTER[0], "shell": "upd-add-allergy-short", "slots": {"allergen": "peanut"}},
        {"person": ROSTER[3], "shell": "upd-fatigue"},
        {"person": ROSTER[3], "shell": "upd-phase-maintain"},
        {"person": ROSTER[2], "shell": "upd-phase-cut"},
    ],
)
def test_degenerate_or_impossible_updates_are_rejected(kwargs) -> None:
    kwargs = {**kwargs, "catalog": _catalog()}
    result = _run(**kwargs)
    assert result.accepted is None
    assert result.rejected is not None


def test_react_manual_covers_new_update_speech() -> None:
    from nutrienv.harness.react import react_manual

    manual = react_manual("v1").lower()
    assert "weigh" in manual
    assert "maintain" in manual
