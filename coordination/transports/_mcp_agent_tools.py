"""Agent registry and execution-session tools."""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from coordination.transports._mcp_shared import _tool_result
from coordination.transports._mcp_types import (
    ActorType,
    AgentStatus,
)


def register(server: FastMCP, db: str | None) -> None:
    """Register these tools on the server."""

    @server.tool()
    def coordination_agent_register(
        id: str,
        name: str,
        role: str,
        actor_type: ActorType = "ai",
        responsibilities: str = "",
        goal: str = "",
        operating_style: str = "",
        decision_authority: str = "",
        review_authority: str = "",
        escalation_rules: str = "",
        unavailable_for: str = "",
        actor: str | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Register one durable actor; harness and model do not belong here."""
        return _tool_result(
            db,
            "agent_add",
            {
                "id": id,
                "name": name,
                "role": role,
                "actor_type": actor_type,
                "responsibilities": responsibilities,
                "goal": goal,
                "operating_style": operating_style,
                "decision_authority": decision_authority,
                "review_authority": review_authority,
                "escalation_rules": escalation_rules,
                "unavailable_for": unavailable_for,
                "actor": actor,
            },
            session=session,
        )

    @server.tool()
    def coordination_agent_list(
        include_inactive: bool = False,
        actor_type: ActorType | None = None,
        filters: list[str] | None = None,
        order_by: list[str] | None = None,
        updated_since: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List durable actors with bounded pagination."""
        return _tool_result(
            db,
            "agent_list",
            {
                "all": include_inactive,
                "actor_type": actor_type,
                "where": filters,
                "order_by": order_by,
                "updated_since": updated_since,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_agent_update(
        id: str,
        name: str | None = None,
        role: str | None = None,
        actor_type: ActorType | None = None,
        status: AgentStatus | None = None,
        actor: str | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Update durable actor metadata or lifecycle status."""
        return _tool_result(
            db,
            "agent_update",
            {
                "id": id,
                "name": name,
                "role": role,
                "actor_type": actor_type,
                "status": status,
                "actor": actor,
            },
            session=session,
        )

    @server.tool()
    def coordination_session_start(
        id: str,
        agent: str,
        harness: str,
        model: str = "",
    ) -> CallToolResult:
        """Start one execution session for a durable actor."""
        return _tool_result(
            db,
            "session_start",
            {
                "id": id,
                "agent": agent,
                "harness": harness,
                "model": model,
            },
        )

    @server.tool()
    def coordination_session_list(
        agent: str | None = None,
        status: Literal["active", "ended"] | None = None,
        harness: str | None = None,
        filters: list[str] | None = None,
        order_by: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List execution sessions independently of durable actors."""
        return _tool_result(
            db,
            "session_list",
            {
                "agent": agent,
                "status": status,
                "harness": harness,
                "where": filters,
                "order_by": order_by,
                "limit": limit,
                "offset": offset,
            },
        )

    @server.tool()
    def coordination_session_heartbeat(id: str) -> CallToolResult:
        """Refresh one active execution session."""
        return _tool_result(db, "session_heartbeat", {"id": id})

    @server.tool()
    def coordination_session_end(id: str) -> CallToolResult:
        """End an active session after its task claims are released."""
        return _tool_result(db, "session_end", {"id": id})

    @server.tool()
    def coordination_session_recover(
        id: str,
        actor: str,
        reason: str,
        stale_after_seconds: int = 3600,
        force: bool = False,
        operator_session: str | None = None,
    ) -> CallToolResult:
        """Recover a stale session and block its claimed tasks atomically."""
        return _tool_result(
            db,
            "session_recover",
            {
                "id": id,
                "actor": actor,
                "reason": reason,
                "stale_after_seconds": stale_after_seconds,
                "force": force,
            },
            session=operator_session,
        )

    @server.tool()
    def coordination_session_sweep(
        actor: str,
        reason: str,
        stale_after_seconds: int = 3600,
        limit: int = 100,
        operator_session: str | None = None,
    ) -> CallToolResult:
        """Recover every session silent past the threshold, oldest first."""
        return _tool_result(
            db,
            "session_sweep",
            {
                "actor": actor,
                "reason": reason,
                "stale_after_seconds": stale_after_seconds,
                "limit": limit,
            },
            session=operator_session,
        )
