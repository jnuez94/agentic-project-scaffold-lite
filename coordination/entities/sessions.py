"""Agent execution-session commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from typing import Any

from coordination.core import (
    audit,
    connect,
    discover_db,
    emit,
    now,
    require_row,
    rows,
    transaction,
)
from coordination.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, EXIT_USAGE, fail


SESSION_STATUSES = ("active", "ended")


def start(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
        require_row(
            connection,
            "SELECT id FROM agents WHERE id = ? AND status = 'active'",
            (args.agent,),
            f"active agent {args.agent}",
        )
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
    emit(
        {
            "id": args.id,
            "agent_id": args.agent,
            "harness": args.harness,
            "model": args.model,
            "status": "active",
        }
    )


def list_sessions(args: argparse.Namespace) -> None:
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
    query += " ORDER BY started_at, id"
    emit(rows(connection.execute(query, parameters)))


def heartbeat(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        session = require_row(
            connection,
            "SELECT agent_id FROM agent_sessions WHERE id = ? AND status = 'active'",
            (args.id,),
            f"active agent session {args.id}",
        )
        audit(
            connection,
            session["agent_id"],
            "heartbeat",
            "session",
            args.id,
            session_id=args.id,
        )
    emit({"id": args.id, "status": "active"})


def end(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
        session = require_row(
            connection,
            "SELECT agent_id FROM agent_sessions WHERE id = ? AND status = 'active'",
            (args.id,),
            f"active agent session {args.id}",
        )
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
    emit({"id": args.id, "status": "ended"})


def recover(args: argparse.Namespace) -> None:
    if args.stale_after_seconds < 0:
        fail(
            "invalid_arguments",
            "--stale-after-seconds must be zero or greater",
            EXIT_USAGE,
        )
    connection = connect(discover_db(args.db))
    stamp = now()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=args.stale_after_seconds)
    ).replace(microsecond=0).isoformat()
    recovered_tasks: list[dict[str, Any]] = []
    with transaction(connection):
        require_row(
            connection,
            "SELECT id FROM agents WHERE id = ? AND status = 'active'",
            (args.actor,),
            f"active agent {args.actor}",
        )
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
        if session["last_seen_at"] > cutoff:
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
        claims = rows(
            connection.execute(
                """SELECT c.task_id, t.status, t.revision
                   FROM task_claims c
                   JOIN tasks t ON t.id = c.task_id
                   WHERE c.session_id = ?
                   ORDER BY c.task_id""",
                (args.id,),
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
                (
                    args.reason,
                    args.reason,
                    stamp,
                    claim["task_id"],
                    claim["revision"],
                ),
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
                args.actor,
                "recover_claim",
                "task",
                claim["task_id"],
                (
                    f"session {args.id}; in_progress -> blocked; "
                    f"revision {claim['revision']} -> {claim['revision'] + 1}; "
                    f"{args.reason}"
                ),
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
            (stamp, stamp, args.id),
        )
        audit(
            connection,
            args.actor,
            "recover",
            "session",
            args.id,
            args.reason,
        )
    emit(
        {
            "id": args.id,
            "previous_status": "active",
            "status": "ended",
            "recovered_tasks": recovered_tasks,
        }
    )


def register(commands: argparse._SubParsersAction) -> None:
    session = commands.add_parser(
        "session",
        help="Manage agent execution sessions",
    ).add_subparsers(dest="session_command", required=True)

    start_parser = session.add_parser("start")
    start_parser.add_argument("--id", required=True)
    start_parser.add_argument("--agent", required=True)
    start_parser.add_argument("--harness", required=True)
    start_parser.add_argument("--model", default="")
    start_parser.set_defaults(func=start)

    list_parser = session.add_parser("list")
    list_parser.add_argument("--agent")
    list_parser.add_argument("--status", choices=SESSION_STATUSES)
    list_parser.add_argument("--harness")
    list_parser.set_defaults(func=list_sessions)

    heartbeat_parser = session.add_parser("heartbeat")
    heartbeat_parser.add_argument("id")
    heartbeat_parser.set_defaults(func=heartbeat)

    end_parser = session.add_parser("end")
    end_parser.add_argument("id")
    end_parser.set_defaults(func=end)

    recover_parser = session.add_parser(
        "recover",
        help="End a stale session and block its claimed tasks",
    )
    recover_parser.add_argument("id")
    recover_parser.add_argument("--actor", required=True)
    recover_parser.add_argument("--reason", required=True)
    recover_parser.add_argument("--stale-after-seconds", type=int, default=3600)
    recover_parser.set_defaults(func=recover)
