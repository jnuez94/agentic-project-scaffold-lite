"""Evidence entity commands."""

from __future__ import annotations

import argparse
import sqlite3
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    Params,
    audit,
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


def add(connection: sqlite3.Connection, params: Params) -> dict[str, object]:
    with transaction(connection):
        require_active_actor(connection, params.actor)
        require_row(
            connection,
            "SELECT id FROM tasks WHERE id = ?",
            (params.task,),
            f"task {params.task}",
        )
        cursor = connection.execute(
            """INSERT INTO task_evidence(
                 task_id, uri, evidence_type, added_by, created_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (params.task, params.uri, params.type, params.actor, now()),
        )
        audit(
            connection,
            params.actor,
            "add",
            "evidence",
            str(cursor.lastrowid),
            params.task,
            session_id=params.session,
        )
    return {"id": cursor.lastrowid, "task_id": params.task, "status": "created"}


def list_evidence(
    connection: sqlite3.Connection, params: Params
) -> list[dict[str, object]]:
    require_row(
        connection,
        "SELECT id FROM tasks WHERE id = ?",
        (params.task,),
        f"task {params.task}",
    )
    conditions = ["task_id = ?"]
    parameters: list[Any] = [params.task]
    extra_conditions, extra_parameters, order_sql = query_options(EVIDENCE, params)
    conditions.extend(extra_conditions)
    parameters.extend(extra_parameters)
    query = (
        "SELECT * FROM task_evidence WHERE "
        + " AND ".join(conditions)
        + " "
        + (order_sql or "ORDER BY created_at, id")
        + " LIMIT ? OFFSET ?"
    )
    parameters.extend((params.limit, params.offset))
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
