"""Hand-in Pass: end state vs Oracle, plus Generator determinism."""

from __future__ import annotations

from nutrienv.bench import Generator, Oracle, Scorer
from nutrienv.env import NutriEnv
from nutrienv.world.catalog_fixture import demo_catalog, demo_state
from nutrienv.world.types import Profile, WorldState


def _peanut_world() -> WorldState:
    s0 = demo_state()
    return WorldState(
        profile=s0.profile,
        ledger=[],
        catalog=demo_catalog(),
        last_plan=[],
    )


def _recommend_oracle(s0: WorldState) -> Oracle:
    return Oracle(
        profile=s0.profile,
        ledger=tuple(s0.ledger),
        last_plan=None,
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
    )


def test_submit_plan_peanut_allergy_fails_with_allergy_tag() -> None:
    env = NutriEnv()
    s0 = _peanut_world()
    env.reset(s0)

    out = env.step(
        {"op": "submit_plan", "items": [{"food_id": "peanut_butter", "grams": 20}]}
    )
    assert out["ok"] is True

    score = Scorer().score(env.state(), _recommend_oracle(s0))
    assert score.passed is False
    assert score.tag == "allergy"
    assert "allergy" in score.tags


def test_submit_plan_in_windows_and_safe_passes() -> None:
    profile = Profile(
        user_id="safe",
        allergies=("peanut",),
        medications=(),
        windows={"kcal": (200.0, 500.0), "protein_g": (20.0, 50.0)},
        plan_preset={"meals_per_day": 3, "cuisine": "any"},
        version=1,
    )
    s0 = WorldState(profile=profile, ledger=[], catalog=demo_catalog(), last_plan=[])
    env = NutriEnv()
    env.reset(s0)

    # chicken_breast 150 g: 247.5 kcal, 46.5 g protein; no peanut tag.
    out = env.step(
        {"op": "submit_plan", "items": [{"food_id": "chicken_breast", "grams": 150}]}
    )
    assert out["ok"] is True

    score = Scorer().score(env.state(), _recommend_oracle(s0))
    assert score.passed is True
    assert score.tag is None


def test_tired_shrimp_query_requires_window_and_allergy() -> None:
    task = Generator().generate(11, family="update")
    query = task.query.lower()
    assert "tired" in query
    assert "shrimp" in query

    oracle = task.oracle
    assert "shrimp" in oracle.profile.allergies
    assert oracle.profile.windows["kcal"] != task.s0.profile.windows["kcal"]
    assert oracle.profile.windows["protein_g"] == task.s0.profile.windows["protein_g"]
    assert oracle.profile.medications == task.s0.profile.medications

    env = NutriEnv()
    scorer = Scorer()
    kcal = oracle.profile.windows["kcal"]

    env.reset(task.s0)
    env.step({"op": "update_profile", "patch": {"windows": {"kcal": [kcal[0], kcal[1]]}}})
    only_window = scorer.score(env.state(), oracle)
    assert only_window.passed is False

    env.reset(task.s0)
    env.step(
        {
            "op": "update_profile",
            "patch": {"allergies": list(oracle.profile.allergies)},
        }
    )
    only_allergy = scorer.score(env.state(), oracle)
    assert only_allergy.passed is False

    env.reset(task.s0)
    env.step(
        {
            "op": "update_profile",
            "patch": {
                "windows": {"kcal": [kcal[0], kcal[1]]},
                "allergies": list(oracle.profile.allergies),
            },
        }
    )
    both = scorer.score(env.state(), oracle)
    assert both.passed is True

    # Extra unmentioned write must not Pass.
    env.reset(task.s0)
    env.step(
        {
            "op": "update_profile",
            "patch": {
                "windows": {"kcal": [kcal[0], kcal[1]]},
                "allergies": list(oracle.profile.allergies),
                "medications": ["warfarin"],
            },
        }
    )
    extra = scorer.score(env.state(), oracle)
    assert extra.passed is False


def test_generator_deterministic_for_the_same_seed() -> None:
    gen = Generator()
    first = gen.generate(42)
    second = gen.generate(42)
    assert first.query == second.query
    assert first.family == second.family
    assert first.s0.profile == second.s0.profile
    assert first.s0.catalog == second.s0.catalog
    assert first.s0.ledger == second.s0.ledger
    assert first.s0.last_plan == second.s0.last_plan
    assert first.oracle == second.oracle
