#!/usr/bin/env python3
"""One-episode ReAct smoke: DeepSeek + NutriEnv. Not a full eval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from nutrienv.bench import Generator, Scorer  # noqa: E402
from nutrienv.env import NutriEnv  # noqa: E402
from nutrienv.harness.react import ReActHarness, load_dotenv_keys  # noqa: E402
from nutrienv.harness.runner import DEFAULT_MAX_STEPS  # noqa: E402
from nutrienv.world.catalog_store import SNAPSHOT_PATH  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--family", default="lookup")
    parser.add_argument("--max-steps", type=int, default=min(8, DEFAULT_MAX_STEPS))
    args = parser.parse_args()

    load_dotenv_keys(
        _ROOT / ".env.local",
        Path("/home/jzq/Projects/NutriBuddy/.env.local"),
    )

    task = Generator().sample(args.seed, family=args.family)
    env = NutriEnv()
    obs = env.reset(task.s0)
    harness = ReActHarness()
    history: list[dict] = []
    print(f"task={task.id} family={task.family}")
    print(f"catalog={SNAPSHOT_PATH if SNAPSHOT_PATH.is_file() else 'fixture'}")
    print(f"query={task.query}")
    for step in range(args.max_steps):
        action = harness.act(obs, task.query, history)
        result = env.step(action)
        history.append({"action": action, "result": result})
        print(f"step={step} action={json.dumps(action, default=str)}")
        err = result.get("error")
        if err:
            print(f"  error={err}")
        if result.get("ok") and isinstance(result.get("observation"), dict):
            obs = result["observation"]
        else:
            obs = {"error": result.get("error")}
    score = Scorer().score(env.state(), task.oracle)
    print(f"passed={score['passed']} tag={score['tag']}")
    print(
        "manifest="
        + json.dumps(
            {
                "env": "nutrienv-0.1.0",
                "harness": "react-v0",
                "model": harness.model,
            }
        )
    )
    return 0 if score["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
