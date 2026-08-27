"""Task status transitions with claim and review gating."""

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
    resolve_reference,
    transaction,
)
from coordination.entities._tasks_shared import (
    STATUS_TRANSITIONS,
    reject_stale_revision,
)
from coordination.errors import EXIT_CONFLICT, EXIT_USAGE, fail


def status(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, params.actor)
        if params.session:
            require_active_session(connection, params.session, params.actor)
        task = require_row(
            connection,
            "SELECT status, revision, notes FROM tasks WHERE id = ?",
            (params.id,),
            f"task {params.id}",
        )
        if task["revision"] != params.if_revision:
            reject_stale_revision(params.id, params.if_revision, task["revision"])
        because = getattr(params, "because", None)
        if because:
            because = resolve_reference(connection, because)
        # `task release` is documented as an owned transition out of
        # in_progress, so it must not silently degrade into a plain status
        # change on a task nobody holds. Checked inside the transaction so the
        # claim cannot disappear between the check and the update.
        if getattr(params, "require_owned_claim", False) and task["status"] != (
            "in_progress"
        ):
            fail(
                "task_not_claimed",
                f"Task {params.id} is not claimed; release requires an"
                " in_progress task the actor and session own",
                EXIT_CONFLICT,
                {"task": params.id, "status": task["status"]},
            )
        if task["status"] == "in_progress" and not params.session:
            fail(
                "session_required",
                "Leaving in_progress requires the active claiming session",
                EXIT_USAGE,
                {"task": params.id},
            )
        if params.status == "in_progress":
            fail(
                "task_claim_required",
                "Use task claim to enter in_progress and establish exclusive ownership",
                EXIT_USAGE,
                {"task": params.id},
            )
        if params.status == task["status"]:
            fail(
                "invalid_task_state",
                f"Task {params.id} is already in status {params.status}",
                EXIT_CONFLICT,
                {"task": params.id, "status": params.status},
            )
        if params.status not in STATUS_TRANSITIONS[task["status"]]:
            fail(
                "invalid_task_transition",
                f"Task {params.id} cannot transition from {task['status']}"
                f" to {params.status}",
                EXIT_CONFLICT,
                {
                    "task": params.id,
                    "from": task["status"],
                    "to": params.status,
                    "allowed": sorted(STATUS_TRANSITIONS[task["status"]]),
                },
            )
        if task["status"] == "in_progress":
            active_claim = require_row(
                connection,
                "SELECT agent_id, session_id FROM task_claims WHERE task_id = ?",
                (params.id,),
                f"active claim for task {params.id}",
            )
            if params.actor != active_claim["agent_id"]:
                fail(
                    "task_claim_owner_mismatch",
                    f"Task {params.id} is claimed by {active_claim['agent_id']}",
                    EXIT_CONFLICT,
                    {
                        "task": params.id,
                        "claimed_by": active_claim["agent_id"],
                        "actor": params.actor,
                    },
                )
            if params.session != active_claim["session_id"]:
                fail(
                    "task_claim_session_mismatch",
                    f"Task {params.id} is claimed by session"
                    f" {active_claim['session_id']}",
                    EXIT_CONFLICT,
                    {
                        "task": params.id,
                        "claim_session_id": active_claim["session_id"],
                        "session_id": params.session,
                    },
                )
        cursor = connection.execute(
            """UPDATE tasks
               SET status = ?,
                   notes = CASE WHEN ? = '' THEN notes ELSE ? END,
                   revision = revision + 1,
                   updated_at = ?
               WHERE id = ? AND revision = ?""",
            (
                params.status,
                params.note,
                params.note,
                stamp,
                params.id,
                params.if_revision,
            ),
        )
        if cursor.rowcount != 1:
            actual = int(
                connection.execute(
                    "SELECT revision FROM tasks WHERE id = ?", (params.id,)
                ).fetchone()[0]
            )
            reject_stale_revision(params.id, params.if_revision, actual)
        if task["status"] == "in_progress":
            connection.execute(
                "DELETE FROM task_claims WHERE task_id = ?", (params.id,)
            )
        audit(
            connection,
            params.actor,
            "status",
            "task",
            params.id,
            (
                f"{task['status']} -> {params.status}; "
                f"revision {params.if_revision} -> {params.if_revision + 1}"
                + (f"; because={because}" if because else "")
            ),
            session_id=params.session,
            changes={
                "status": (task["status"], params.status),
                **(
                    {"notes": (task["notes"], params.note)}
                    if params.note and task["notes"] != params.note
                    else {}
                ),
            },
        )
    return {
        "id": params.id,
        "previous_status": task["status"],
        "status": params.status,
        "revision": params.if_revision + 1,
    }
