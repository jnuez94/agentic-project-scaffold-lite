"""Decision entity commands."""

from __future__ import annotations

import argparse

from coordination.core import audit, connect, discover_db, emit, now, rows


DECISION_STATUSES = ("proposed", "accepted", "superseded", "rejected")


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        connection.execute(
            """INSERT INTO decisions(
              id, title, owner_id, status, context, decision, options_considered,
              implications, evidence, blocked_claims, review_required, created_at, updated_at
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
    emit({"id": args.id, "status": args.status})


def list_decisions(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    emit(rows(connection.execute("SELECT * FROM decisions ORDER BY created_at, id")))


def register(commands: argparse._SubParsersAction) -> None:
    decision = commands.add_parser("decision", help="Manage decisions").add_subparsers(
        dest="decision_command",
        required=True,
    )
    add_parser = decision.add_parser("add")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--owner", required=True)
    add_parser.add_argument("--status", choices=DECISION_STATUSES, default="proposed")
    add_parser.add_argument("--context", required=True)
    add_parser.add_argument("--decision", required=True)
    add_parser.add_argument("--options", default="")
    add_parser.add_argument("--implications", default="")
    add_parser.add_argument("--evidence", default="")
    add_parser.add_argument("--blocked-claims", default="")
    add_parser.add_argument("--review-required", default="")
    add_parser.set_defaults(func=add)

    list_parser = decision.add_parser("list")
    list_parser.set_defaults(func=list_decisions)
