"""Confirmation-gated backup and restore tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from coordination.errors import (
    CoordinationError,
    error_envelope,
)
from coordination.transports._mcp_shared import _require_confirmation, _tool_result


def register(server: FastMCP, db: str | None) -> None:
    """Register these tools on the server."""

    @server.tool()
    def coordination_backup(
        output: str,
        confirmation: str,
        actor: str,
        session: str | None = None,
    ) -> CallToolResult:
        """Publish a verified backup after explicit BACKUP confirmation.

        There is deliberately no `force`: a transport whose caller acts on
        text it did not write never replaces an existing file. Choose a new
        name, or use the CLI.
        """
        try:
            _require_confirmation(confirmation, "BACKUP")
        except CoordinationError as error:
            envelope = error_envelope(error, include_exit_code=True)
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(envelope, indent=2, sort_keys=True),
                    )
                ],
                structuredContent=envelope,
                isError=True,
            )
        return _tool_result(
            db,
            "backup",
            {"output": output, "force": False, "actor": actor},
            session=session,
        )

    @server.tool()
    def coordination_restore(
        input: str,
        actor: str,
        confirmation: str,
        session: str | None = None,
    ) -> CallToolResult:
        """Restore only after explicit RESTORE confirmation and full validation."""
        try:
            _require_confirmation(confirmation, "RESTORE")
        except CoordinationError as error:
            envelope = error_envelope(error, include_exit_code=True)
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(envelope, indent=2, sort_keys=True),
                    )
                ],
                structuredContent=envelope,
                isError=True,
            )
        return _tool_result(
            db,
            "restore",
            {"input": input, "actor": actor, "force": True},
            session=session,
        )
