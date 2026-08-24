"""Decision and dependency tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from coordination.transports._mcp_shared import _tool_result
from coordination.transports._mcp_types import (
    DecisionStatus,
    DependencyType,
)


def register(server: FastMCP, db: str | None) -> None:
    """Register these tools on the server."""

    @server.tool()
    def coordination_decision_add(
        id: str,
        title: str,
        owner: str,
        context: str,
        decision: str,
        status: DecisionStatus = "proposed",
        options: str = "",
        implications: str = "",
        evidence: str = "",
        blocked_claims: str = "",
        review_required: str = "",
        session: str | None = None,
    ) -> CallToolResult:
        """Record a durable decision."""
        return _tool_result(
            db,
            "decision_add",
            {
                "id": id,
                "title": title,
                "owner": owner,
                "context": context,
                "decision": decision,
                "status": status,
                "options": options,
                "implications": implications,
                "evidence": evidence,
                "blocked_claims": blocked_claims,
                "review_required": review_required,
            },
            session=session,
        )

    @server.tool()
    def coordination_decision_list(
        filters: list[str] | None = None,
        order_by: list[str] | None = None,
        updated_since: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List decisions."""
        return _tool_result(
            db,
            "decision_list",
            {
                "where": filters,
                "order_by": order_by,
                "updated_since": updated_since,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_decision_status(
        id: str,
        status: DecisionStatus,
        actor: str,
        if_status: DecisionStatus | None = None,
        note: str = "",
        because: str | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Record a ruling on a decision, optionally only from `if_status`."""
        return _tool_result(
            db,
            "decision_status",
            {
                "id": id,
                "status": status,
                "actor": actor,
                "if_status": if_status,
                "note": note,
                "because": because,
            },
            session=session,
        )

    @server.tool()
    def coordination_dependency_add(
        task: str,
        depends_on: str,
        actor: str,
        type: DependencyType = "blocks",
        rationale: str = "",
        session: str | None = None,
    ) -> CallToolResult:
        """Add a typed task dependency."""
        return _tool_result(
            db,
            "dependency_add",
            {
                "task": task,
                "depends_on": depends_on,
                "actor": actor,
                "type": type,
                "rationale": rationale,
            },
            session=session,
        )

    @server.tool()
    def coordination_dependency_resolve(
        task: str,
        depends_on: str,
        actor: str,
        type: DependencyType = "blocks",
        session: str | None = None,
    ) -> CallToolResult:
        """Resolve a typed task dependency."""
        return _tool_result(
            db,
            "dependency_resolve",
            {
                "task": task,
                "depends_on": depends_on,
                "actor": actor,
                "type": type,
            },
            session=session,
        )
