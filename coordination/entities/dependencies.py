"""Dependency entity commands."""

from __future__ import annotations

import argparse

from coordination.core import (
    audit,
    connect,
    discover_db,
    emit,
    identifier,
    now,
    optional_text,
    require_active_actor,
    require_row,
    transaction,
)
from coordination.errors import EXIT_NOT_FOUND, EXIT_USAGE, fail


DEPENDENCY_TYPES = ("blocks", "informs", "review_required", "evidence_required")


def add(args: argparse.Namespace) -> None:
    if args.task == args.depends_on:
        fail(
            "invalid_arguments",
            "A task cannot depend on itself",
            EXIT_USAGE,
            {"task": args.task},
        )
    connection = connect(discover_db(args.db))
    with transaction(connection):
        require_active_actor(connection, args.actor)
        for task_id in (args.task, args.depends_on):
            require_row(
                connection,
                "SELECT id FROM tasks WHERE id = ?",
                (task_id,),
                f"task {task_id}",
            )
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
    add_parser.add_argument("--task", required=True, type=identifier)
    add_parser.add_argument("--depends-on", required=True, type=identifier)
    add_parser.add_argument("--type", choices=DEPENDENCY_TYPES, default="blocks")
    add_parser.add_argument("--rationale", default="", type=optional_text)
    add_parser.add_argument("--actor", required=True, type=identifier)
    add_parser.set_defaults(func=add)

    resolve_parser = dependency.add_parser("resolve")
    resolve_parser.add_argument("--task", required=True, type=identifier)
    resolve_parser.add_argument("--depends-on", required=True, type=identifier)
    resolve_parser.add_argument("--type", choices=DEPENDENCY_TYPES, default="blocks")
    resolve_parser.add_argument("--actor", required=True, type=identifier)
    resolve_parser.set_defaults(func=resolve)
