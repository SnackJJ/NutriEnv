"""Thin runner: Env is the exam; the subject is Harness+Model."""

from __future__ import annotations

from nutrienv import __version__
from nutrienv.bench import Generator, Scorer
from nutrienv.env import NutriEnv

from .protocol import Harness
from .script import ScriptHarness

__all__ = [
    "ENV_LABEL",
    "HARNESS_LABEL",
    "MODEL_LABEL",
    "run_split",
    "DEFAULT_MAX_STEPS",
]

ENV_LABEL = f"nutrienv-{__version__}"
HARNESS_LABEL = "script-v0"
MODEL_LABEL = "script"
DEFAULT_MAX_STEPS = 12


def run_split(
    seed: int,
    n: int,
    k: int = 1,
    family: str | None = None,
    situation: str | None = None,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    harness: Harness | None = None,
) -> dict:
    """Run a seeded split and return Pass / pass^k plus env×harness×model labels.

    ``k`` independent episodes are run per Task. ``pass_rate`` is the fraction
    of those episodes that Pass. ``pass_k`` is the fraction of Tasks that Pass
    on every one of the k episodes.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be an int >= 1")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("max_steps must be an int >= 1")

    tasks = _split(seed, n, family=family, situation=situation)
    policy = harness if harness is not None else ScriptHarness()
    scorer = Scorer()

    episode_pass = 0
    task_all_k = 0
    for task in tasks:
        k_hits = 0
        for _ in range(k):
            if _run_episode(task, policy, scorer, max_steps):
                episode_pass += 1
                k_hits += 1
        if k_hits == k:
            task_all_k += 1

    total = max(len(tasks) * k, 1)
    pass_rate = episode_pass / total if tasks else 0.0
    pass_k = task_all_k / len(tasks) if tasks else 0.0

    manifest = {"env": ENV_LABEL, "harness": HARNESS_LABEL, "model": MODEL_LABEL}
    result = {
        **manifest,
        "manifest": manifest,
        "pass_rate": pass_rate,
        "n": n,
        "seed": seed,
        "k": k,
        "family": family,
        "situation": situation,
    }
    if k > 1:
        result["pass_k"] = pass_k
    return result


def _split(
    seed: int, n: int, family: str | None, situation: str | None
) -> list:
    gen = Generator()
    if family is not None:
        return [
            gen.sample(seed + index, family=family, situation=situation)
            for index in range(n)
        ]
    return gen.generate_split(seed, n, situation=situation)


def _run_episode(task, harness: Harness, scorer: Scorer, max_steps: int) -> bool:
    env = NutriEnv()
    observation = env.reset(task.s0)
    history: list[dict] = []
    for _ in range(max_steps):
        action = harness.act(observation, task.query, history)
        result = env.step(action)
        history.append({"action": action, "result": result})
        if result.get("ok") and isinstance(result.get("observation"), dict):
            observation = result["observation"]
        else:
            observation = {"error": result.get("error")}
    score = scorer.score(env.state(), task.oracle)
    return bool(score["passed"])
