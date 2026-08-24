"""Evidence, review, and message tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from coordination.transports._mcp_shared import _tool_result
from coordination.transports._mcp_types import (
    ReviewDecision,
)


def register(server: FastMCP, db: str | None) -> None:
    """Register these tools on the server."""

    @server.tool()
    def coordination_evidence_add(
        task: str,
        uri: str,
        actor: str,
        type: str = "artifact",
        session: str | None = None,
    ) -> CallToolResult:
        """Attach evidence to a task with actor/session attribution."""
        return _tool_result(
            db,
            "evidence_add",
            {"task": task, "uri": uri, "actor": actor, "type": type},
            session=session,
        )

    @server.tool()
    def coordination_evidence_list(
        task: str,
        filters: list[str] | None = None,
        order_by: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List task evidence."""
        return _tool_result(
            db,
            "evidence_list",
            {
                "task": task,
                "where": filters,
                "order_by": order_by,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_review_add(
        id: str,
        reviewer: str,
        artifact: str,
        scope: str,
        decision: ReviewDecision,
        task: str | None = None,
        accepted_items: str = "",
        required_changes: str = "",
        risks: str = "",
        blocked_claims: str = "",
        follow_up_tasks: str = "",
        session: str | None = None,
    ) -> CallToolResult:
        """Record a review through the canonical review service."""
        return _tool_result(
            db,
            "review_add",
            {
                "id": id,
                "reviewer": reviewer,
                "artifact": artifact,
                "scope": scope,
                "decision": decision,
                "task": task,
                "accepted_items": accepted_items,
                "required_changes": required_changes,
                "risks": risks,
                "blocked_claims": blocked_claims,
                "follow_up_tasks": follow_up_tasks,
            },
            session=session,
        )

    @server.tool()
    def coordination_review_list(
        task: str | None = None,
        filters: list[str] | None = None,
        order_by: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List reviews with bounded pagination."""
        return _tool_result(
            db,
            "review_list",
            {
                "task": task,
                "where": filters,
                "order_by": order_by,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_message_send(
        id: str,
        sender: str,
        recipient: str,
        body: str,
        task: str | None = None,
        tags: str = "",
        session: str | None = None,
    ) -> CallToolResult:
        """Send a durable coordination message."""
        return _tool_result(
            db,
            "message_send",
            {
                "id": id,
                "sender": sender,
                "recipient": recipient,
                "body": body,
                "task": task,
                "tags": tags,
            },
            session=session,
        )

    @server.tool()
    def coordination_message_list(
        recipient: str | None = None,
        task: str | None = None,
        filters: list[str] | None = None,
        order_by: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List direct and team messages, optionally for one task."""
        return _tool_result(
            db,
            "message_list",
            {
                "recipient": recipient,
                "task": task,
                "where": filters,
                "order_by": order_by,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_message_redact(
        id: str,
        actor: str,
        reason: str,
        session: str | None = None,
    ) -> CallToolResult:
        """Replace a message body with a marker; the row and audit remain."""
        return _tool_result(
            db,
            "message_redact",
            {"id": id, "actor": actor, "reason": reason},
            session=session,
        )
