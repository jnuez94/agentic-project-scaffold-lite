"""Escalation entity commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
    because_reference,
    connect,
    discover_db,
    identifier,
    list_limit,
    list_offset,
    now,
    optional_text,
    require_active_actor,
    require_row,
    required_text,
    resolve_reference,
    rows,
    transaction,
)
from coordination.entities.audit import register_history
from coordination.entities.descriptors import (
    ESCALATIONS,
    add_query_arguments,
    query_options,
)
from coordination.errors import EXIT_CONFLICT, fail


ESCALATION_STATUSES = ("open", "in_review", "resolved", "closed_no_action")


def add(args: argparse.Namespace) -> dict[str, str]:
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
    return {"id": args.id, "status": "open"}


def list_escalations(args: argparse.Namespace) -> list[dict[str, Any]]:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM escalations"
    conditions: list[str] = []
    parameters: list[Any] = []
    if args.status:
        conditions.append("status = ?")
        parameters.append(args.status)
    extra_conditions, extra_parameters, order_sql = query_options(ESCALATIONS, args)
    conditions.extend(extra_conditions)
    parameters.extend(extra_parameters)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " " + (order_sql or "ORDER BY created_at, id") + " LIMIT ? OFFSET ?"
    parameters.extend((args.limit, args.offset))
    return rows(connection.execute(query, parameters))


def resolve(args: argparse.Namespace) -> dict[str, str]:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        current = require_row(
            connection,
            "SELECT status FROM escalations WHERE id = ?",
            (args.id,),
            f"escalation {args.id}",
        )
        if_status = getattr(args, "if_status", None)
        if if_status is not None and str(current["status"]) != if_status:
            fail(
                "status_mismatch",
                f"Escalation {args.id} is {current['status']}, not {if_status}",
                EXIT_CONFLICT,
                {
                    "escalation": args.id,
                    "expected_status": if_status,
                    "actual_status": str(current["status"]),
                },
            )
        because = getattr(args, "because", None)
        if because:
            because = resolve_reference(connection, because)
        connection.execute(
            """UPDATE escalations
               SET status = ?, resolution = ?, follow_up_tasks = ?, updated_at = ?
               WHERE id = ?""",
            (args.status, args.resolution, args.follow_up_tasks, now(), args.id),
        )
        audit(
            connection,
            args.actor,
            "resolve",
            "escalation",
            args.id,
            f"{current['status']} -> {args.status}"
            + (f"; because={because}" if because else ""),
            session_id=args.session,
        )
    return {"id": args.id, "status": args.status}


def show(args: argparse.Namespace) -> dict[str, Any]:
    connection = connect(discover_db(args.db))

    row = require_row(
        connection,
        "SELECT * FROM escalations WHERE id = ?",
        (args.id,),
        f"escalation {args.id}",
    )
    result = dict(row)
    return result


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
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
    add_query_arguments(list_parser, ESCALATIONS)
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
    resolve_parser.add_argument(
        "--if-status",
        choices=ESCALATION_STATUSES,
        help="Only resolve if the status is currently this value",
    )
    resolve_parser.add_argument(
        "--because",
        type=because_reference,
        help="Record the review, decision, or message (TYPE:ID) that caused this",
    )
    resolve_parser.set_defaults(func=resolve)
    show_parser = escalation.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)
    register_history(escalation, "escalation")
