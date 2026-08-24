"""Exclusive task claims with stale-lease reaping."""

from __future__ import annotations

import sqlite3
from typing import Any

from coordination.core import (
    SESSION_LEASE_SECONDS,
    Params,
    audit,
    now,
    require_active_actor,
    require_active_session,
    require_row,
    transaction,
)
from coordination.entities._tasks_shared import reject_stale_revision
from coordination.entities.sessions import recover_session_claims, stale_cutoff
from coordination.errors import EXIT_CONFLICT, EXIT_USAGE, fail


def claim(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    if not params.session:
        fail(
            "session_required",
            "Task claims require an active session via --session"
            " or COORDINATION_SESSION",
            EXIT_USAGE,
        )
    stamp = now()
    result: dict[str, Any]
    with transaction(connection):
        require_active_actor(connection, params.agent)
        require_active_session(connection, params.session, params.agent)
        task = require_row(
            connection,
            "SELECT status, revision FROM tasks WHERE id = ?",
            (params.id,),
            f"task {params.id}",
        )
        active_claim = connection.execute(
            "SELECT agent_id, session_id, claimed_at FROM task_claims"
            " WHERE task_id = ?",
            (params.id,),
        ).fetchone()
        # The revision the claim UPDATE must match. Reaping an expired lease
        # first bumps it by one, so the caller's `if_revision` is checked
        # against what they observed, and the claim lands on the next revision.
        claim_revision = params.if_revision
        reaped_session: str | None = None
        if task["revision"] != params.if_revision:
            if (
                task["revision"] == params.if_revision + 1
                and task["status"] == "in_progress"
                and active_claim is not None
                and active_claim["agent_id"] == params.agent
                and active_claim["session_id"] == params.session
            ):
                result = {
                    "id": params.id,
                    "status": "in_progress",
                    "revision": task["revision"],
                    "agent": params.agent,
                    "session_id": params.session,
                    "claimed": False,
                    "idempotent_replay": True,
                    "reaped_session": None,
                }
                return result
            reject_stale_revision(params.id, params.if_revision, task["revision"])
        if task["status"] == "in_progress":
            # An exclusive claim is a lease, not a lock. When the holding
            # session has been silent past SESSION_LEASE_SECONDS it is reaped
            # here -- the same recovery `session recover` performs, attributed
            # to the claimant -- and the claim proceeds from `blocked`. A live
            # holder is never displaced. Checked inside the write transaction
            # so the holder cannot heartbeat between the check and the reap.
            holder = (
                connection.execute(
                    "SELECT id, last_seen_at FROM agent_sessions WHERE id = ?",
                    (active_claim["session_id"],),
                ).fetchone()
                if active_claim is not None
                else None
            )
            if holder is None or holder["last_seen_at"] > stale_cutoff(
                SESSION_LEASE_SECONDS
            ):
                fail(
                    "task_already_claimed",
                    f"Task {params.id} already has an active claim",
                    EXIT_CONFLICT,
                    {
                        "task": params.id,
                        "agent": active_claim["agent_id"] if active_claim else None,
                        "session_id": (
                            active_claim["session_id"] if active_claim else None
                        ),
                    },
                )
            recover_session_claims(
                connection,
                str(holder["id"]),
                actor=params.agent,
                reason=(
                    f"claim lease expired after {SESSION_LEASE_SECONDS} seconds"
                    f" of silence; reclaimed by {params.agent}"
                ),
                operator_session=params.session,
                stamp=stamp,
            )
            reaped_session = str(holder["id"])
            claim_revision = params.if_revision + 1
        elif task["status"] not in ("todo", "review", "blocked"):
            fail(
                "invalid_task_state",
                f"Task {params.id} cannot be claimed from status {task['status']}",
                EXIT_CONFLICT,
                {"task": params.id, "status": task["status"]},
            )
        connection.execute(
            """INSERT INTO task_claims(task_id, agent_id, session_id, claimed_at)
               VALUES (?, ?, ?, ?)""",
            (params.id, params.agent, params.session, stamp),
        )
        cursor = connection.execute(
            """UPDATE tasks
               SET status = 'in_progress', revision = revision + 1, updated_at = ?
               WHERE id = ? AND revision = ?""",
            (stamp, params.id, claim_revision),
        )
        if cursor.rowcount != 1:
            actual = int(
                connection.execute(
                    "SELECT revision FROM tasks WHERE id = ?", (params.id,)
                ).fetchone()[0]
            )
            reject_stale_revision(params.id, params.if_revision, actual)
        connection.execute(
            """INSERT OR IGNORE INTO task_assignees(task_id, agent_id, assigned_at)
               VALUES (?, ?, ?)""",
            (params.id, params.agent, stamp),
        )
        audit(
            connection,
            params.agent,
            "claim",
            "task",
            params.id,
            f"revision {claim_revision} -> {claim_revision + 1}"
            + (f"; reaped session {reaped_session}" if reaped_session else ""),
            session_id=params.session,
        )
        result = {
            "id": params.id,
            "status": "in_progress",
            "revision": claim_revision + 1,
            "agent": params.agent,
            "session_id": params.session,
            "claimed": True,
            "idempotent_replay": False,
            "reaped_session": reaped_session,
        }
    return result
