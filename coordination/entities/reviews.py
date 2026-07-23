"""Review entity commands."""

from __future__ import annotations

import argparse

from coordination.core import audit, connect, discover_db, emit, now, rows


REVIEW_DECISIONS = (
    "accepted",
    "conditionally_accepted",
    "changes_requested",
    "rejected",
)


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
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
        audit(connection, args.reviewer, "create", "review", args.id, args.decision)
    emit({"id": args.id, "decision": args.decision, "status": "created"})


def list_reviews(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    if args.task:
        result = connection.execute(
            "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at",
            (args.task,),
        )
    else:
        result = connection.execute("SELECT * FROM reviews ORDER BY created_at")
    emit(rows(result))


def register(commands: argparse._SubParsersAction) -> None:
    review = commands.add_parser("review", help="Manage reviews").add_subparsers(
        dest="review_command",
        required=True,
    )
    add_parser = review.add_parser("add")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--task")
    add_parser.add_argument("--reviewer", required=True)
    add_parser.add_argument("--artifact", required=True)
    add_parser.add_argument("--scope", required=True)
    add_parser.add_argument("--decision", choices=REVIEW_DECISIONS, required=True)
    add_parser.add_argument("--accepted-items", default="")
    add_parser.add_argument("--required-changes", default="")
    add_parser.add_argument("--risks", default="")
    add_parser.add_argument("--blocked-claims", default="")
    add_parser.add_argument("--follow-up-tasks", default="")
    add_parser.set_defaults(func=add)

    list_parser = review.add_parser("list")
    list_parser.add_argument("--task")
    list_parser.set_defaults(func=list_reviews)
