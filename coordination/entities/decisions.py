"""Decision entity commands."""

from __future__ import annotations

import argparse

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
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
    rows,
    transaction,
)
from coordination.entities.audit import register_history
from coordination.errors import EXIT_CONFLICT, fail


DECISION_STATUSES = ("proposed", "accepted", "superseded", "rejected")


def add(args: argparse.Namespace) -> dict[str, str]:
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, args.owner)
        connection.execute(
            """INSERT INTO decisions(
              id, title, owner_id, status, context, decision, options_considered,
              implications, evidence, blocked_claims, review_required,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                args.id,
                args.title,
                args.owner,
                args.status,
                args.context,
                args.decision,
                args.options,
                args.implications,
                args.evidence,
                args.blocked_claims,
                args.review_required,
                stamp,
                stamp,
            ),
        )
        audit(
            connection,
            args.owner,
            "create",
            "decision",
            args.id,
            args.status,
            session_id=args.session,
        )
    return {"id": args.id, "status": args.status}


def list_decisions(args: argparse.Namespace) -> list[dict[str, object]]:
    connection = connect(discover_db(args.db))
    return rows(
        connection.execute(
            """SELECT * FROM decisions
               ORDER BY created_at, id LIMIT ? OFFSET ?""",
            (args.limit, args.offset),
        )
    )


def status(args: argparse.Namespace) -> dict[str, str]:
    """Record a ruling on a decision after it was proposed.

    The schema anticipated every transition -- `superseded` was reachable only
    at creation, the one moment it can never be true -- and `updated_at` was
    written once. There is no notes column on decisions, so `--note` is kept in
    the audit detail. `--if-status` is compare-and-swap on the status the
    caller saw.
    """
    connection = connect(discover_db(args.db))
    with transaction(connection):
        require_active_actor(connection, args.actor)
        current = require_row(
            connection,
            "SELECT status FROM decisions WHERE id = ?",
            (args.id,),
            f"decision {args.id}",
        )
        if_status = getattr(args, "if_status", None)
        if if_status is not None and str(current["status"]) != if_status:
            fail(
                "status_mismatch",
                f"Decision {args.id} is {current['status']}, not {if_status}",
                EXIT_CONFLICT,
                {
                    "decision": args.id,
                    "expected_status": if_status,
                    "actual_status": str(current["status"]),
                },
            )
        connection.execute(
            "UPDATE decisions SET status = ?, updated_at = ? WHERE id = ?",
            (args.status, now(), args.id),
        )
        detail = f"{current['status']} -> {args.status}"
        if args.note:
            detail += f"; {args.note}"
        audit(
            connection,
            args.actor,
            "status",
            "decision",
            args.id,
            detail,
            session_id=args.session,
        )
    return {
        "id": args.id,
        "previous_status": str(current["status"]),
        "status": args.status,
    }


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    decision = commands.add_parser("decision", help="Manage decisions").add_subparsers(
        dest="decision_command",
        required=True,
    )
    add_parser = decision.add_parser("add")
    add_parser.add_argument("--id", required=True, type=identifier)
    add_parser.add_argument("--title", required=True, type=required_text)
    add_parser.add_argument("--owner", required=True, type=identifier)
    add_parser.add_argument("--status", choices=DECISION_STATUSES, default="proposed")
    add_parser.add_argument("--context", required=True, type=required_text)
    add_parser.add_argument("--decision", required=True, type=required_text)
    add_parser.add_argument("--options", default="", type=optional_text)
    add_parser.add_argument("--implications", default="", type=optional_text)
    add_parser.add_argument("--evidence", default="", type=optional_text)
    add_parser.add_argument("--blocked-claims", default="", type=optional_text)
    add_parser.add_argument("--review-required", default="", type=optional_text)
    add_parser.set_defaults(func=add)

    list_parser = decision.add_parser("list")
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_decisions)

    status_parser = decision.add_parser("status")
    status_parser.add_argument("id", type=identifier)
    status_parser.add_argument("status", choices=DECISION_STATUSES)
    status_parser.add_argument("--actor", required=True, type=identifier)
    status_parser.add_argument(
        "--if-status",
        choices=DECISION_STATUSES,
        help="Only change the status if it is currently this value",
    )
    status_parser.add_argument("--note", default="", type=optional_text)
    status_parser.set_defaults(func=status)
    register_history(decision, "decision")
