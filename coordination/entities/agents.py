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
              id, name, role, actor_type, status, responsibilities, goal, operating_style,
              decision_authority, review_authority, escalation_rules, unavailable_for,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                args.id,
                args.name,
                args.role,
                args.actor_type,
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
    emit({"id": args.id, "actor_type": args.actor_type, "status": "created"})


def list_agents(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM agents"
    parameters: tuple[Any, ...] = ()
    conditions: list[str] = []
    values: list[Any] = []
    if not args.all:
        conditions.append("status = ?")
        values.append("active")
    if args.actor_type:
        conditions.append("actor_type = ?")
        values.append(args.actor_type)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    parameters = tuple(values)
    query += " ORDER BY role, id"
    emit(rows(connection.execute(query, parameters)))


def update(args: argparse.Namespace) -> None:
    changes = {
        "name": args.name,
        "role": args.role,
        "actor_type": args.actor_type,
        "status": args.status,
    }
    selected = {key: value for key, value in changes.items() if value is not None}
    if not selected:
        raise SystemExit("Agent update requires at least one changed field")
    connection = connect(discover_db(args.db))
    stamp = now()
    assignments = ", ".join(f"{column} = ?" for column in selected)
    parameters = [*selected.values(), stamp, args.id]
    actor = args.actor or args.id
    with connection:
        cursor = connection.execute(
            f"UPDATE agents SET {assignments}, updated_at = ? WHERE id = ?",
            parameters,
        )
        if cursor.rowcount != 1:
            raise SystemExit(f"Not found: agent {args.id}")
        audit(
            connection,
            actor,
            "update",
            "agent",
            args.id,
            ",".join(selected),
            session_id=args.session,
        )
        result = dict(
            connection.execute(
                "SELECT * FROM agents WHERE id = ?",
                (args.id,),
            ).fetchone()
        )
    emit(result)


def register(commands: argparse._SubParsersAction) -> None:
    agent = commands.add_parser("agent", help="Manage agents").add_subparsers(
        dest="agent_command",
        required=True,
    )
    add_parser = agent.add_parser("add")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--role", required=True)
    add_parser.add_argument(
        "--actor-type",
        choices=("ai", "human", "service"),
        default="ai",
    )
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
    list_parser.add_argument("--actor-type", choices=("ai", "human", "service"))
    list_parser.set_defaults(func=list_agents)

    update_parser = agent.add_parser("update")
    update_parser.add_argument("id")
    update_parser.add_argument("--name")
    update_parser.add_argument("--role")
    update_parser.add_argument("--actor-type", choices=("ai", "human", "service"))
    update_parser.add_argument("--status", choices=("active", "inactive"))
    update_parser.add_argument("--actor")
    update_parser.set_defaults(func=update)
