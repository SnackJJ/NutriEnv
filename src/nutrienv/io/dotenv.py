"""Load KEY=value files into os.environ without overriding set keys."""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["load_dotenv_keys"]


def load_dotenv_keys(*paths: Path) -> None:
    """Load KEY=value from files into os.environ if the key is unset."""
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
