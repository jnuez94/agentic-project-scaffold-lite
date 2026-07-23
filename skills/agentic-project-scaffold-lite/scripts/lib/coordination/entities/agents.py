"""Agent entity commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import audit, connect, discover_db, emit, now, rows


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        connection.execute(
            """INSERT INTO agents(
              id, name, role, status, responsibilities, goal, operating_style,
              decision_authority, review_authority, escalation_rules, unavailable_for,
              created_at, updated_at
            ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                args.id,
                args.name,
                args.role,
                args.responsibilities,
                args.goal,
                args.operating_style,
                args.decision_authority,
                args.review_authority,
                args.escalation_rules,
                args.unavailable_for,
                stamp,
                stamp,
            ),
        )
        audit(connection, args.id, "create", "agent", args.id)
    emit({"id": args.id, "status": "created"})


def list_agents(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM agents"
    parameters: tuple[Any, ...] = ()
    if not args.all:
        query += " WHERE status = ?"
        parameters = ("active",)
    query += " ORDER BY role, id"
    emit(rows(connection.execute(query, parameters)))


def register(commands: argparse._SubParsersAction) -> None:
    agent = commands.add_parser("agent", help="Manage agents").add_subparsers(
        dest="agent_command",
        required=True,
    )
    add_parser = agent.add_parser("add")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--role", required=True)
    add_parser.add_argument("--responsibilities", default="")
    add_parser.add_argument("--goal", default="")
    add_parser.add_argument("--operating-style", default="")
    add_parser.add_argument("--decision-authority", default="")
    add_parser.add_argument("--review-authority", default="")
    add_parser.add_argument("--escalation-rules", default="")
    add_parser.add_argument("--unavailable-for", default="")
    add_parser.set_defaults(func=add)

    list_parser = agent.add_parser("list")
    list_parser.add_argument("--all", action="store_true")
    list_parser.set_defaults(func=list_agents)
