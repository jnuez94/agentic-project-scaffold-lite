"""Artifact and escalation tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from coordination.transports._mcp_shared import _tool_result
from coordination.transports._mcp_types import (
    ArtifactStatus,
    EscalationResolution,
    EscalationStatus,
    IdentifierArray,
)


def register(server: FastMCP, db: str | None) -> None:
    """Register these tools on the server."""

    @server.tool()
    def coordination_artifact_add(
        id: str,
        uri: str,
        owner: str,
        type: str,
        status: ArtifactStatus = "draft",
        usage_boundaries: str = "",
        tasks: IdentifierArray | None = None,
        reviewers: IdentifierArray | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Register an artifact without reading or writing its URI."""
        return _tool_result(
            db,
            "artifact_add",
            {
                "id": id,
                "uri": uri,
                "owner": owner,
                "type": type,
                "status": status,
                "usage_boundaries": usage_boundaries,
                "task": tasks,
                "reviewer": reviewers,
            },
            session=session,
        )

    @server.tool()
    def coordination_artifact_list(
        status: ArtifactStatus | None = None,
        filters: list[str] | None = None,
        order_by: list[str] | None = None,
        updated_since: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List artifact metadata; artifact contents are never opened."""
        return _tool_result(
            db,
            "artifact_list",
            {
                "status": status,
                "where": filters,
                "order_by": order_by,
                "updated_since": updated_since,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_artifact_status(
        id: str,
        status: ArtifactStatus,
        actor: str,
        if_status: ArtifactStatus | None = None,
        because: str | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Update artifact review status, optionally only from `if_status`."""
        return _tool_result(
            db,
            "artifact_status",
            {
                "id": id,
                "status": status,
                "actor": actor,
                "if_status": if_status,
                "because": because,
            },
            session=session,
        )

    @server.tool()
    def coordination_artifact_update(
        id: str,
        actor: str,
        uri: str | None = None,
        type: str | None = None,
        usage_boundaries: str | None = None,
        if_status: ArtifactStatus | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Correct artifact metadata such as a moved URI."""
        return _tool_result(
            db,
            "artifact_update",
            {
                "id": id,
                "actor": actor,
                "uri": uri,
                "type": type,
                "usage_boundaries": usage_boundaries,
                "if_status": if_status,
            },
            session=session,
        )

    @server.tool()
    def coordination_escalation_add(
        id: str,
        raised_by: str,
        owner: str,
        issue: str,
        requested_decision: str,
        related_tasks: str = "",
        needed_by: str | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Open an escalation."""
        return _tool_result(
            db,
            "escalation_add",
            {
                "id": id,
                "raised_by": raised_by,
                "owner": owner,
                "issue": issue,
                "requested_decision": requested_decision,
                "related_tasks": related_tasks,
                "needed_by": needed_by,
            },
            session=session,
        )

    @server.tool()
    def coordination_escalation_list(
        status: EscalationStatus | None = None,
        filters: list[str] | None = None,
        order_by: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List escalations."""
        return _tool_result(
            db,
            "escalation_list",
            {
                "status": status,
                "where": filters,
                "order_by": order_by,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_escalation_resolve(
        id: str,
        resolution: str,
        actor: str,
        status: EscalationResolution = "resolved",
        follow_up_tasks: str = "",
        if_status: EscalationStatus | None = None,
        because: str | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Resolve or close an escalation, optionally only from `if_status`."""
        return _tool_result(
            db,
            "escalation_resolve",
            {
                "id": id,
                "resolution": resolution,
                "actor": actor,
                "status": status,
                "follow_up_tasks": follow_up_tasks,
                "if_status": if_status,
                "because": because,
            },
            session=session,
        )
