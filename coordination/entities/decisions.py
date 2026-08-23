"""Decision entity commands."""

from __future__ import annotations

import argparse
import sqlite3
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    Params,
    audit,
    because_reference,
    identifier,
    list_limit,
    list_offset,
    now,
    optional_text,
    require_active_actor,
    require_row,
    required_text,
    resolve_reference,
    rows,
    transaction,
)
from coordination.entities.audit import register_history
from coordination.entities.descriptors import (
    DECISIONS,
    add_query_arguments,
    query_options,
)
from coordination.errors import EXIT_CONFLICT, fail


DECISION_STATUSES = ("proposed", "accepted", "superseded", "rejected")


def add(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, params.owner)
        connection.execute(
            """INSERT INTO decisions(
              id, title, owner_id, status, context, decision, options_considered,
              implications, evidence, blocked_claims, review_required,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                params.id,
                params.title,
                params.owner,
                params.status,
                params.context,
                params.decision,
                params.options,
                params.implications,
                params.evidence,
                params.blocked_claims,
                params.review_required,
                stamp,
                stamp,
            ),
        )
        audit(
            connection,
            params.owner,
            "create",
            "decision",
            params.id,
            params.status,
            session_id=params.session,
        )
    return {"id": params.id, "status": params.status}


def list_decisions(
    connection: sqlite3.Connection, params: Params
) -> list[dict[str, object]]:
    conditions, parameters, order_sql = query_options(DECISIONS, params)
    query = "SELECT * FROM decisions"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " " + (order_sql or "ORDER BY created_at, id") + " LIMIT ? OFFSET ?"
    parameters.extend((params.limit, params.offset))
    return rows(connection.execute(query, parameters))


def status(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    """Record a ruling on a decision after it was proposed.

    The schema anticipated every transition -- `superseded` was reachable only
    at creation, the one moment it can never be true -- and `updated_at` was
    written once. There is no notes column on decisions, so `--note` is kept in
    the audit detail. `--if-status` is compare-and-swap on the status the
    caller saw.
    """
    with transaction(connection):
        require_active_actor(connection, params.actor)
        current = require_row(
            connection,
            "SELECT status FROM decisions WHERE id = ?",
            (params.id,),
            f"decision {params.id}",
        )
        if_status = getattr(params, "if_status", None)
        if if_status is not None and str(current["status"]) != if_status:
            fail(
                "status_mismatch",
                f"Decision {params.id} is {current['status']}, not {if_status}",
                EXIT_CONFLICT,
                {
                    "decision": params.id,
                    "expected_status": if_status,
                    "actual_status": str(current["status"]),
                },
            )
        connection.execute(
            "UPDATE decisions SET status = ?, updated_at = ? WHERE id = ?",
            (params.status, now(), params.id),
        )
        detail = f"{current['status']} -> {params.status}"
        because = getattr(params, "because", None)
        if because:
            detail += f"; because={resolve_reference(connection, because)}"
        if params.note:
            detail += f"; {params.note}"
        audit(
            connection,
            params.actor,
            "status",
            "decision",
            params.id,
            detail,
            session_id=params.session,
        )
    return {
        "id": params.id,
        "previous_status": str(current["status"]),
        "status": params.status,
    }


def show(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:

    row = require_row(
        connection,
        "SELECT * FROM decisions WHERE id = ?",
        (params.id,),
        f"decision {params.id}",
    )
    result = dict(row)
    return result


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    decision = commands.add_parser("decision", help="Manage decisions").add_subparsers(
        dest="decision_command",
        required=True,
    )
    add_parser = decision.add_parser("add")
    add_parser.add_argument("--id", required=True, type=identifier)
    add_parser.add_argument("--title", required=True, type=required_text)
    add_parser.add_argument("--owner", required=True, type=identifier)
    add_parser.add_argument("--status", choices=DECISION_STATUSES, default="proposed")
    add_parser.add_argument("--context", required=True, type=required_text)
    add_parser.add_argument("--decision", required=True, type=required_text)
    add_parser.add_argument("--options", default="", type=optional_text)
    add_parser.add_argument("--implications", default="", type=optional_text)
    add_parser.add_argument("--evidence", default="", type=optional_text)
    add_parser.add_argument("--blocked-claims", default="", type=optional_text)
    add_parser.add_argument("--review-required", default="", type=optional_text)
    add_parser.set_defaults(func=add)

    list_parser = decision.add_parser("list")
    add_query_arguments(list_parser, DECISIONS)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_decisions)

    status_parser = decision.add_parser("status")
    status_parser.add_argument("id", type=identifier)
    status_parser.add_argument("status", choices=DECISION_STATUSES)
    status_parser.add_argument("--actor", required=True, type=identifier)
    status_parser.add_argument(
        "--if-status",
        choices=DECISION_STATUSES,
        help="Only change the status if it is currently this value",
    )
    status_parser.add_argument("--note", default="", type=optional_text)
    status_parser.add_argument(
        "--because",
        type=because_reference,
        help="Record the review, decision, or message (TYPE:ID) that caused this",
    )
    status_parser.set_defaults(func=status)
    show_parser = decision.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)
    register_history(decision, "decision")
