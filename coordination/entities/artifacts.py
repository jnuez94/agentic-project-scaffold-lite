"""Artifact entity commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import audit, connect, discover_db, emit, now, rows


ARTIFACT_STATUSES = ("draft", "review", "accepted", "superseded")


def add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
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
        audit(connection, args.owner, "create", "artifact", args.id, args.uri)
    emit({"id": args.id, "status": args.status})


def list_artifacts(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = """SELECT a.*,
      COALESCE(GROUP_CONCAT(DISTINCT at.task_id), '') AS related_tasks,
      COALESCE(GROUP_CONCAT(DISTINCT ar.reviewer_id), '') AS reviewers
      FROM artifacts a
      LEFT JOIN artifact_tasks at ON at.artifact_id = a.id
      LEFT JOIN artifact_reviewers ar ON ar.artifact_id = a.id"""
    parameters: tuple[Any, ...] = ()
    if args.status:
        query += " WHERE a.status = ?"
        parameters = (args.status,)
    query += " GROUP BY a.id ORDER BY a.updated_at, a.id"
    emit(rows(connection.execute(query, parameters)))


def status(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
        cursor = connection.execute(
            "UPDATE artifacts SET status = ?, updated_at = ? WHERE id = ?",
            (args.status, now(), args.id),
        )
        if cursor.rowcount != 1:
            raise SystemExit(f"Not found: artifact {args.id}")
        audit(connection, args.actor, "status", "artifact", args.id, args.status)
    emit({"id": args.id, "status": args.status})


def register(commands: argparse._SubParsersAction) -> None:
    artifact = commands.add_parser("artifact", help="Manage artifacts").add_subparsers(
        dest="artifact_command",
        required=True,
    )
    add_parser = artifact.add_parser("add")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--uri", required=True)
    add_parser.add_argument("--owner", required=True)
    add_parser.add_argument("--type", required=True)
    add_parser.add_argument("--status", choices=ARTIFACT_STATUSES, default="draft")
    add_parser.add_argument("--usage-boundaries", default="")
    add_parser.add_argument("--task", action="append", default=[])
    add_parser.add_argument("--reviewer", action="append", default=[])
    add_parser.set_defaults(func=add)

    list_parser = artifact.add_parser("list")
    list_parser.add_argument("--status", choices=ARTIFACT_STATUSES)
    list_parser.set_defaults(func=list_artifacts)

    status_parser = artifact.add_parser("status")
    status_parser.add_argument("id")
    status_parser.add_argument("status", choices=ARTIFACT_STATUSES)
    status_parser.add_argument("--actor")
    status_parser.set_defaults(func=status)
