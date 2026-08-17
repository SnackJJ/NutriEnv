"""Action envelope schemas and the error Env raises for an Illegal Action.

Every Action is available on every Task (CHARTER). What makes an Action illegal
is physics, not difficulty: a malformed envelope, an unminted food_id, or a
quantity no person can eat. The schema is strict — unknown keys are a schema
error, not silently ignored.
"""

from __future__ import annotations

__all__ = [
    "ActionError",
    "ACTION_SCHEMAS",
    "OPS",
    "validate_envelope",
    "as_nonempty_str",
    "as_dict",
    "as_list",
]

# op -> (required arg names, optional arg names)
ACTION_SCHEMAS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "search_foods": (frozenset({"q"}), frozenset()),
    "get_food": (frozenset({"food_id"}), frozenset()),
    "get_profile": (frozenset(), frozenset()),
    "get_ledger": (frozenset(), frozenset()),
    "get_dri": (frozenset(), frozenset()),
    "log_meal": (frozenset({"food_id", "grams"}), frozenset({"eaten_at"})),
    "submit_plan": (frozenset({"items"}), frozenset()),
    "update_profile": (frozenset({"patch"}), frozenset()),
    "update_plan": (frozenset({"patch"}), frozenset()),
}

OPS = frozenset(ACTION_SCHEMAS)


class ActionError(Exception):
    """An Illegal Action. Env reports it and leaves the world untouched."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def validate_envelope(action: object) -> tuple[str, dict]:
    """Check the outer shape of an action. Returns ``(op, args)``."""
    if not isinstance(action, dict):
        raise ActionError("bad_schema", "action must be a dict")
    if "op" not in action:
        raise ActionError("bad_schema", "action is missing 'op'")
    op = action["op"]
    if not isinstance(op, str):
        raise ActionError("bad_schema", "'op' must be a string")
    if op not in ACTION_SCHEMAS:
        raise ActionError("unknown_op", f"unknown op: {op!r}")

    required, optional = ACTION_SCHEMAS[op]
    args = {key: value for key, value in action.items() if key != "op"}
    missing = sorted(required - args.keys())
    if missing:
        raise ActionError("bad_schema", f"{op} is missing {missing}")
    extra = sorted(args.keys() - required - optional)
    if extra:
        raise ActionError("bad_schema", f"{op} got unexpected keys {extra}")
    return op, args


def as_nonempty_str(value: object, field: str) -> str:
    """A required string field, stripped, that must not be empty."""
    if not isinstance(value, str):
        raise ActionError("bad_schema", f"'{field}' must be a string")
    text = value.strip()
    if not text:
        raise ActionError("bad_schema", f"'{field}' must not be empty")
    return text


def as_dict(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise ActionError("bad_schema", f"'{field}' must be a dict")
    return value


def as_list(value: object, field: str) -> list:
    if not isinstance(value, list):
        raise ActionError("bad_schema", f"'{field}' must be a list")
    return value
