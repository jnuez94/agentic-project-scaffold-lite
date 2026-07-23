"""Agent execution-session commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import audit, connect, discover_db, emit, now, require_row, rows


SESSION_STATUSES = ("active", "ended")


def start(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
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
    with connection:
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
    with connection:
        session = require_row(
            connection,
            "SELECT agent_id FROM agent_sessions WHERE id = ? AND status = 'active'",
            (args.id,),
            f"active agent session {args.id}",
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
