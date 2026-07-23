"""Escalation entity commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import audit, connect, discover_db, emit, now, rows


ESCALATION_STATUSES = ("open", "in_review", "resolved", "closed_no_action")


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        connection.execute(
            """INSERT INTO escalations(
              id, raised_by, owner, status, related_tasks, needed_by, issue,
              requested_decision, created_at, updated_at
            ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)""",
            (
                args.id,
                args.raised_by,
                args.owner,
                args.related_tasks,
                args.needed_by,
                args.issue,
                args.requested_decision,
                stamp,
                stamp,
            ),
        )
        audit(
            connection,
            args.raised_by,
            "create",
            "escalation",
            args.id,
            session_id=args.session,
        )
    emit({"id": args.id, "status": "open"})


def list_escalations(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM escalations"
    parameters: tuple[Any, ...] = ()
    if args.status:
        query += " WHERE status = ?"
        parameters = (args.status,)
    query += " ORDER BY created_at, id"
    emit(rows(connection.execute(query, parameters)))


def resolve(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
        cursor = connection.execute(
            """UPDATE escalations
               SET status = ?, resolution = ?, follow_up_tasks = ?, updated_at = ?
               WHERE id = ?""",
            (args.status, args.resolution, args.follow_up_tasks, now(), args.id),
        )
        if cursor.rowcount != 1:
            raise SystemExit(f"Not found: escalation {args.id}")
        audit(
            connection,
            args.actor,
            "resolve",
            "escalation",
            args.id,
            args.status,
            session_id=args.session,
        )
    emit({"id": args.id, "status": args.status})


def register(commands: argparse._SubParsersAction) -> None:
    escalation = commands.add_parser(
        "escalation",
        help="Manage escalations",
    ).add_subparsers(dest="escalation_command", required=True)

    add_parser = escalation.add_parser("add")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--raised-by", required=True)
    add_parser.add_argument("--owner", required=True)
    add_parser.add_argument("--related-tasks", default="")
    add_parser.add_argument("--needed-by")
    add_parser.add_argument("--issue", required=True)
    add_parser.add_argument("--requested-decision", required=True)
    add_parser.set_defaults(func=add)

    list_parser = escalation.add_parser("list")
    list_parser.add_argument("--status", choices=ESCALATION_STATUSES)
    list_parser.set_defaults(func=list_escalations)

    resolve_parser = escalation.add_parser("resolve")
    resolve_parser.add_argument("id")
    resolve_parser.add_argument(
        "--status",
        choices=("resolved", "closed_no_action"),
        default="resolved",
    )
    resolve_parser.add_argument("--resolution", required=True)
    resolve_parser.add_argument("--follow-up-tasks", default="")
    resolve_parser.add_argument("--actor")
    resolve_parser.set_defaults(func=resolve)
