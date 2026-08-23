"""Artifact entity commands."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
    because_reference,
    connect,
    discover_db,
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
    resolve_reference,
    transaction,
)
from coordination.entities.audit import register_history
from coordination.errors import EXIT_CONFLICT, EXIT_USAGE, fail


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
    reviewers: dict[str, list[str]] = {artifact_id: [] for artifact_id in artifact_ids}
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


def add(args: argparse.Namespace) -> dict[str, str]:
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
                "INSERT INTO artifact_reviewers(artifact_id, reviewer_id)"
                " VALUES (?, ?)",
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
    return {"id": args.id, "status": args.status}


def list_artifacts(args: argparse.Namespace) -> list[dict[str, Any]]:
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
    return result


def require_expected_status(
    current: str,
    expected: str | None,
    *,
    entity: str,
    entity_id: str,
) -> None:
    """Compare-and-swap on the status being changed (optimistic concurrency).

    Only tasks carry a revision. For the other mutable entities, checking the
    status the caller saw is the no-migration way to refuse a lost update:
    two agents that both read `draft` cannot both succeed.
    """
    if expected is not None and current != expected:
        fail(
            "status_mismatch",
            f"{entity} {entity_id} is {current}, not {expected}",
            EXIT_CONFLICT,
            {
                entity.lower(): entity_id,
                "expected_status": expected,
                "actual_status": current,
            },
        )


def status(args: argparse.Namespace) -> dict[str, str]:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        current = require_row(
            connection,
            "SELECT status FROM artifacts WHERE id = ?",
            (args.id,),
            f"artifact {args.id}",
        )
        require_expected_status(
            str(current["status"]),
            getattr(args, "if_status", None),
            entity="Artifact",
            entity_id=args.id,
        )
        because = getattr(args, "because", None)
        if because:
            because = resolve_reference(connection, because)
        connection.execute(
            "UPDATE artifacts SET status = ?, updated_at = ? WHERE id = ?",
            (args.status, now(), args.id),
        )
        audit(
            connection,
            args.actor,
            "status",
            "artifact",
            args.id,
            f"{current['status']} -> {args.status}"
            + (f"; because={because}" if because else ""),
            session_id=args.session,
        )
    return {"id": args.id, "status": args.status}


def update(args: argparse.Namespace) -> dict[str, Any]:
    """Correct artifact metadata; URIs are paths, and paths move."""
    changes = {
        "uri": args.uri,
        "type": args.type,
        "usage_boundaries": args.usage_boundaries,
    }
    selected = {key: value for key, value in changes.items() if value is not None}
    if not selected:
        fail(
            "invalid_arguments",
            "Artifact update requires at least one changed field",
            EXIT_USAGE,
        )
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, args.actor)
        current = require_row(
            connection,
            "SELECT status FROM artifacts WHERE id = ?",
            (args.id,),
            f"artifact {args.id}",
        )
        require_expected_status(
            str(current["status"]),
            getattr(args, "if_status", None),
            entity="Artifact",
            entity_id=args.id,
        )
        assignments = ", ".join(f"{column} = ?" for column in selected)
        connection.execute(
            f"UPDATE artifacts SET {assignments}, updated_at = ? WHERE id = ?",
            (*selected.values(), stamp, args.id),
        )
        audit(
            connection,
            args.actor,
            "update",
            "artifact",
            args.id,
            f"fields={','.join(sorted(selected))}",
            session_id=args.session,
        )
        result = dict(
            connection.execute(
                "SELECT * FROM artifacts WHERE id = ?", (args.id,)
            ).fetchone()
        )
    return result


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
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
    status_parser.add_argument(
        "--if-status",
        choices=ARTIFACT_STATUSES,
        help="Only change the status if it is currently this value",
    )
    status_parser.add_argument(
        "--because",
        type=because_reference,
        help="Record the review, decision, or message (TYPE:ID) that caused this",
    )
    status_parser.set_defaults(func=status)

    update_parser = artifact.add_parser("update")
    update_parser.add_argument("id", type=identifier)
    update_parser.add_argument("--uri", type=required_text)
    update_parser.add_argument("--type", type=required_text)
    update_parser.add_argument("--usage-boundaries", type=optional_text)
    update_parser.add_argument("--actor", required=True, type=identifier)
    update_parser.add_argument(
        "--if-status",
        choices=ARTIFACT_STATUSES,
        help="Only update if the status is currently this value",
    )
    update_parser.set_defaults(func=update)
    register_history(artifact, "artifact")
