"""Runner: Env is the exam; subject is Harness+Model."""

from __future__ import annotations

from nutrienv.harness.runner import HARNESS_LABEL, MODEL_LABEL, run_split


def test_run_split_finishes_and_writes_manifest() -> None:
    result = run_split(n=6, seed=0)
    assert 0.0 <= result["pass_rate"] <= 1.0
    manifest = result["manifest"]
    assert manifest["env"]
    assert manifest["harness"] == HARNESS_LABEL == "script-v0"
    assert manifest["model"] == MODEL_LABEL == "script"
    assert set(manifest) >= {"env", "harness", "model"}
