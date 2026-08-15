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


def test_update_pass_requires_every_oracle_field() -> None:
    from nutrienv.bench.generator import Task
    from nutrienv.bench.realizations import UPDATE_ROWS

    row = next(item for item in UPDATE_ROWS if item.seed_id == "up-milk-kcal-200")
    assert row.add_allergens and row.window_shifts
    generator = Generator()
    s0 = generator._make_s0(0, generator._difficulty(None))
    query, oracle = generator._update_from_row(s0, row)
    task = Task("draft", "update", query, s0, oracle)
    assert task.oracle.profile.allergies != task.s0.profile.allergies
    assert task.oracle.profile.windows != task.s0.profile.windows
    assert "shrimp" not in task.oracle.profile.allergies
    assert task.oracle.profile.medications == task.s0.profile.medications

    env = NutriEnv()
    scorer = Scorer()
    full_patch = {
        "allergies": list(oracle.profile.allergies),
        "windows": {
            key: list(bounds) for key, bounds in oracle.profile.windows.items()
        },
    }

    env.reset(task.s0)
    env.step({"op": "update_profile", "patch": full_patch})
    assert scorer.score(env.state(), oracle).passed is True

    env.reset(task.s0)
    env.step({"op": "update_profile", "patch": {"windows": full_patch["windows"]}})
    assert scorer.score(env.state(), oracle).passed is False
    env.reset(task.s0)
    env.step({"op": "update_profile", "patch": {"allergies": full_patch["allergies"]}})
    assert scorer.score(env.state(), oracle).passed is False

    extra = dict(full_patch)
    extra["medications"] = ["warfarin"]
    env.reset(task.s0)
    env.step({"op": "update_profile", "patch": extra})
    assert scorer.score(env.state(), oracle).passed is False


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
