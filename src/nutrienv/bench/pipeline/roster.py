"""Adult roster people for mill worlds. Windows are derived, never stored here."""

from __future__ import annotations

import random
from dataclasses import dataclass

from nutrienv.world.daily_windows import derive_profile_windows
from nutrienv.world.types import Profile

__all__ = ["ROSTER", "RosterPerson", "profile_for", "sample_roster_person"]


@dataclass(frozen=True)
class RosterPerson:
    user_id: str
    sex: str
    age_y: int
    height_cm: float
    weight_kg: float
    activity: str
    phase: str = "maintain"
    allergies: tuple[str, ...] = ()
    persona: str = "everyday"
    diet_style: str = "standard"


# ~20 adults, ages 19–75. Children, pregnancy, and 80+ stay out (ADR 0014).
ROSTER: tuple[RosterPerson, ...] = (
    RosterPerson("roster-ada", "female", 34, 165.0, 62.0, "light", "maintain", ("peanut",)),
    RosterPerson("roster-ben", "male", 28, 178.0, 80.0, "active", "muscle", (), "gym"),
    RosterPerson("roster-cam", "female", 41, 160.0, 70.0, "sedentary", "cut", ("egg",), "cut"),
    RosterPerson("roster-drew", "male", 52, 182.0, 88.0, "moderate", "maintain", ()),
    RosterPerson("roster-eve", "female", 19, 168.0, 58.0, "very_active", "maintain", (), "gym"),
    RosterPerson("roster-fay", "female", 63, 158.0, 64.0, "light", "maintain", ("milk",)),
    RosterPerson("roster-gus", "male", 37, 175.0, 76.0, "moderate", "cut", (), "cut"),
    RosterPerson("roster-hao", "male", 45, 170.0, 72.0, "sedentary", "maintain", ("peanut", "shellfish")),
    RosterPerson("roster-ina", "female", 29, 172.0, 66.0, "active", "muscle", (), "gym"),
    RosterPerson("roster-jay", "male", 22, 185.0, 79.0, "very_active", "maintain", ()),
    RosterPerson("roster-kim", "female", 55, 162.0, 68.0, "light", "cut", ("soy",), "cut"),
    RosterPerson("roster-leo", "male", 71, 174.0, 81.0, "sedentary", "maintain", ()),
    RosterPerson("roster-mia", "female", 47, 166.0, 61.0, "moderate", "maintain", ("tree_nut",)),
    RosterPerson("roster-ned", "male", 33, 180.0, 85.0, "active", "muscle", (), "gym"),
    RosterPerson("roster-ola", "female", 24, 159.0, 54.0, "light", "maintain", ()),
    RosterPerson("roster-pj", "male", 60, 176.0, 90.0, "light", "cut", ("egg",), "cut"),
    RosterPerson("roster-quin", "female", 38, 170.0, 74.0, "moderate", "maintain", ("milk",)),
    RosterPerson("roster-raj", "male", 19, 181.0, 70.0, "very_active", "muscle", (), "gym"),
    RosterPerson("roster-sam", "female", 75, 155.0, 60.0, "sedentary", "maintain", ()),
    RosterPerson("roster-tess", "female", 31, 164.0, 59.0, "active", "maintain", ("peanut",)),
    RosterPerson("roster-uma", "female", 43, 163.0, 63.0, "light", "maintain", ("fish",)),
    RosterPerson("roster-van", "male", 36, 177.0, 80.0, "moderate", "maintain", ("gluten",)),
    RosterPerson("roster-wes", "male", 50, 171.0, 77.0, "sedentary", "maintain", ("wheat",)),
)


def sample_roster_person(seed: int) -> RosterPerson:
    """Deterministic pick. Same seed → same person."""
    return random.Random(seed).choice(ROSTER)


def profile_for(person: RosterPerson, *, user_id: str | None = None) -> Profile:
    """Roster body facts plus world-derived daily windows. Mill does not invent kcal."""
    skeleton = Profile(
        user_id=user_id or person.user_id,
        allergies=person.allergies,
        sex=person.sex,
        age_y=person.age_y,
        height_cm=person.height_cm,
        weight_kg=person.weight_kg,
        activity=person.activity,
        phase=person.phase,
    )
    windows = derive_profile_windows(skeleton)
    if windows is None:
        raise ValueError(f"incomplete roster body for {person.user_id}")
    return Profile(
        user_id=skeleton.user_id,
        allergies=skeleton.allergies,
        windows=windows,
        sex=skeleton.sex,
        age_y=skeleton.age_y,
        height_cm=skeleton.height_cm,
        weight_kg=skeleton.weight_kg,
        activity=skeleton.activity,
        phase=skeleton.phase,
    )
