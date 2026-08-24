"""Argument validators shared by every transport."""

from __future__ import annotations

import argparse

from coordination._primitives import (
    IDENTIFIER_PATTERN,
    MAX_AUDIT_CURSOR,
    MAX_IDENTIFIER_LENGTH,
    MAX_LIST_LIMIT,
    MAX_PATH_LENGTH,
    MAX_STALE_DAYS,
    MAX_STALE_SECONDS,
    MAX_STALE_SESSION_MINUTES,
    MAX_TEXT_LENGTH,
    MIN_STALE_SECONDS,
)
from coordination.errors import EXIT_USAGE, fail


def identifier(value: str) -> str:
    """Validate a stable public identifier without silently rewriting it."""
    if (
        not 1 <= len(value) <= MAX_IDENTIFIER_LENGTH
        or IDENTIFIER_PATTERN.fullmatch(value) is None
    ):
        raise argparse.ArgumentTypeError(
            "must be 1-128 ASCII characters: "
            "letters, digits, '.', '_', ':', '@', '+', or '-'"
        )
    return value


def required_text(value: str) -> str:
    """Validate a required human-readable value while preserving its content."""
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be empty or whitespace")
    return optional_text(value)


def optional_text(value: str) -> str:
    if "\x00" in value:
        raise argparse.ArgumentTypeError("must not contain a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise argparse.ArgumentTypeError(
            "must contain valid Unicode scalar values"
        ) from error
    if len(value) > MAX_TEXT_LENGTH:
        raise argparse.ArgumentTypeError(
            f"must be at most {MAX_TEXT_LENGTH} characters"
        )
    return value


def path_argument(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("path must not be empty or whitespace")
    if "\x00" in value:
        raise argparse.ArgumentTypeError("path must not contain a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise argparse.ArgumentTypeError(
            "path must contain valid Unicode scalar values"
        ) from error
    if len(value) > MAX_PATH_LENGTH:
        raise argparse.ArgumentTypeError(
            f"path must be at most {MAX_PATH_LENGTH} characters"
        )
    return value


def _bounded_integer(value: str, minimum: int, maximum: int, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{label} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(
            f"{label} must be between {minimum} and {maximum}"
        )
    return parsed


def audit_cursor(value: str) -> int:
    return _bounded_integer(value, 0, MAX_AUDIT_CURSOR, "cursor")


def tag_token(value: str) -> str:
    """Validate one tag for filtering: a comma-separated token of `tags`."""
    token = required_text(value).strip()
    if "," in token or any(character.isspace() for character in token):
        raise argparse.ArgumentTypeError(
            "must be a single tag token without commas or whitespace"
        )
    return token


BECAUSE_TABLES = {
    "review": "reviews",
    "decision": "decisions",
    "message": "messages",
    "task": "tasks",
    "escalation": "escalations",
    "artifact": "artifacts",
}


def because_reference(value: str) -> str:
    """Validate a causality reference of the form `type:id`."""
    kind, separator, record_id = value.partition(":")
    if not separator or kind not in BECAUSE_TABLES:
        raise argparse.ArgumentTypeError(
            "must be TYPE:ID where TYPE is one of " + ", ".join(sorted(BECAUSE_TABLES))
        )
    return f"{kind}:{identifier(record_id)}"


def positive_revision(value: str) -> int:
    return _bounded_integer(value, 1, 2_147_483_647, "revision")


def list_limit(value: str) -> int:
    return _bounded_integer(value, 1, MAX_LIST_LIMIT, "limit")


def list_offset(value: str) -> int:
    return _bounded_integer(value, 0, 2_147_483_647, "offset")


def stale_days(value: str) -> int:
    return _bounded_integer(value, 0, MAX_STALE_DAYS, "stale days")


def stale_session_minutes(value: str) -> int:
    return _bounded_integer(
        value,
        0,
        MAX_STALE_SESSION_MINUTES,
        "stale session minutes",
    )


def stale_seconds(value: str) -> int:
    return _bounded_integer(
        value, MIN_STALE_SECONDS, MAX_STALE_SECONDS, "stale seconds"
    )


def require_unique(values: list[str], option: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    if duplicates:
        fail(
            "invalid_arguments",
            f"{option} may not contain duplicate values",
            EXIT_USAGE,
            {"option": option, "duplicates": sorted(duplicates)},
        )
