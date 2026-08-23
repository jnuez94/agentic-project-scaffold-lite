"""Evidence entity commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
    connect,
    discover_db,
    identifier,
    list_limit,
    list_offset,
    now,
    require_active_actor,
    require_row,
    required_text,
    rows,
    transaction,
)
from coordination.entities.descriptors import (
    EVIDENCE,
    add_query_arguments,
    query_options,
)


def add(args: argparse.Namespace) -> dict[str, object]:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        require_active_actor(connection, args.actor)
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
    return {"id": cursor.lastrowid, "task_id": args.task, "status": "created"}


def list_evidence(args: argparse.Namespace) -> list[dict[str, object]]:
    connection = connect(discover_db(args.db))
    require_row(
        connection,
        "SELECT id FROM tasks WHERE id = ?",
        (args.task,),
        f"task {args.task}",
    )
    conditions = ["task_id = ?"]
    parameters: list[Any] = [args.task]
    extra_conditions, extra_parameters, order_sql = query_options(EVIDENCE, args)
    conditions.extend(extra_conditions)
    parameters.extend(extra_parameters)
    query = (
        "SELECT * FROM task_evidence WHERE "
        + " AND ".join(conditions)
        + " "
        + (order_sql or "ORDER BY created_at, id")
        + " LIMIT ? OFFSET ?"
    )
    parameters.extend((args.limit, args.offset))
    return rows(connection.execute(query, parameters))


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    evidence = commands.add_parser(
        "evidence",
        help="Manage task evidence",
    ).add_subparsers(
        dest="evidence_command",
        required=True,
    )
    add_parser = evidence.add_parser("add")
    add_parser.add_argument("--task", required=True, type=identifier)
    add_parser.add_argument("--uri", required=True, type=required_text)
    add_parser.add_argument("--type", default="artifact", type=required_text)
    add_parser.add_argument("--actor", required=True, type=identifier)
    add_parser.set_defaults(func=add)

    list_parser = evidence.add_parser("list")
    list_parser.add_argument("--task", required=True, type=identifier)
    add_query_arguments(list_parser, EVIDENCE)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_evidence)
