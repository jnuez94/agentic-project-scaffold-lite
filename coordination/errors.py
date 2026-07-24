"""Stable CLI error types, exit codes, and JSON serialization."""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn


EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_ENVIRONMENT = 5
EXIT_BUSY = 6


class CoordinationError(Exception):
    """Expected CLI failure with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        exit_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}


def fail(
    code: str,
    message: str,
    exit_code: int,
    details: dict[str, Any] | None = None,
) -> NoReturn:
    raise CoordinationError(code, message, exit_code, details)


def error_envelope(
    error: CoordinationError,
    *,
    include_exit_code: bool = False,
) -> dict[str, Any]:
    """Return the stable error shape shared by CLI and transport adapters."""
    value: dict[str, Any] = {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
        },
    }
    if error.details:
        value["error"]["details"] = error.details
    if include_exit_code:
        value["error"]["exit_code"] = error.exit_code
    return value


def emit_error(error: CoordinationError) -> None:
    value = error_envelope(error)
    print(json.dumps(value, indent=2, sort_keys=True), file=sys.stderr)
