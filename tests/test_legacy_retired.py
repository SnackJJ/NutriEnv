"""Old v1.0 batch surface is retired from the formal path (ADR 0017 mill)."""

from __future__ import annotations

import nutrienv.bench.pipeline as pipeline


def test_pipeline_init_does_not_export_run_batch_or_pass_through_reviewer() -> None:
    assert not hasattr(pipeline, "run_batch")
    assert not hasattr(pipeline, "pass_through_reviewer")
    assert not hasattr(pipeline, "BatchResult")


def test_legacy_module_exists_for_reference_only() -> None:
    import importlib

    legacy = importlib.import_module("nutrienv.bench.pipeline.legacy_run_batch")
    assert hasattr(legacy, "run_batch")
    assert legacy.__doc__ is not None and "RETIRED" in legacy.__doc__


def test_new_entry_point_is_the_formal_export() -> None:
    assert hasattr(pipeline, "generate_one")
    assert pipeline.__all__ == ["GenerateOneResult", "catalog_digest", "generate_one"]
