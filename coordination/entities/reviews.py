"""Review entity commands."""

from __future__ import annotations

import argparse

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
    require_row,
    required_text,
    rows,
    transaction,
)


REVIEW_DECISIONS = (
    "accepted",
    "conditionally_accepted",
    "changes_requested",
    "rejected",
)


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        require_active_actor(connection, args.reviewer)
        if args.task:
            require_row(
                connection,
                "SELECT id FROM tasks WHERE id = ?",
                (args.task,),
                f"task {args.task}",
            )
        connection.execute(
            """INSERT INTO reviews(
              id, task_id, reviewer_id, artifact_uri, scope, decision, accepted_items,
              required_changes, remaining_risks, blocked_claims, follow_up_tasks, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                args.id,
                args.task,
                args.reviewer,
                args.artifact,
                args.scope,
                args.decision,
                args.accepted_items,
                args.required_changes,
                args.risks,
                args.blocked_claims,
                args.follow_up_tasks,
                now(),
            ),
        )
        audit(
            connection,
            args.reviewer,
            "create",
            "review",
            args.id,
            args.decision,
            session_id=args.session,
        )
    emit({"id": args.id, "decision": args.decision, "status": "created"})


def list_reviews(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    if args.task:
        require_row(
            connection,
            "SELECT id FROM tasks WHERE id = ?",
            (args.task,),
            f"task {args.task}",
        )
        result = connection.execute(
            """SELECT * FROM reviews WHERE task_id = ?
               ORDER BY created_at, id LIMIT ? OFFSET ?""",
            (args.task, args.limit, args.offset),
        )
    else:
        result = connection.execute(
            "SELECT * FROM reviews ORDER BY created_at, id LIMIT ? OFFSET ?",
            (args.limit, args.offset),
        )
    emit(rows(result))


def register(commands: argparse._SubParsersAction) -> None:
    review = commands.add_parser("review", help="Manage reviews").add_subparsers(
        dest="review_command",
        required=True,
    )
    add_parser = review.add_parser("add")
    add_parser.add_argument("--id", required=True, type=identifier)
    add_parser.add_argument("--task", type=identifier)
    add_parser.add_argument("--reviewer", required=True, type=identifier)
    add_parser.add_argument("--artifact", required=True, type=required_text)
    add_parser.add_argument("--scope", required=True, type=required_text)
    add_parser.add_argument("--decision", choices=REVIEW_DECISIONS, required=True)
    add_parser.add_argument("--accepted-items", default="", type=optional_text)
    add_parser.add_argument("--required-changes", default="", type=optional_text)
    add_parser.add_argument("--risks", default="", type=optional_text)
    add_parser.add_argument("--blocked-claims", default="", type=optional_text)
    add_parser.add_argument("--follow-up-tasks", default="", type=optional_text)
    add_parser.set_defaults(func=add)

    list_parser = review.add_parser("list")
    list_parser.add_argument("--task", type=identifier)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_reviews)
