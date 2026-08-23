"""Audit log read access.

The audit trail is the accountability record the tool exists to keep. Until
this module existed it was reachable only by opening the SQLite file, which the
project's own guidance forbids. `audit list` is bounded, filtered, ordered by
`id`, and `--since CURSOR` returns rows with `id` greater than the cursor so a
client can poll for what changed without re-fetching everything.
"""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit_cursor,
    connect,
    discover_db,
    identifier,
    list_limit,
    list_offset,
    required_text,
    rows,
)


def list_audit(args: argparse.Namespace) -> list[dict[str, Any]]:
    connection = connect(discover_db(args.db))
    conditions: list[str] = []
    parameters: list[Any] = []
    for column, value in (
        ("actor", args.actor),
        ("session_id", args.session_id),
        ("object_type", args.object_type),
        ("object_id", args.object_id),
        ("action", args.action),
    ):
        if value is not None:
            conditions.append(f"{column} = ?")
            parameters.append(value)
    if args.since:
        conditions.append("id > ?")
        parameters.append(args.since)
    query = "SELECT * FROM audit_log"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id LIMIT ? OFFSET ?"
    parameters.extend((args.limit, args.offset))
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


def history(args: argparse.Namespace) -> list[dict[str, Any]]:
    """One record's timeline: its audit rows in id order, optionally after a cursor."""
    connection = connect(discover_db(args.db))
    return rows(
        connection.execute(
            """SELECT * FROM audit_log
               WHERE object_type = ? AND object_id = ? AND id > ?
               ORDER BY id LIMIT ? OFFSET ?""",
            (args.object_type, args.id, args.since, args.limit, args.offset),
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
