"""Review entity commands."""

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
    optional_text,
    require_active_actor,
    require_row,
    required_text,
    rows,
    transaction,
)
from coordination.entities.audit import register_history
from coordination.entities.descriptors import (
    REVIEWS,
    add_query_arguments,
    query_options,
)


REVIEW_DECISIONS = (
    "accepted",
    "conditionally_accepted",
    "changes_requested",
    "rejected",
)


def add(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    with transaction(connection):
        require_active_actor(connection, params.reviewer)
        if params.task:
            require_row(
                connection,
                "SELECT id FROM tasks WHERE id = ?",
                (params.task,),
                f"task {params.task}",
            )
        connection.execute(
            """INSERT INTO reviews(
              id, task_id, reviewer_id, artifact_uri, scope, decision,
              accepted_items, required_changes, remaining_risks, blocked_claims,
              follow_up_tasks, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                params.id,
                params.task,
                params.reviewer,
                params.artifact,
                params.scope,
                params.decision,
                params.accepted_items,
                params.required_changes,
                params.risks,
                params.blocked_claims,
                params.follow_up_tasks,
                now(),
            ),
        )
        audit(
            connection,
            params.reviewer,
            "create",
            "review",
            params.id,
            params.decision,
            session_id=params.session,
        )
    return {"id": params.id, "decision": params.decision, "status": "created"}


def list_reviews(
    connection: sqlite3.Connection, params: Params
) -> list[dict[str, object]]:
    conditions: list[str] = []
    parameters: list[Any] = []
    if params.task:
        require_row(
            connection,
            "SELECT id FROM tasks WHERE id = ?",
            (params.task,),
            f"task {params.task}",
        )
        conditions.append("task_id = ?")
        parameters.append(params.task)
    extra_conditions, extra_parameters, order_sql = query_options(REVIEWS, params)
    conditions.extend(extra_conditions)
    parameters.extend(extra_parameters)
    query = "SELECT * FROM reviews"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " " + (order_sql or "ORDER BY created_at, id") + " LIMIT ? OFFSET ?"
    parameters.extend((params.limit, params.offset))
    return rows(connection.execute(query, parameters))


def show(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:

    row = require_row(
        connection,
        "SELECT * FROM reviews WHERE id = ?",
        (params.id,),
        f"review {params.id}",
    )
    result = dict(row)
    return result


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    review = commands.add_parser("review", help="Manage reviews").add_subparsers(
        dest="review_command",
        required=True,
    )
    add_parser = review.add_parser("add")
    add_parser.add_argument("--id", required=True, type=identifier)
    add_parser.add_argument("--task", type=identifier)
    add_parser.add_argument("--reviewer", required=True, type=identifier)
    add_parser.add_argument("--artifact", required=True, type=required_text)
    add_parser.add_argument("--scope", required=True, type=required_text)
    add_parser.add_argument("--decision", choices=REVIEW_DECISIONS, required=True)
    add_parser.add_argument("--accepted-items", default="", type=optional_text)
    add_parser.add_argument("--required-changes", default="", type=optional_text)
    add_parser.add_argument("--risks", default="", type=optional_text)
    add_parser.add_argument("--blocked-claims", default="", type=optional_text)
    add_parser.add_argument("--follow-up-tasks", default="", type=optional_text)
    add_parser.set_defaults(func=add)

    list_parser = review.add_parser("list")
    list_parser.add_argument("--task", type=identifier)
    add_query_arguments(list_parser, REVIEWS)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_reviews)
    show_parser = review.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)
    register_history(review, "review")
