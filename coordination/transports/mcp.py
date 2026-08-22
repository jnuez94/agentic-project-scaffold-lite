"""Optional local stdio MCP transport for canonical coordination services."""

from __future__ import annotations

import argparse
import json
import signal
from typing import Annotated, Any, Literal, NoReturn

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from coordination.core import MAX_IDENTIFIER_ARRAY_ITEMS, path_argument
from coordination.errors import (
    EXIT_USAGE,
    CoordinationError,
    emit_error,
    error_envelope,
    fail,
)
from coordination.service import CoordinationService


ActorType = Literal["ai", "human", "service"]
AgentStatus = Literal["active", "inactive"]
TaskStatus = Literal["todo", "in_progress", "review", "blocked", "done"]
ReleaseStatus = Literal["todo", "review", "blocked"]
ReviewDecision = Literal[
    "accepted",
    "conditionally_accepted",
    "changes_requested",
    "rejected",
]
DecisionStatus = Literal["proposed", "accepted", "superseded", "rejected"]
DependencyType = Literal[
    "blocks",
    "informs",
    "review_required",
    "evidence_required",
]
ArtifactStatus = Literal["draft", "review", "accepted", "superseded"]
EscalationStatus = Literal["open", "in_review", "resolved", "closed_no_action"]
EscalationResolution = Literal["resolved", "closed_no_action"]
HealthSection = Literal[
    "unowned_tasks",
    "stale_tasks",
    "stale_sessions",
    "unclaimed_in_progress_tasks",
    "invalid_active_claims",
    "active_blockers",
    "done_without_evidence",
    "open_escalations",
    "tasks_awaiting_review",
]
SummarySection = Literal["totals", "task_status", "task_priority", "workload"]
IdentifierArray = Annotated[
    list[str],
    Field(max_length=MAX_IDENTIFIER_ARRAY_ITEMS),
]


def _tool_result(
    db: str | None,
    operation: str,
    parameters: dict[str, object],
    *,
    session: str | None = None,
) -> CallToolResult:
    try:
        data = CoordinationService(db=db, session=session, contain_paths=True).invoke(
            operation,
            parameters,
        )
        envelope: dict[str, Any] = {"ok": True, "data": data}
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


def build_server(*, db: str | None = None) -> FastMCP:
    """Build the fixed stdio-only MCP server for one project database."""
    server = FastMCP(
        "Harness-neutral SQLite coordination",
        instructions=(
            "Use explicit durable actor IDs and execution-session IDs. "
            "Harness and model identify sessions, never actors. All tools use "
            "the same canonical SQLite coordination services as the CLI."
        ),
        json_response=True,
    )

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
            },
            session=session,
        )

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
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List task evidence."""
        return _tool_result(
            db,
            "evidence_list",
            {"task": task, "limit": limit, "offset": offset},
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
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List reviews with bounded pagination."""
        return _tool_result(
            db,
            "review_list",
            {"task": task, "limit": limit, "offset": offset},
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
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List direct and team messages, optionally for one task."""
        return _tool_result(
            db,
            "message_list",
            {"recipient": recipient, "task": task, "limit": limit, "offset": offset},
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
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List decisions."""
        return _tool_result(
            db,
            "decision_list",
            {"limit": limit, "offset": offset},
        )

    @server.tool()
    def coordination_decision_status(
        id: str,
        status: DecisionStatus,
        actor: str,
        if_status: DecisionStatus | None = None,
        note: str = "",
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
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List artifact metadata; artifact contents are never opened."""
        return _tool_result(
            db,
            "artifact_list",
            {"status": status, "limit": limit, "offset": offset},
        )

    @server.tool()
    def coordination_artifact_status(
        id: str,
        status: ArtifactStatus,
        actor: str,
        if_status: ArtifactStatus | None = None,
        session: str | None = None,
    ) -> CallToolResult:
        """Update artifact review status, optionally only from `if_status`."""
        return _tool_result(
            db,
            "artifact_status",
            {"id": id, "status": status, "actor": actor, "if_status": if_status},
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
        limit: int = 100,
        offset: int = 0,
    ) -> CallToolResult:
        """List escalations."""
        return _tool_result(
            db,
            "escalation_list",
            {"status": status, "limit": limit, "offset": offset},
        )

    @server.tool()
    def coordination_escalation_resolve(
        id: str,
        resolution: str,
        actor: str,
        status: EscalationResolution = "resolved",
        follow_up_tasks: str = "",
        if_status: EscalationStatus | None = None,
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
            },
            session=session,
        )

    @server.tool()
    def coordination_backup(
        output: str,
        confirmation: str,
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
            {"output": output, "force": False},
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

    return server


class MCPArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> NoReturn:
        # Every other failure path in this project reports a JSON envelope, so
        # a launcher argument error must not fall back to argparse's prose.
        raise CoordinationError("invalid_arguments", message, EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    parser = MCPArgumentParser(
        prog="coordination-mcp",
        description="Local stdio MCP transport for SQLite coordination",
    )
    parser.add_argument(
        "--db",
        type=path_argument,
        help="SQLite coordination database; otherwise discover from the server cwd",
    )
    try:
        args = parser.parse_args(argv)
    except CoordinationError as error:
        emit_error(error)
        return error.exit_code
    # A long-lived server is the process most likely to be SIGTERMed -- by the
    # client on shutdown, by the host on reboot. Python's default handler
    # terminates without unwinding, so an in-flight backup's `finally` never
    # ran and its staging file was orphaned. Map the termination signals to an
    # interrupt so the stack unwinds: transactions roll back, staging files
    # are removed, and the server exits cleanly.
    for signal_name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), _interrupt)
    try:
        build_server(db=args.db).run(transport="stdio")
    except KeyboardInterrupt:
        return 0
    return 0


def _interrupt(signum: int, _frame: object) -> None:
    raise KeyboardInterrupt(signum)


if __name__ == "__main__":
    raise SystemExit(main())
