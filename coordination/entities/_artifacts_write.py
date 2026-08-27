"""Artifact write operations with status gating."""

from __future__ import annotations

import sqlite3
from typing import Any

from coordination.core import (
    Params,
    audit,
    now,
    require_active_actor,
    require_row,
    require_unique,
    resolve_reference,
    transaction,
)
from coordination.errors import EXIT_CONFLICT, EXIT_USAGE, fail


def add(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    stamp = now()
    require_unique(params.task, "--task")
    require_unique(params.reviewer, "--reviewer")
    with transaction(connection):
        require_active_actor(connection, params.owner)
        for task_id in params.task:
            require_row(
                connection,
                "SELECT id FROM tasks WHERE id = ?",
                (task_id,),
                f"task {task_id}",
            )
        for reviewer in params.reviewer:
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
                params.id,
                params.uri,
                params.owner,
                params.type,
                params.status,
                params.usage_boundaries,
                stamp,
                stamp,
            ),
        )
        for task_id in params.task:
            connection.execute(
                "INSERT INTO artifact_tasks(artifact_id, task_id) VALUES (?, ?)",
                (params.id, task_id),
            )
        for reviewer in params.reviewer:
            connection.execute(
                "INSERT INTO artifact_reviewers(artifact_id, reviewer_id)"
                " VALUES (?, ?)",
                (params.id, reviewer),
            )
        audit(
            connection,
            params.owner,
            "create",
            "artifact",
            params.id,
            params.uri,
            session_id=params.session,
        )
    return {"id": params.id, "status": params.status}


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


def status(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    with transaction(connection):
        current = require_row(
            connection,
            "SELECT status FROM artifacts WHERE id = ?",
            (params.id,),
            f"artifact {params.id}",
        )
        require_expected_status(
            str(current["status"]),
            getattr(params, "if_status", None),
            entity="Artifact",
            entity_id=params.id,
        )
        because = getattr(params, "because", None)
        if because:
            because = resolve_reference(connection, because)
        connection.execute(
            "UPDATE artifacts SET status = ?, updated_at = ? WHERE id = ?",
            (params.status, now(), params.id),
        )
        audit(
            connection,
            params.actor,
            "status",
            "artifact",
            params.id,
            f"{current['status']} -> {params.status}"
            + (f"; because={because}" if because else ""),
            session_id=params.session,
            changes=(
                {"status": (current["status"], params.status)}
                if current["status"] != params.status
                else None
            ),
        )
    return {"id": params.id, "status": params.status}


def update(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    """Correct artifact metadata; URIs are paths, and paths move."""
    changes = {
        "uri": params.uri,
        "type": params.type,
        "usage_boundaries": params.usage_boundaries,
    }
    selected = {key: value for key, value in changes.items() if value is not None}
    if not selected:
        fail(
            "invalid_arguments",
            "Artifact update requires at least one changed field",
            EXIT_USAGE,
        )
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, params.actor)
        current = require_row(
            connection,
            "SELECT * FROM artifacts WHERE id = ?",
            (params.id,),
            f"artifact {params.id}",
        )
        require_expected_status(
            str(current["status"]),
            getattr(params, "if_status", None),
            entity="Artifact",
            entity_id=params.id,
        )
        assignments = ", ".join(f"{column} = ?" for column in selected)
        connection.execute(
            f"UPDATE artifacts SET {assignments}, updated_at = ? WHERE id = ?",
            (*selected.values(), stamp, params.id),
        )
        audit(
            connection,
            params.actor,
            "update",
            "artifact",
            params.id,
            f"fields={','.join(sorted(selected))}",
            session_id=params.session,
            changes={
                key: (current[key], value)
                for key, value in selected.items()
                if current[key] != value
            },
        )
        result = dict(
            connection.execute(
                "SELECT * FROM artifacts WHERE id = ?", (params.id,)
            ).fetchone()
        )
    return result
