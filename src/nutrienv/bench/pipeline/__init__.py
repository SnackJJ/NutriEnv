"""Agent authoring -> structured evidence -> independent review -> reachable frozen task.

The parser/template mill in legacy_generate_one.py is legacy calibration code, not
the public authoring entry point. It has no implicit fallback from this path.
"""

from .generate_one import GenerateOneResult, generate_one
from .types import catalog_digest

__all__ = [
    "GenerateOneResult",
    "catalog_digest",
    "generate_one",
]
