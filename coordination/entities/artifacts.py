"""Artifact entity commands."""

from __future__ import annotations

import argparse
from typing import Any, Iterable

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
    read_transaction,
    require_active_actor,
    require_row,
    require_unique,
    required_text,
    transaction,
)
from coordination.errors import EXIT_NOT_FOUND, fail


ARTIFACT_STATUSES = ("draft", "review", "accepted", "superseded")


def shape_artifacts(
    connection: Any,
    artifact_rows: Iterable[Any],
) -> list[dict[str, Any]]:
    values = [dict(row) for row in artifact_rows]
    if not values:
        return []
    artifact_ids = [str(value["id"]) for value in values]
    placeholders = ",".join("?" for _ in artifact_ids)
    tasks: dict[str, list[str]] = {artifact_id: [] for artifact_id in artifact_ids}
    reviewers: dict[str, list[str]] = {
        artifact_id: [] for artifact_id in artifact_ids
    }
    for row in connection.execute(
        f"""SELECT artifact_id, task_id FROM artifact_tasks
            WHERE artifact_id IN ({placeholders})
            ORDER BY artifact_id, task_id""",
        artifact_ids,
    ):
        tasks[str(row["artifact_id"])].append(str(row["task_id"]))
    for row in connection.execute(
        f"""SELECT artifact_id, reviewer_id FROM artifact_reviewers
            WHERE artifact_id IN ({placeholders})
            ORDER BY artifact_id, reviewer_id""",
        artifact_ids,
    ):
        reviewers[str(row["artifact_id"])].append(str(row["reviewer_id"]))
    for value in values:
        artifact_id = str(value["id"])
        value["related_tasks"] = tasks[artifact_id]
        value["reviewers"] = reviewers[artifact_id]
    return values


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    require_unique(args.task, "--task")
    require_unique(args.reviewer, "--reviewer")
    with transaction(connection):
        require_active_actor(connection, args.owner)
        for task_id in args.task:
            require_row(
                connection,
                "SELECT id FROM tasks WHERE id = ?",
                (task_id,),
                f"task {task_id}",
            )
        for reviewer in args.reviewer:
            require_row(
                connection,
                "SELECT id FROM agents WHERE id = ?",
                (reviewer,),
                f"agent {reviewer}",
            )
        connection.execute(
            """INSERT INTO artifacts(
              id, uri, owner_id, type, status, usage_boundaries, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                args.id,
                args.uri,
                args.owner,
                args.type,
                args.status,
                args.usage_boundaries,
                stamp,
                stamp,
            ),
        )
        for task_id in args.task:
            connection.execute(
                "INSERT INTO artifact_tasks(artifact_id, task_id) VALUES (?, ?)",
                (args.id, task_id),
            )
        for reviewer in args.reviewer:
            connection.execute(
                "INSERT INTO artifact_reviewers(artifact_id, reviewer_id) VALUES (?, ?)",
                (args.id, reviewer),
            )
        audit(
            connection,
            args.owner,
            "create",
            "artifact",
            args.id,
            args.uri,
            session_id=args.session,
        )
    emit({"id": args.id, "status": args.status})


def list_artifacts(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = "SELECT a.* FROM artifacts a"
    parameters: list[Any] = []
    if args.status:
        query += " WHERE a.status = ?"
        parameters.append(args.status)
    query += " ORDER BY a.updated_at, a.id LIMIT ? OFFSET ?"
    parameters.extend((args.limit, args.offset))
    with read_transaction(connection):
        result = shape_artifacts(connection, connection.execute(query, parameters))
    emit(result)


def status(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        cursor = connection.execute(
            "UPDATE artifacts SET status = ?, updated_at = ? WHERE id = ?",
            (args.status, now(), args.id),
        )
        if cursor.rowcount != 1:
            fail(
                "not_found",
                f"Not found: artifact {args.id}",
                EXIT_NOT_FOUND,
                {"resource": f"artifact {args.id}"},
            )
        audit(
            connection,
            args.actor,
            "status",
            "artifact",
            args.id,
            args.status,
            session_id=args.session,
        )
    emit({"id": args.id, "status": args.status})


def register(commands: argparse._SubParsersAction) -> None:
    artifact = commands.add_parser("artifact", help="Manage artifacts").add_subparsers(
        dest="artifact_command",
        required=True,
    )
    add_parser = artifact.add_parser("add")
    add_parser.add_argument("--id", required=True, type=identifier)
    add_parser.add_argument("--uri", required=True, type=required_text)
    add_parser.add_argument("--owner", required=True, type=identifier)
    add_parser.add_argument("--type", required=True, type=required_text)
    add_parser.add_argument("--status", choices=ARTIFACT_STATUSES, default="draft")
    add_parser.add_argument("--usage-boundaries", default="", type=optional_text)
    add_parser.add_argument("--task", action="append", default=[], type=identifier)
    add_parser.add_argument(
        "--reviewer",
        action="append",
        default=[],
        type=identifier,
    )
    add_parser.set_defaults(func=add)

    list_parser = artifact.add_parser("list")
    list_parser.add_argument("--status", choices=ARTIFACT_STATUSES)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_artifacts)

    status_parser = artifact.add_parser("status")
    status_parser.add_argument("id", type=identifier)
    status_parser.add_argument("status", choices=ARTIFACT_STATUSES)
    status_parser.add_argument("--actor", required=True, type=identifier)
    status_parser.set_defaults(func=status)
