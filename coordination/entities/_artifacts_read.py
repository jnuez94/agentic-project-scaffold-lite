"""Artifact statuses and read operations."""

from __future__ import annotations

from collections.abc import Iterable
import sqlite3
from typing import Any

from coordination.core import (
    Params,
    read_transaction,
    require_row,
)
from coordination.entities.descriptors import (
    ARTIFACTS,
    query_options,
)


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


def list_artifacts(
    connection: sqlite3.Connection, params: Params
) -> list[dict[str, Any]]:
    query = "SELECT a.* FROM artifacts a"
    conditions: list[str] = []
    parameters: list[Any] = []
    if params.status:
        conditions.append("a.status = ?")
        parameters.append(params.status)
    extra_conditions, extra_parameters, order_sql = query_options(ARTIFACTS, params)
    conditions.extend(extra_conditions)
    parameters.extend(extra_parameters)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " " + (order_sql or "ORDER BY a.updated_at, a.id") + " LIMIT ? OFFSET ?"
    parameters.extend((params.limit, params.offset))
    with read_transaction(connection):
        result = shape_artifacts(connection, connection.execute(query, parameters))
    return result


def show(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    with read_transaction(connection):
        row = require_row(
            connection,
            "SELECT a.* FROM artifacts a WHERE a.id = ?",
            (params.id,),
            f"artifact {params.id}",
        )
        result = shape_artifacts(connection, [row])[0]
    return result
