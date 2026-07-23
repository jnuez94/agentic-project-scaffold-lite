"""Dependency entity commands."""

from __future__ import annotations

import argparse

from coordination.core import audit, connect, discover_db, emit, now, transaction
from coordination.errors import EXIT_NOT_FOUND, fail


DEPENDENCY_TYPES = ("blocks", "informs", "review_required", "evidence_required")


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        connection.execute(
            """INSERT INTO task_dependencies(
                 task_id, depends_on_task_id, dependency_type, rationale, created_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (args.task, args.depends_on, args.type, args.rationale, now()),
        )
        audit(
            connection,
            args.actor,
            "add",
            "dependency",
            f"{args.task}:{args.depends_on}:{args.type}",
            session_id=args.session,
        )
    emit(
        {
            "task_id": args.task,
            "depends_on": args.depends_on,
            "type": args.type,
            "status": "active",
        }
    )


def resolve(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        cursor = connection.execute(
            """UPDATE task_dependencies
               SET status = 'resolved'
               WHERE task_id = ? AND depends_on_task_id = ? AND dependency_type = ?""",
            (args.task, args.depends_on, args.type),
        )
        if cursor.rowcount != 1:
            fail(
                "not_found",
                "Dependency not found",
                EXIT_NOT_FOUND,
                {
                    "task": args.task,
                    "depends_on": args.depends_on,
                    "type": args.type,
                },
            )
        audit(
            connection,
            args.actor,
            "resolve",
            "dependency",
            f"{args.task}:{args.depends_on}:{args.type}",
            session_id=args.session,
        )
    emit(
        {
            "task_id": args.task,
            "depends_on": args.depends_on,
            "type": args.type,
            "status": "resolved",
        }
    )


def register(commands: argparse._SubParsersAction) -> None:
    dependency = commands.add_parser(
        "dependency",
        help="Manage dependencies",
    ).add_subparsers(dest="dependency_command", required=True)

    add_parser = dependency.add_parser("add")
    add_parser.add_argument("--task", required=True)
    add_parser.add_argument("--depends-on", required=True)
    add_parser.add_argument("--type", choices=DEPENDENCY_TYPES, default="blocks")
    add_parser.add_argument("--rationale", default="")
    add_parser.add_argument("--actor")
    add_parser.set_defaults(func=add)

    resolve_parser = dependency.add_parser("resolve")
    resolve_parser.add_argument("--task", required=True)
    resolve_parser.add_argument("--depends-on", required=True)
    resolve_parser.add_argument("--type", choices=DEPENDENCY_TYPES, default="blocks")
    resolve_parser.add_argument("--actor")
    resolve_parser.set_defaults(func=resolve)
