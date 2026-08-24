"""Task read operations: filtered list and single-task show."""

from __future__ import annotations

import sqlite3
from typing import Any

from coordination.core import (
    MAX_LIST_LIMIT,
    Params,
    read_transaction,
    require_row,
    rows,
)
from coordination.entities._tasks_shared import shape_tasks, task_query
from coordination.entities.descriptors import TASKS, query_options


def list_tasks(connection: sqlite3.Connection, params: Params) -> list[dict[str, Any]]:
    query = task_query()
    conditions: list[str] = []
    parameters: list[Any] = []
    if params.status:
        statuses = (
            [params.status] if isinstance(params.status, str) else list(params.status)
        )
        placeholders = ",".join("?" for _ in statuses)
        conditions.append(f"t.status IN ({placeholders})")
        parameters.extend(statuses)
    if getattr(params, "tag", None):
        # `tags` is free text of comma-separated tokens. Compare against the
        # token list with surrounding whitespace removed, so "a, b" and "a,b"
        # both carry tokens a and b. LIKE wildcards in the tag are escaped.
        escaped = (
            params.tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        conditions.append(
            "(',' || REPLACE(REPLACE(t.tags, ' ', ''), char(9), '') || ',')"
            " LIKE ? ESCAPE '\\'"
        )
        parameters.append(f"%,{escaped},%")
    if params.assignee:
        conditions.append(
            "EXISTS (SELECT 1 FROM task_assignees x"
            " WHERE x.task_id = t.id AND x.agent_id = ?)"
        )
        parameters.append(params.assignee)
    extra_conditions, extra_parameters, order_sql = query_options(TASKS, params)
    conditions.extend(extra_conditions)
    parameters.extend(extra_parameters)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += (
        " "
        + (order_sql or "ORDER BY t.priority, t.updated_at, t.id")
        + " LIMIT ? OFFSET ?"
    )
    parameters.extend((params.limit, params.offset))
    with read_transaction(connection):
        result = shape_tasks(connection, connection.execute(query, parameters))
    return result


def show(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    with read_transaction(connection):
        task = require_row(
            connection,
            task_query() + " WHERE t.id = ?",
            (params.id,),
            f"task {params.id}",
        )
        result = shape_tasks(connection, [task])[0]
        # Each detail array is bounded like every list command. An unbounded
        # inspect grew linearly with attached rows and could hand a client a
        # multi-megabyte response; `evidence_count` and the per-entity list
        # commands remain the complete view. Truncation is reported, never
        # silent.
        truncated: list[str] = []
        for name, query in (
            (
                "evidence",
                """SELECT * FROM task_evidence
                   WHERE task_id = ? ORDER BY created_at, id""",
            ),
            (
                "dependencies",
                """SELECT * FROM task_dependencies
                   WHERE task_id = ?
                   ORDER BY depends_on_task_id, dependency_type""",
            ),
            (
                "reviews",
                "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at, id",
            ),
        ):
            values = rows(
                connection.execute(
                    query + " LIMIT ?",
                    (params.id, MAX_LIST_LIMIT + 1),
                )
            )
            if len(values) > MAX_LIST_LIMIT:
                truncated.append(name)
            result[name] = values[:MAX_LIST_LIMIT]
        result["truncated_sections"] = truncated
    return result
