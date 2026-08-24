"""Task write operations: create and revision-guarded update."""

from __future__ import annotations

import sqlite3
from typing import Any

from coordination.core import (
    Params,
    audit,
    now,
    require_active_actor,
    require_active_session,
    require_row,
    require_unique,
    transaction,
)
from coordination.entities._tasks_shared import (
    reject_stale_revision,
    require_claim_ownership,
)
from coordination.errors import EXIT_USAGE, fail


def create(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    stamp = now()
    require_unique(params.assignee, "--assignee")
    with transaction(connection):
        require_active_actor(connection, params.actor)
        for assignee in params.assignee:
            require_row(
                connection,
                "SELECT id FROM agents WHERE id = ?",
                (assignee,),
                f"agent {assignee}",
            )
        connection.execute(
            """INSERT INTO tasks(
                id, title, description, priority, tags, acceptance_criteria,
                next_steps, blocked_claims, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                params.id,
                params.title,
                params.description,
                params.priority,
                params.tags,
                params.acceptance,
                params.next_steps,
                params.blocked_claims,
                params.actor,
                stamp,
                stamp,
            ),
        )
        for assignee in params.assignee:
            connection.execute(
                "INSERT INTO task_assignees(task_id, agent_id, assigned_at)"
                " VALUES (?, ?, ?)",
                (params.id, assignee, stamp),
            )
        audit(
            connection,
            params.actor,
            "create",
            "task",
            params.id,
            session_id=params.session,
        )
    return {
        "id": params.id,
        "status": "todo",
        "revision": 1,
        "assignees": sorted(params.assignee),
    }


def update(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    """Update task content without changing its workflow state."""
    changes = {
        "title": params.title,
        "description": params.description,
        "priority": params.priority,
        "tags": params.tags,
        "acceptance_criteria": params.acceptance,
        "next_steps": params.next_steps,
        "blocked_claims": params.blocked_claims,
    }
    selected = {key: value for key, value in changes.items() if value is not None}
    if not selected:
        fail(
            "invalid_arguments",
            "Task update requires at least one changed field",
            EXIT_USAGE,
        )
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, params.actor)
        if params.session:
            require_active_session(connection, params.session, params.actor)
        task = require_row(
            connection,
            "SELECT revision FROM tasks WHERE id = ?",
            (params.id,),
            f"task {params.id}",
        )
        if task["revision"] != params.if_revision:
            reject_stale_revision(params.id, params.if_revision, task["revision"])
        require_claim_ownership(connection, params.id, params.actor, params.session)
        assignments = ", ".join(f"{column} = ?" for column in selected)
        cursor = connection.execute(
            f"""UPDATE tasks
                SET {assignments}, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?""",
            (*selected.values(), stamp, params.id, params.if_revision),
        )
        if cursor.rowcount != 1:
            actual = int(
                connection.execute(
                    "SELECT revision FROM tasks WHERE id = ?", (params.id,)
                ).fetchone()[0]
            )
            reject_stale_revision(params.id, params.if_revision, actual)
        audit(
            connection,
            params.actor,
            "update",
            "task",
            params.id,
            (
                f"fields={','.join(sorted(selected))}; "
                f"revision {params.if_revision} -> {params.if_revision + 1}"
            ),
            session_id=params.session,
        )
    return {
        "id": params.id,
        "revision": params.if_revision + 1,
        "updated_fields": sorted(selected),
    }
