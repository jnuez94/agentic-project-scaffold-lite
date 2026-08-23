"""Dependency entity commands."""

from __future__ import annotations

import argparse
import sqlite3

from coordination.core import (
    Params,
    audit,
    identifier,
    now,
    optional_text,
    require_active_actor,
    require_row,
    transaction,
)
from coordination.errors import EXIT_NOT_FOUND, EXIT_USAGE, fail


DEPENDENCY_TYPES = ("blocks", "informs", "review_required", "evidence_required")


def add(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    if params.task == params.depends_on:
        fail(
            "invalid_arguments",
            "A task cannot depend on itself",
            EXIT_USAGE,
            {"task": params.task},
        )
    with transaction(connection):
        require_active_actor(connection, params.actor)
        for task_id in (params.task, params.depends_on):
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
            (params.task, params.depends_on, params.type, params.rationale, now()),
        )
        audit(
            connection,
            params.actor,
            "add",
            "dependency",
            f"{params.task}:{params.depends_on}:{params.type}",
            session_id=params.session,
        )
    return {
        "task_id": params.task,
        "depends_on": params.depends_on,
        "type": params.type,
        "status": "active",
    }


def resolve(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    with transaction(connection):
        cursor = connection.execute(
            """UPDATE task_dependencies
               SET status = 'resolved'
               WHERE task_id = ? AND depends_on_task_id = ? AND dependency_type = ?""",
            (params.task, params.depends_on, params.type),
        )
        if cursor.rowcount != 1:
            fail(
                "not_found",
                "Dependency not found",
                EXIT_NOT_FOUND,
                {
                    "task": params.task,
                    "depends_on": params.depends_on,
                    "type": params.type,
                },
            )
        audit(
            connection,
            params.actor,
            "resolve",
            "dependency",
            f"{params.task}:{params.depends_on}:{params.type}",
            session_id=params.session,
        )
    return {
        "task_id": params.task,
        "depends_on": params.depends_on,
        "type": params.type,
        "status": "resolved",
    }


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
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
