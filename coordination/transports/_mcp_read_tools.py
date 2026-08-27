"""Status, report, inbox, show, history, and audit tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from coordination.transports._mcp_shared import _tool_result
from coordination.transports._mcp_types import (
    HealthSection,
    HistoryObjectType,
    ShowObjectType,
    SummarySection,
)


def register(server: FastMCP, db: str | None) -> None:
    """Register these tools on the server."""

    @server.tool()
    def coordination_project_status() -> CallToolResult:
        """Validate the configured project, database, schema, and durability."""
        return _tool_result(db, "project_status", {})

    @server.tool()
    def coordination_health(
        stale_days: int = 7,
        stale_session_minutes: int = 60,
        limit: int = 100,
        sections: list[HealthSection] | None = None,
    ) -> CallToolResult:
        """Return bounded health diagnostics: anomalies and informational."""
        return _tool_result(
            db,
            "health",
            {
                "stale_days": stale_days,
                "stale_session_minutes": stale_session_minutes,
                "limit": limit,
                "section": sections,
            },
        )

    @server.tool()
    def coordination_summary(
        sections: list[SummarySection] | None = None,
    ) -> CallToolResult:
        """Return aggregate counts computed at one coherent snapshot."""
        return _tool_result(db, "summary", {"section": sections})

    @server.tool()
    def coordination_inbox_list(
        agent: str | None = None,
        limit: int = 100,
        offset: int = 0,
        session: str | None = None,
    ) -> CallToolResult:
        """Messages for an agent (or its session's agent) after its read position."""
        return _tool_result(
            db,
            "inbox_list",
            {"agent": agent, "limit": limit, "offset": offset},
            session=session,
        )

    @server.tool()
    def coordination_inbox_mark_read(
        cursor: int,
        agent: str | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Advance an agent's inbox cursor; explicit and forward only."""
        return _tool_result(
            db,
            "inbox_mark_read",
            {"cursor": cursor, "agent": agent},
            session=session,
        )

    @server.tool()
    def coordination_show(object_type: ShowObjectType, id: str) -> CallToolResult:
        """Show one record of the given type; tasks use coordination_task_inspect."""
        return _tool_result(db, f"{object_type}_show", {"id": id})

    @server.tool()
    def coordination_history(
        object_type: HistoryObjectType,
        object_id: str,
        since: int = 0,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """One record's audit timeline in id order, optionally after a cursor."""
        return _tool_result(
            db,
            f"{object_type}_history",
            {"id": object_id, "since": since, "limit": limit, "offset": offset},
        )

    @server.tool()
    def coordination_audit_list(
        actor: str | None = None,
        session_id: str | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        action: str | None = None,
        since: int = 0,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List audit rows by id; `since` returns rows after a cursor."""
        return _tool_result(
            db,
            "audit_list",
            {
                "actor": actor,
                "session_id": session_id,
                "object_type": object_type,
                "object_id": object_id,
                "action": action,
                "since": since,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_audit_changes(
        audit_id: int | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        since: int = 0,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """Field-level before/after rows recorded with audit events."""
        return _tool_result(
            db,
            "audit_changes",
            {
                "audit_id": audit_id,
                "object_type": object_type,
                "object_id": object_id,
                "since": since,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_audit_redact(
        id: int,
        actor: str,
        reason: str,
        session: str | None = None,
    ) -> CallToolResult:
        """Redact one audit row's detail and change rows, leaving a tombstone."""
        return _tool_result(
            db,
            "audit_redact",
            {"id": id, "actor": actor, "reason": reason},
            session=session,
        )
