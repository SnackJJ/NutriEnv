"""ADR 0017 mill pipeline: Sampler → generate_one → Resolver → gates.

The old v1.0 Sampler → Expander → Resolver surface (``run_batch`` /
``LlmExpander``) is retired: its code lives in ``legacy_run_batch.py`` and
``expander.py`` for reference, but it is no longer exported or wired into any
live entry point.
"""

from .generate_one import GenerateOneResult, generate_one
from .types import catalog_digest

__all__ = [
    "GenerateOneResult",
    "catalog_digest",
    "generate_one",
]
