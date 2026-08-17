"""Archived factory module.

Task construction lives in :mod:`nutrienv.bench.realize`. ``Generator.sample``,
``generate``, and ``generate_split`` are retired. This module re-exports
``Task``, ``Oracle``, and ``FAMILIES`` so existing bench imports keep working.
"""

from .realize import FAMILIES, Oracle, Task, realize

__all__ = ["Oracle", "Task", "realize", "FAMILIES"]
