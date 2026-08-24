"""Task tools: creation, reads, claims, transitions, release."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from coordination.transports._mcp_shared import _tool_result
from coordination.transports._mcp_types import (
    IdentifierArray,
    ReleaseStatus,
    TaskStatus,
)


def register(server: FastMCP, db: str | None) -> None:
    """Register these tools on the server."""

    @server.tool()
    def coordination_task_create(
        id: str,
        title: str,
        actor: str,
        description: str = "",
        priority: int = 3,
        tags: str = "",
        acceptance: str = "",
        next_steps: str = "",
        blocked_claims: str = "",
        assignees: IdentifierArray | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Create a task with explicit actor attribution."""
        return _tool_result(
            db,
            "task_create",
            {
                "id": id,
                "title": title,
                "actor": actor,
                "description": description,
                "priority": priority,
                "tags": tags,
                "acceptance": acceptance,
                "next_steps": next_steps,
                "blocked_claims": blocked_claims,
                "assignee": assignees,
            },
            session=session,
        )

    @server.tool()
    def coordination_task_list(
        status: TaskStatus | list[TaskStatus] | None = None,
        assignee: str | None = None,
        tag: str | None = None,
        filters: list[str] | None = None,
        order_by: list[str] | None = None,
        updated_since: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List tasks with deterministic ordering and bounded pagination."""
        return _tool_result(
            db,
            "task_list",
            {
                "status": status,
                "assignee": assignee,
                "tag": tag,
                "where": filters,
                "order_by": order_by,
                "updated_since": updated_since,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_task_inspect(id: str) -> CallToolResult:
        """Inspect one task with evidence, dependencies, and reviews."""
        return _tool_result(db, "task_show", {"id": id})

    @server.tool()
    def coordination_task_assign(
        id: str,
        actor: str,
        if_revision: int,
        add: IdentifierArray | None = None,
        remove: IdentifierArray | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Change task assignees under optimistic revision control."""
        return _tool_result(
            db,
            "task_assign",
            {
                "id": id,
                "actor": actor,
                "if_revision": if_revision,
                "add": add,
                "remove": remove,
            },
            session=session,
        )

    @server.tool()
    def coordination_task_claim(
        id: str,
        agent: str,
        if_revision: int,
        session: str,
    ) -> CallToolResult:
        """Claim a task exclusively for one actor execution session."""
        return _tool_result(
            db,
            "task_claim",
            {
                "id": id,
                "agent": agent,
                "if_revision": if_revision,
            },
            session=session,
        )

    @server.tool()
    def coordination_task_update(
        id: str,
        actor: str,
        if_revision: int,
        title: str | None = None,
        description: str | None = None,
        priority: int | None = None,
        tags: str | None = None,
        acceptance: str | None = None,
        next_steps: str | None = None,
        blocked_claims: str | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Update task content without changing workflow state."""
        return _tool_result(
            db,
            "task_update",
            {
                "id": id,
                "actor": actor,
                "if_revision": if_revision,
                "title": title,
                "description": description,
                "priority": priority,
                "tags": tags,
                "acceptance": acceptance,
                "next_steps": next_steps,
                "blocked_claims": blocked_claims,
            },
            session=session,
        )

    @server.tool()
    def coordination_task_transition(
        id: str,
        status: TaskStatus,
        actor: str,
        if_revision: int,
        note: str = "",
        because: str | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Transition a task using the canonical workflow rules."""
        return _tool_result(
            db,
            "task_status",
            {
                "id": id,
                "status": status,
                "actor": actor,
                "if_revision": if_revision,
                "note": note,
                "because": because,
            },
            session=session,
        )

    @server.tool()
    def coordination_task_release(
        id: str,
        status: ReleaseStatus,
        actor: str,
        if_revision: int,
        session: str,
        note: str = "",
        because: str | None = None,
    ) -> CallToolResult:
        """Release an owned claim and transition out of in_progress."""
        return _tool_result(
            db,
            "task_release",
            {
                "id": id,
                "status": status,
                "actor": actor,
                "if_revision": if_revision,
                "note": note,
                "because": because,
            },
            session=session,
        )
