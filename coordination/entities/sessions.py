"""Agent execution-session commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    MIN_STALE_SECONDS,
    audit,
    connect,
    discover_db,
    identifier,
    list_limit,
    list_offset,
    now,
    optional_text,
    require_active_actor,
    require_active_session,
    require_row,
    required_text,
    rows,
    stale_seconds,
    transaction,
)
from coordination.entities.audit import register_history
from coordination.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, EXIT_USAGE, fail


SESSION_STATUSES = ("active", "ended")


def require_open_session(
    connection: Any,
    session_id: str,
) -> Any:
    session = require_row(
        connection,
        "SELECT agent_id, status FROM agent_sessions WHERE id = ?",
        (session_id,),
        f"agent session {session_id}",
    )
    if session["status"] != "active":
        fail(
            "inactive_session",
            f"Agent session {session_id} is not active",
            EXIT_CONFLICT,
            {"session_id": session_id},
        )
    return session


def start(args: argparse.Namespace) -> dict[str, object]:
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, args.agent)
        connection.execute(
            """INSERT INTO agent_sessions(
                 id, agent_id, harness, model, status, started_at, last_seen_at
               ) VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (args.id, args.agent, args.harness, args.model, stamp, stamp),
        )
        audit(
            connection,
            args.agent,
            "start",
            "session",
            args.id,
            args.harness,
            session_id=args.id,
        )
    return {
        "id": args.id,
        "agent_id": args.agent,
        "harness": args.harness,
        "model": args.model,
        "status": "active",
    }


def list_sessions(args: argparse.Namespace) -> list[dict[str, Any]]:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM agent_sessions"
    conditions: list[str] = []
    parameters: list[Any] = []
    if args.agent:
        conditions.append("agent_id = ?")
        parameters.append(args.agent)
    if args.status:
        conditions.append("status = ?")
        parameters.append(args.status)
    if args.harness:
        conditions.append("harness = ?")
        parameters.append(args.harness)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY started_at, id LIMIT ? OFFSET ?"
    parameters.extend((args.limit, args.offset))
    return rows(connection.execute(query, parameters))


def heartbeat(args: argparse.Namespace) -> dict[str, str]:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        session = require_open_session(connection, args.id)
        audit(
            connection,
            session["agent_id"],
            "heartbeat",
            "session",
            args.id,
            session_id=args.id,
        )
    return {"id": args.id, "status": "active"}


def end(args: argparse.Namespace) -> dict[str, str]:
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
        session = require_open_session(connection, args.id)
        claimed_tasks = [
            str(row[0])
            for row in connection.execute(
                "SELECT task_id FROM task_claims WHERE session_id = ? ORDER BY task_id",
                (args.id,),
            )
        ]
        if claimed_tasks:
            fail(
                "session_has_active_claims",
                f"Session {args.id} cannot end while it owns active task claims",
                EXIT_CONFLICT,
                {"session_id": args.id, "tasks": claimed_tasks},
            )
        audit(
            connection,
            session["agent_id"],
            "end",
            "session",
            args.id,
            session_id=args.id,
        )
        connection.execute(
            """UPDATE agent_sessions
               SET status = 'ended', last_seen_at = ?, ended_at = ?
               WHERE id = ?""",
            (stamp, stamp, args.id),
        )
    return {"id": args.id, "status": "ended"}


def stale_cutoff(seconds: int) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(seconds=seconds))
        .replace(microsecond=0)
        .isoformat()
    )


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


def recover(args: argparse.Namespace) -> dict[str, object]:
    if args.session == args.id:
        fail(
            "invalid_arguments",
            "The recovery operator session must differ from the recovered session",
            EXIT_USAGE,
        )
    connection = connect(discover_db(args.db))
    stamp = now()
    cutoff = stale_cutoff(args.stale_after_seconds)
    forced = bool(args.force)
    with transaction(connection):
        require_active_actor(connection, args.actor)
        session = require_row(
            connection,
            """SELECT agent_id, status, last_seen_at
               FROM agent_sessions
               WHERE id = ?""",
            (args.id,),
            f"agent session {args.id}",
        )
        if session["status"] != "active":
            fail(
                "inactive_session",
                f"Agent session {args.id} is not active",
                EXIT_CONFLICT,
            )
        if not forced and session["last_seen_at"] > cutoff:
            fail(
                "session_not_stale",
                f"Agent session {args.id} has not reached the stale threshold",
                EXIT_CONFLICT,
                {
                    "session_id": args.id,
                    "last_seen_at": session["last_seen_at"],
                    "stale_cutoff": cutoff,
                },
            )
        recovered_tasks = recover_session_claims(
            connection,
            args.id,
            actor=args.actor,
            reason=args.reason,
            operator_session=args.session,
            stamp=stamp,
            forced=forced,
        )
    return {
        "id": args.id,
        "previous_status": "active",
        "status": "ended",
        "recovered_tasks": recovered_tasks,
        "forced": forced,
    }


