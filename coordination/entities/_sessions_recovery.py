"""Stale-session recovery, claim release, and sweeps."""

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
    rows,
    transaction,
)
from coordination.entities._sessions_lifecycle import stale_cutoff
from coordination.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, EXIT_USAGE, fail


def recover_session_claims(
    connection: Any,
    session_id: str,
    *,
    actor: str,
    reason: str,
    operator_session: str | None,
    stamp: str,
    forced: bool = False,
) -> list[dict[str, Any]]:
    """End one active session and block every task it claims.

    This is the single reaper shared by `session recover`, `session sweep`,
    and claim-lease expiry in `task claim`. The caller holds the write
    transaction and has already decided the session may be reaped -- by
    staleness, by explicit force, or by an expired claim lease. Nothing here
    transfers a claim: tasks go to `blocked` with the reason in their notes,
    and whoever wants them claims fresh.
    """
    recovered_tasks: list[dict[str, Any]] = []
    claims = rows(
        connection.execute(
            """SELECT c.task_id, t.status, t.revision
               FROM task_claims c
               JOIN tasks t ON t.id = c.task_id
               WHERE c.session_id = ?
               ORDER BY c.task_id""",
            (session_id,),
        )
    )
    for claim in claims:
        if claim["status"] != "in_progress":
            fail(
                "coordination_invariant_violation",
                f"Claimed task {claim['task_id']} is not in progress",
                EXIT_ENVIRONMENT,
                {"task": claim["task_id"], "status": claim["status"]},
            )
        cursor = connection.execute(
            """UPDATE tasks
               SET status = 'blocked',
                   revision = revision + 1,
                   notes = CASE
                     WHEN notes = '' THEN ?
                     ELSE notes || char(10) || ?
                   END,
                   updated_at = ?
               WHERE id = ? AND status = 'in_progress' AND revision = ?""",
            (reason, reason, stamp, claim["task_id"], claim["revision"]),
        )
        if cursor.rowcount != 1:
            fail(
                "coordination_invariant_violation",
                f"Claimed task {claim['task_id']} changed during recovery",
                EXIT_ENVIRONMENT,
                {"task": claim["task_id"]},
            )
        connection.execute(
            "DELETE FROM task_claims WHERE task_id = ?",
            (claim["task_id"],),
        )
        audit(
            connection,
            actor,
            "recover_claim",
            "task",
            claim["task_id"],
            (
                f"session {session_id}; in_progress -> blocked; "
                f"revision {claim['revision']} -> {claim['revision'] + 1}; "
                f"{reason}"
            ),
            session_id=operator_session,
        )
        recovered_tasks.append(
            {
                "id": claim["task_id"],
                "status": "blocked",
                "revision": claim["revision"] + 1,
            }
        )
    connection.execute(
        """UPDATE agent_sessions
           SET status = 'ended', last_seen_at = ?, ended_at = ?
           WHERE id = ?""",
        (stamp, stamp, session_id),
    )
    audit(
        connection,
        actor,
        "recover",
        "session",
        session_id,
        f"forced; {reason}" if forced else reason,
        session_id=operator_session,
    )
    return recovered_tasks


def recover(connection: sqlite3.Connection, params: Params) -> dict[str, object]:
    if params.session == params.id:
        fail(
            "invalid_arguments",
            "The recovery operator session must differ from the recovered session",
            EXIT_USAGE,
        )
    stamp = now()
    cutoff = stale_cutoff(params.stale_after_seconds)
    forced = bool(params.force)
    with transaction(connection):
        require_active_actor(connection, params.actor)
        session = require_row(
            connection,
            """SELECT agent_id, status, last_seen_at
               FROM agent_sessions
               WHERE id = ?""",
            (params.id,),
            f"agent session {params.id}",
        )
        if session["status"] != "active":
            fail(
                "inactive_session",
                f"Agent session {params.id} is not active",
                EXIT_CONFLICT,
            )
        if not forced and session["last_seen_at"] > cutoff:
            fail(
                "session_not_stale",
                f"Agent session {params.id} has not reached the stale threshold",
                EXIT_CONFLICT,
                {
                    "session_id": params.id,
                    "last_seen_at": session["last_seen_at"],
                    "stale_cutoff": cutoff,
                },
            )
        recovered_tasks = recover_session_claims(
            connection,
            params.id,
            actor=params.actor,
            reason=params.reason,
            operator_session=params.session,
            stamp=stamp,
            forced=forced,
        )
    return {
        "id": params.id,
        "previous_status": "active",
        "status": "ended",
        "recovered_tasks": recovered_tasks,
        "forced": forced,
    }


def sweep(connection: sqlite3.Connection, params: Params) -> dict[str, object]:
    """Recover every active session that has been silent past the threshold.

    This is the operator's bounded reaper: `health` reports stale sessions,
    `sweep` acts on them, in one transaction, ordered oldest first. The
    operator's own session is never swept.
    """
    stamp = now()
    cutoff = stale_cutoff(params.stale_after_seconds)
    with transaction(connection):
        require_active_actor(connection, params.actor)
        if params.session:
            require_active_session(connection, params.session, params.actor)
        candidates = rows(
            connection.execute(
                """SELECT id FROM agent_sessions
                   WHERE status = 'active' AND last_seen_at <= ? AND id <> ?
                   ORDER BY last_seen_at, id LIMIT ?""",
                (cutoff, params.session or "", params.limit + 1),
            )
        )
        truncated = len(candidates) > params.limit
        recovered_sessions = [
            {
                "id": candidate["id"],
                "recovered_tasks": recover_session_claims(
                    connection,
                    str(candidate["id"]),
                    actor=params.actor,
                    reason=params.reason,
                    operator_session=params.session,
                    stamp=stamp,
                ),
            }
            for candidate in candidates[: params.limit]
        ]
    return {
        "stale_after_seconds": params.stale_after_seconds,
        "recovered_sessions": recovered_sessions,
        "truncated": truncated,
    }
