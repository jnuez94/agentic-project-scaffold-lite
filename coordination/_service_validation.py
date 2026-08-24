"""Parameter validators and shared constants for the coordination service."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from coordination.core import (
    IDENTIFIER_PATTERN,
    MAX_IDENTIFIER_ARRAY_ITEMS,
    identifier,
)
from coordination.errors import (
    EXIT_USAGE,
    fail,
)


OperationResult = dict[str, Any] | list[dict[str, Any]] | None

OperationLog = Callable[[dict[str, Any]], None]

ACCOUNTABLE_PARAMETERS = ("actor", "agent", "reviewer", "owner", "sender", "raised_by")

OBJECT_PARAMETERS = ("id", "task", "input", "output")

MAX_SQLITE_INTEGER = 2_147_483_647


def _validate(
    field: str,
    validator: Callable[[str], Any],
    value: object,
) -> Any:
    if not isinstance(value, str):
        fail(
            "invalid_arguments",
            f"{field} must be a string",
            EXIT_USAGE,
            {"field": field},
        )
    try:
        return validator(value)
    except argparse.ArgumentTypeError as error:
        fail(
            "invalid_arguments",
            f"{field} {error}",
            EXIT_USAGE,
            {"field": field},
        )


def _optional(
    field: str,
    validator: Callable[[str], Any],
    value: object | None,
) -> Any | None:
    if value is None:
        return None
    return _validate(field, validator, value)


def _choice(
    field: str,
    value: object,
    choices: Sequence[str],
) -> str:
    if not isinstance(value, str) or value not in choices:
        fail(
            "invalid_arguments",
            f"{field} must be one of: {', '.join(choices)}",
            EXIT_USAGE,
            {"field": field, "choices": list(choices)},
        )
    return value


def _optional_choice(
    field: str,
    value: object | None,
    choices: Sequence[str],
) -> str | None:
    if value is None:
        return None
    return _choice(field, value, choices)


def _choices(
    field: str,
    value: object | None,
    choices: Sequence[str],
) -> list[str] | None:
    """Accept one choice or a list of choices; return a deduplicated list."""
    if value is None:
        return None
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        fail(
            "invalid_arguments",
            f"{field} must be one of {', '.join(choices)}, or an array of them",
            EXIT_USAGE,
            {"field": field, "choices": list(choices)},
        )
    selected: list[str] = []
    for item in items:
        checked = _choice(field, item, choices)
        if checked not in selected:
            selected.append(checked)
    return selected or None


def _strings(field: str, value: object | None) -> list[str] | None:
    """Accept a list of short strings (repeatable CLI flags, MCP arrays)."""
    if value is None:
        return None
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        fail(
            "invalid_arguments",
            f"{field} must be a string or an array of strings",
            EXIT_USAGE,
            {"field": field},
        )
    if len(items) > MAX_IDENTIFIER_ARRAY_ITEMS or any(
        len(item) > 4096 for item in items
    ):
        fail(
            "invalid_arguments",
            f"{field} has too many or too long entries",
            EXIT_USAGE,
            {"field": field, "maximum": MAX_IDENTIFIER_ARRAY_ITEMS},
        )
    return [item for item in items if item] or None


def _integer(
    field: str,
    value: object,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(
            "invalid_arguments",
            f"{field} must be an integer",
            EXIT_USAGE,
            {"field": field},
        )
    if not minimum <= value <= maximum:
        fail(
            "invalid_arguments",
            f"{field} must be between {minimum} and {maximum}",
            EXIT_USAGE,
            {"field": field, "minimum": minimum, "maximum": maximum},
        )
    return value


def _boolean(field: str, value: object) -> bool:
    if not isinstance(value, bool):
        fail(
            "invalid_arguments",
            f"{field} must be a boolean",
            EXIT_USAGE,
            {"field": field},
        )
    return value


def _identifiers(field: str, value: object) -> list[str]:
    if not isinstance(value, list):
        fail(
            "invalid_arguments",
            f"{field} must be an array of identifiers",
            EXIT_USAGE,
            {"field": field},
        )
    if len(value) > MAX_IDENTIFIER_ARRAY_ITEMS:
        fail(
            "invalid_arguments",
            (f"{field} must contain at most {MAX_IDENTIFIER_ARRAY_ITEMS} identifiers"),
            EXIT_USAGE,
            {
                "field": field,
                "maximum": MAX_IDENTIFIER_ARRAY_ITEMS,
                "actual": len(value),
            },
        )
    return [_validate(field, identifier, item) for item in value]


def _identifier_parameter(
    parameters: Mapping[str, object],
    names: Sequence[str],
) -> str | None:
    """Return the first named parameter that is a well-formed identifier.

    Used only by the operation log, which records principals and object ids
    and never free text; a value that is not identifier-shaped is omitted
    rather than logged.
    """
    for name in names:
        value = parameters.get(name)
        if isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value):
            return value
    return None
