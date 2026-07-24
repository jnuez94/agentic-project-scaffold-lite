"""Escalation entity commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
    connect,
    discover_db,
    emit,
    identifier,
    list_limit,
    list_offset,
    now,
    optional_text,
    require_active_actor,
    required_text,
    rows,
    transaction,
)
from coordination.errors import EXIT_NOT_FOUND, fail


ESCALATION_STATUSES = ("open", "in_review", "resolved", "closed_no_action")


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, args.raised_by)
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
    query += " ORDER BY created_at, id LIMIT ? OFFSET ?"
    parameters = (*parameters, args.limit, args.offset)
    emit(rows(connection.execute(query, parameters)))


def resolve(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        cursor = connection.execute(
            """UPDATE escalations
               SET status = ?, resolution = ?, follow_up_tasks = ?, updated_at = ?
               WHERE id = ?""",
            (args.status, args.resolution, args.follow_up_tasks, now(), args.id),
        )
        if cursor.rowcount != 1:
            fail(
                "not_found",
                f"Not found: escalation {args.id}",
                EXIT_NOT_FOUND,
                {"resource": f"escalation {args.id}"},
            )
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
    add_parser.add_argument("--id", required=True, type=identifier)
    add_parser.add_argument("--raised-by", required=True, type=identifier)
    add_parser.add_argument("--owner", required=True, type=required_text)
    add_parser.add_argument("--related-tasks", default="", type=optional_text)
    add_parser.add_argument("--needed-by", type=required_text)
    add_parser.add_argument("--issue", required=True, type=required_text)
    add_parser.add_argument(
        "--requested-decision",
        required=True,
        type=required_text,
    )
    add_parser.set_defaults(func=add)

    list_parser = escalation.add_parser("list")
    list_parser.add_argument("--status", choices=ESCALATION_STATUSES)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_escalations)

    resolve_parser = escalation.add_parser("resolve")
    resolve_parser.add_argument("id", type=identifier)
    resolve_parser.add_argument(
        "--status",
        choices=("resolved", "closed_no_action"),
        default="resolved",
    )
    resolve_parser.add_argument("--resolution", required=True, type=required_text)
    resolve_parser.add_argument("--follow-up-tasks", default="", type=optional_text)
    resolve_parser.add_argument("--actor", required=True, type=identifier)
    resolve_parser.set_defaults(func=resolve)