def sweep(args: argparse.Namespace) -> dict[str, object]:
    """Recover every active session that has been silent past the threshold.

    This is the operator's bounded reaper: `health` reports stale sessions,
    `sweep` acts on them, in one transaction, ordered oldest first. The
    operator's own session is never swept.
    """
    connection = connect(discover_db(args.db))
    stamp = now()
    cutoff = stale_cutoff(args.stale_after_seconds)
    with transaction(connection):
        require_active_actor(connection, args.actor)
        if args.session:
            require_active_session(connection, args.session, args.actor)
        candidates = rows(
            connection.execute(
                """SELECT id FROM agent_sessions
                   WHERE status = 'active' AND last_seen_at <= ? AND id <> ?
                   ORDER BY last_seen_at, id LIMIT ?""",
                (cutoff, args.session or "", args.limit + 1),
            )
        )
        truncated = len(candidates) > args.limit
        recovered_sessions = [
            {
                "id": candidate["id"],
                "recovered_tasks": recover_session_claims(
                    connection,
                    str(candidate["id"]),
                    actor=args.actor,
                    reason=args.reason,
                    operator_session=args.session,
                    stamp=stamp,
                ),
            }
            for candidate in candidates[: args.limit]
        ]
    return {
        "stale_after_seconds": args.stale_after_seconds,
        "recovered_sessions": recovered_sessions,
        "truncated": truncated,
    }


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    session = commands.add_parser(
        "session",
        help="Manage agent execution sessions",
    ).add_subparsers(dest="session_command", required=True)

    start_parser = session.add_parser("start")
    start_parser.add_argument("--id", required=True, type=identifier)
    start_parser.add_argument("--agent", required=True, type=identifier)
    start_parser.add_argument("--harness", required=True, type=required_text)
    start_parser.add_argument("--model", default="", type=optional_text)
    start_parser.set_defaults(func=start)

    list_parser = session.add_parser("list")
    list_parser.add_argument("--agent", type=identifier)
    list_parser.add_argument("--status", choices=SESSION_STATUSES)
    list_parser.add_argument("--harness", type=required_text)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_sessions)

    heartbeat_parser = session.add_parser("heartbeat")
    heartbeat_parser.add_argument("id", type=identifier)
    heartbeat_parser.set_defaults(func=heartbeat)

    end_parser = session.add_parser("end")
    end_parser.add_argument("id", type=identifier)
    end_parser.set_defaults(func=end)

    recover_parser = session.add_parser(
        "recover",
        help="End a stale session and block its claimed tasks",
    )
    recover_parser.add_argument("id", type=identifier)
    recover_parser.add_argument("--actor", required=True, type=identifier)
    recover_parser.add_argument("--reason", required=True, type=required_text)
    recover_parser.add_argument(
        "--stale-after-seconds",
        type=stale_seconds,
        default=3600,
        help=(
            "Seconds of silence before a session counts as stale"
            f" (minimum {MIN_STALE_SECONDS})"
        ),
    )
    recover_parser.add_argument(
        "--force",
        action="store_true",
        help="Recover even if the session is not stale; audited as forced",
    )
    recover_parser.set_defaults(func=recover)

    sweep_parser = session.add_parser(
        "sweep",
        help="Recover every active session silent past the stale threshold",
    )
    sweep_parser.add_argument("--actor", required=True, type=identifier)
    sweep_parser.add_argument("--reason", required=True, type=required_text)
    sweep_parser.add_argument(
        "--stale-after-seconds",
        type=stale_seconds,
        default=3600,
    )
    sweep_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    sweep_parser.set_defaults(func=sweep)
    register_history(session, "session")
