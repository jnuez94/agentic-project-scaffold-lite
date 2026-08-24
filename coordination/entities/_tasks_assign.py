"""Revision-guarded task assignment changes."""

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
from coordination.errors import EXIT_CONFLICT, EXIT_NOT_FOUND, EXIT_USAGE, fail


def assign(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    """Change task assignees with optimistic revision protection."""
    require_unique(params.add, "--add")
    require_unique(params.remove, "--remove")
    overlap = sorted(set(params.add) & set(params.remove))
    if overlap:
        fail(
            "invalid_arguments",
            "Task assignment cannot add and remove the same actor",
            EXIT_USAGE,
            {"actors": overlap},
        )
    if not params.add and not params.remove:
        fail(
            "invalid_arguments",
            "Task assignment requires at least one --add or --remove",
            EXIT_USAGE,
        )
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, params.actor)
        if params.session:
            require_active_session(connection, params.session, params.actor)
        task = require_row(
            connection,
            "SELECT status, revision FROM tasks WHERE id = ?",
            (params.id,),
            f"task {params.id}",
        )
        if task["revision"] != params.if_revision:
            reject_stale_revision(params.id, params.if_revision, task["revision"])
        require_claim_ownership(connection, params.id, params.actor, params.session)
        for assignee in params.add:
            require_row(
                connection,
                "SELECT id FROM agents WHERE id = ?",
                (assignee,),
                f"agent {assignee}",
            )
        claim = connection.execute(
            "SELECT agent_id FROM task_claims WHERE task_id = ?",
            (params.id,),
        ).fetchone()
        if claim is not None and str(claim["agent_id"]) in params.remove:
            fail(
                "task_claim_owner_mismatch",
                "The active claim owner cannot be removed from task assignees",
                EXIT_CONFLICT,
                {"task": params.id, "claimed_by": claim["agent_id"]},
            )
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT agent_id FROM task_assignees WHERE task_id = ?",
                (params.id,),
            )
        }
        missing = sorted(set(params.remove) - existing)
        if missing:
            fail(
                "not_found",
                "Task assignee to remove was not found",
                EXIT_NOT_FOUND,
                {"task": params.id, "assignees": missing},
            )
        for assignee in params.add:
            connection.execute(
                """INSERT OR IGNORE INTO task_assignees(
                     task_id, agent_id, assigned_at
                   ) VALUES (?, ?, ?)""",
                (params.id, assignee, stamp),
            )
        for assignee in params.remove:
            connection.execute(
                "DELETE FROM task_assignees WHERE task_id = ? AND agent_id = ?",
                (params.id, assignee),
            )
        updated_assignees = sorted((existing | set(params.add)) - set(params.remove))
        if updated_assignees == sorted(existing):
            fail(
                "invalid_arguments",
                "Task assignment did not change any assignees",
                EXIT_USAGE,
                {"task": params.id},
            )
        cursor = connection.execute(
            """UPDATE tasks
               SET revision = revision + 1, updated_at = ?
               WHERE id = ? AND revision = ?""",
            (stamp, params.id, params.if_revision),
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
            "assign",
            "task",
            params.id,
            (
                f"add={','.join(sorted(params.add))}; "
                f"remove={','.join(sorted(params.remove))}; "
                f"revision {params.if_revision} -> {params.if_revision + 1}"
            ),
            session_id=params.session,
        )
    return {
        "id": params.id,
        "revision": params.if_revision + 1,
        "assignees": updated_assignees,
    }
