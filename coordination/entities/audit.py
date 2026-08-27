"""Audit log read access.

The audit trail is the accountability record the tool exists to keep. Until
this module existed it was reachable only by opening the SQLite file, which the
project's own guidance forbids. `audit list` is bounded, filtered, ordered by
`id`, and `--since CURSOR` returns rows with `id` greater than the cursor so a
client can poll for what changed without re-fetching everything.
"""

from __future__ import annotations

import argparse
import sqlite3
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    Params,
    audit_cursor,
    identifier,
    list_limit,
    list_offset,
    required_text,
    rows,
)
from coordination.entities._audit_write import redact as redact


def list_audit(connection: sqlite3.Connection, params: Params) -> list[dict[str, Any]]:
    conditions: list[str] = []
    parameters: list[Any] = []
    for column, value in (
        ("actor", params.actor),
        ("session_id", params.session_id),
        ("object_type", params.object_type),
        ("object_id", params.object_id),
        ("action", params.action),
    ):
        if value is not None:
            conditions.append(f"{column} = ?")
            parameters.append(value)
    if params.since:
        conditions.append("id > ?")
        parameters.append(params.since)
    query = "SELECT * FROM audit_log"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id LIMIT ? OFFSET ?"
    parameters.extend((params.limit, params.offset))
    return rows(connection.execute(query, parameters))


def changes(connection: sqlite3.Connection, params: Params) -> list[dict[str, Any]]:
    """Field-level before/after rows for the security and behavior audit."""
    conditions: list[str] = []
    parameters: list[Any] = []
    if params.audit_id is not None:
        conditions.append("audit_id = ?")
        parameters.append(params.audit_id)
    if params.object_type is not None:
        conditions.append("object_type = ?")
        parameters.append(params.object_type)
    if params.object_id is not None:
        conditions.append("object_id = ?")
        parameters.append(params.object_id)
    if params.since:
        conditions.append("id > ?")
        parameters.append(params.since)
    query = "SELECT * FROM change_log"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id LIMIT ? OFFSET ?"
    parameters.extend((params.limit, params.offset))
    return rows(connection.execute(query, parameters))


HISTORY_OBJECT_TYPES = (
    "task",
    "agent",
    "session",
    "artifact",
    "decision",
    "message",
    "review",
    "escalation",
)


def history(connection: sqlite3.Connection, params: Params) -> list[dict[str, Any]]:
    """One record's timeline: its audit rows in id order, optionally after a cursor."""
    return rows(
        connection.execute(
            """SELECT * FROM audit_log
               WHERE object_type = ? AND object_id = ? AND id > ?
               ORDER BY id LIMIT ? OFFSET ?""",
            (params.object_type, params.id, params.since, params.limit, params.offset),
        )
    )


def register_history(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    object_type: str,
) -> None:
    """Add `<entity> history ID` to an entity's subcommands."""
    parser = subparsers.add_parser(
        "history",
        help=f"Audit timeline of one {object_type}, oldest first",
    )
    parser.add_argument("id", type=identifier)
    parser.add_argument(
        "--since",
        type=audit_cursor,
        default=0,
        help="Only rows with audit id greater than this cursor",
    )
    parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    parser.add_argument("--offset", type=list_offset, default=0)
    parser.set_defaults(func=history, object_type=object_type)


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    audit_parser = commands.add_parser(
        "audit", help="Read the audit log"
    ).add_subparsers(
        dest="audit_command",
        required=True,
    )
    list_parser = audit_parser.add_parser("list")
    list_parser.add_argument("--actor", type=identifier)
    # `--session` is the global attribution option; the filter is distinct.
    # The service parameter is `session_id`; the global attribution option is
    # `--session` (dest `session`), so the two never collide.
    list_parser.add_argument(
        "--session-id",
        dest="session_id",
        type=identifier,
        help="Only rows attributed to this execution session",
    )
    list_parser.add_argument("--object-type", type=required_text)
    list_parser.add_argument("--object-id", type=required_text)
    list_parser.add_argument("--action", type=required_text)
    list_parser.add_argument(
        "--since",
        type=audit_cursor,
        default=0,
        help="Only rows with id greater than this cursor",
    )
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_audit)
    changes_parser = audit_parser.add_parser(
        "changes",
        help="Field-level before/after rows recorded with audit events",
    )
    changes_parser.add_argument(
        "--id",
        dest="audit_id",
        type=audit_cursor,
        help="Only rows recorded with this audit event",
    )
    changes_parser.add_argument("--object-type", type=required_text)
    changes_parser.add_argument("--object-id", type=required_text)
    changes_parser.add_argument(
        "--since",
        type=audit_cursor,
        default=0,
        help="Only rows with change id greater than this cursor",
    )
    changes_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    changes_parser.add_argument("--offset", type=list_offset, default=0)
    changes_parser.set_defaults(func=changes, audit_id=None)

    redact_parser = audit_parser.add_parser(
        "redact",
        help="Redact one audit row's detail and change rows, leaving a tombstone",
    )
    redact_parser.add_argument(
        "--id",
        required=True,
        type=audit_cursor,
    )
    redact_parser.add_argument("--actor", required=True, type=identifier)
    redact_parser.add_argument("--reason", required=True, type=required_text)
    redact_parser.set_defaults(func=redact)
