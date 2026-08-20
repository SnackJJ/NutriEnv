"""Expander model-route table: parse, assign, disable."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from nutrienv.io.chat import EXPANDER_MODELS

__all__ = [
    "DEFAULT_EXPANDER_MODEL",
    "DEFAULT_EXPANDER_MODELS",
    "DISABLED_EXPANDER_MODELS",
    "QWEN_EXPANDER_MODELS",
    "assign_model",
    "enabled_route",
    "parse_model_route",
]

# Roadmap pool. Smoke 2026-08-17: all six ids answer on DashScope.
# deepseek-v4-pro-0813 is flaky-empty on content (recovered from
# reasoning_content); its DeepSeek-direct fallback is HTTP 400.
# Unavailable ids belong in DISABLED_EXPANDER_MODELS, not deleted here.
DEFAULT_EXPANDER_MODELS: tuple[str, ...] = (
    "qwen3.8-2.4t-a95b",
    "qwen3.8-max",
    "deepseek-v4-pro-0813",
    "deepseek-v4-flash-0731",
    "glm-5.2",
    "kimi-k2.7-code",
)

# Filled after Phase-1 smoke. A disabled id is skipped so a stale route
# table cannot crash the pipeline; an empty remaining route still raises.
DISABLED_EXPANDER_MODELS: frozenset[str] = frozenset(
    model_id for model_id, spec in EXPANDER_MODELS.items() if spec.disabled
)

DEFAULT_EXPANDER_MODEL = "qwen3.8-max"

# Single-task generate_one runs only the Qwen legs of the route table.
QWEN_EXPANDER_MODELS: tuple[str, ...] = tuple(
    model_id for model_id in DEFAULT_EXPANDER_MODELS if "qwen" in model_id.lower()
)


def parse_model_route(model_route: object) -> tuple[str, ...]:
    """Normalize ``batch_spec['model_route']`` to an ordered tuple of ids.

    A mapping is batch-key → model id; keys are sorted so the same table
    always yields the same rotation order. A sequence is used as-is. Empty
    input is empty (the expander then falls back to one default model).
    """
    if model_route is None:
        return ()
    if isinstance(model_route, Mapping):
        pairs: list[tuple[str, str]] = []
        for key, value in model_route.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"model_route[{key!r}] must be a model id")
            pairs.append((str(key), value.strip()))
        pairs.sort(key=lambda item: item[0])
        return tuple(value for _key, value in pairs)
    if isinstance(model_route, str):
        text = model_route.strip()
        return (text,) if text else ()
    if isinstance(model_route, Sequence) and not isinstance(model_route, (str, bytes)):
        out: list[str] = []
        for item in model_route:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("model_route entries must be model ids")
            out.append(item.strip())
        return tuple(out)
    raise ValueError("model_route must be a mapping, sequence, or model id")


def enabled_route(
    route: Sequence[str], disabled: Iterable[str] = ()
) -> tuple[str, ...]:
    """Drop registry-disabled and caller-disabled ids, keep order."""
    blocked = DISABLED_EXPANDER_MODELS | frozenset(disabled)
    return tuple(model_id for model_id in route if model_id not in blocked)


def assign_model(index: int, route: Sequence[str], *, seed: int = 0) -> str:
    """Round-robin. Same ``seed`` + ``route`` + ``index`` → same model."""
    if not route:
        raise RuntimeError("no enabled expander models in the route table")
    return route[(int(seed) + int(index)) % len(route)]
