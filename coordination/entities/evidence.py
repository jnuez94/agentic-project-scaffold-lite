"""Evidence entity commands."""

from __future__ import annotations

import argparse

from coordination.core import (
    audit,
    connect,
    discover_db,
    emit,
    now,
    require_row,
    rows,
    transaction,
)


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        require_row(
            connection,
            "SELECT id FROM tasks WHERE id = ?",
            (args.task,),
            f"task {args.task}",
        )
        cursor = connection.execute(
            """INSERT INTO task_evidence(
                 task_id, uri, evidence_type, added_by, created_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (args.task, args.uri, args.type, args.actor, now()),
        )
        audit(
            connection,
            args.actor,
            "add",
            "evidence",
            str(cursor.lastrowid),
            args.task,
            session_id=args.session,
        )
    emit({"id": cursor.lastrowid, "task_id": args.task, "status": "created"})


def list_evidence(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    emit(
        rows(
            connection.execute(
                "SELECT * FROM task_evidence WHERE task_id = ? ORDER BY created_at",
                (args.task,),
            )
        )
    )


def register(commands: argparse._SubParsersAction) -> None:
    evidence = commands.add_parser("evidence", help="Manage task evidence").add_subparsers(
        dest="evidence_command",
        required=True,
    )
    add_parser = evidence.add_parser("add")
    add_parser.add_argument("--task", required=True)
    add_parser.add_argument("--uri", required=True)
    add_parser.add_argument("--type", default="artifact")
    add_parser.add_argument("--actor")
    add_parser.set_defaults(func=add)

    list_parser = evidence.add_parser("list")
    list_parser.add_argument("--task", required=True)
    list_parser.set_defaults(func=list_evidence)
