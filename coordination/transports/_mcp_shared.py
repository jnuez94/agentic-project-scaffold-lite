"""The shared tool-result envelope and live operation-log binding."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import CallToolResult, TextContent

from coordination.errors import (
    EXIT_USAGE,
    CoordinationError,
    error_envelope,
    fail,
)
from coordination.service import CoordinationService, OperationLog


_OPERATION_LOG: OperationLog | None = None


def _tool_result(
    db: str | None,
    operation: str,
    parameters: dict[str, object],
    *,
    session: str | None = None,
) -> CallToolResult:
    service = CoordinationService(
        db=db,
        session=session,
        contain_paths=True,
        transport="mcp",
        operation_log=_OPERATION_LOG,
    )
    try:
        data = service.invoke(operation, parameters)
        envelope: dict[str, Any] = {"ok": True, "data": data}
        audit_range = service.last_receipt.get("audit_range")
        if audit_range is not None:
            envelope["audit_range"] = audit_range
        is_error = False
    except CoordinationError as error:
        envelope = error_envelope(error, include_exit_code=True)
        is_error = True
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(envelope, indent=2, sort_keys=True),
            )
        ],
        structuredContent=envelope,
        isError=is_error,
    )


def _require_confirmation(value: str, expected: str) -> None:
    if value != expected:
        fail(
            "confirmation_required",
            f"This operation requires confirmation={expected!r}",
            EXIT_USAGE,
            {"expected_confirmation": expected},
        )
