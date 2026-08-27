"""Message entity commands."""

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
    MESSAGES,
    add_query_arguments,
    query_options,
)
from coordination.errors import EXIT_CONFLICT, fail


def send(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    with transaction(connection):
        require_active_actor(connection, params.sender)
        if params.task:
            require_row(
                connection,
                "SELECT id FROM tasks WHERE id = ?",
                (params.task,),
                f"task {params.task}",
            )
        connection.execute(
            """INSERT INTO messages(
                 id, sender_id, recipient, task_id, body, tags, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                params.id,
                params.sender,
                params.recipient,
                params.task,
                params.body,
                params.tags,
                now(),
            ),
        )
        audit(
            connection,
            params.sender,
            "send",
            "message",
            params.id,
            params.recipient,
            session_id=params.session,
        )
    return {"id": params.id, "status": "sent"}


def list_messages(
    connection: sqlite3.Connection, params: Params
) -> list[dict[str, Any]]:
    query = "SELECT * FROM messages"
    conditions: list[str] = []
    parameters: list[Any] = []
    if params.recipient:
        conditions.append("recipient IN (?, 'team')")
        parameters.append(params.recipient)
    if getattr(params, "task", None):
        conditions.append("task_id = ?")
        parameters.append(params.task)
    extra_conditions, extra_parameters, order_sql = query_options(MESSAGES, params)
    conditions.extend(extra_conditions)
    parameters.extend(extra_parameters)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " " + (order_sql or "ORDER BY created_at, id") + " LIMIT ? OFFSET ?"
    parameters.extend((params.limit, params.offset))
    return rows(connection.execute(query, parameters))


REDACTED_BODY = "[redacted]"


def redact(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    """Remove a message's content while keeping the fact that it was sent.

    The project tells users to keep secrets and regulated data out of
    coordination records; until now the only remediation was editing the
    database by hand, which the same guidance forbids. Redaction replaces the
    body with a marker, leaves the row, sender, recipient, task, and timestamps
    intact, and records the redaction itself -- an audit trail that can be
    silently rewritten is not an audit trail.
    """
    with transaction(connection):
        require_active_actor(connection, params.actor)
        current = require_row(
            connection,
            "SELECT body FROM messages WHERE id = ?",
            (params.id,),
            f"message {params.id}",
        )
        if current["body"] == REDACTED_BODY:
            fail(
                "already_redacted",
                f"Message {params.id} is already redacted",
                EXIT_CONFLICT,
                {"message": params.id},
            )
        connection.execute(
            "UPDATE messages SET body = ? WHERE id = ?",
            (REDACTED_BODY, params.id),
        )
        # Deliberately no change_log rows: recording the previous body
        # would preserve exactly the content this operation removes.
        audit(
            connection,
            params.actor,
            "redact",
            "message",
            params.id,
            params.reason,
            session_id=params.session,
        )
    return {"id": params.id, "status": "redacted"}


def show(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:

    row = require_row(
        connection,
        "SELECT * FROM messages WHERE id = ?",
        (params.id,),
        f"message {params.id}",
    )
    result = dict(row)
    return result


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    message = commands.add_parser("message", help="Manage messages").add_subparsers(
        dest="message_command",
        required=True,
    )
    send_parser = message.add_parser("send")
    send_parser.add_argument("--id", required=True, type=identifier)
    send_parser.add_argument("--sender", required=True, type=identifier)
    send_parser.add_argument("--recipient", required=True, type=required_text)
    send_parser.add_argument("--task", type=identifier)
    send_parser.add_argument("--body", required=True, type=required_text)
    send_parser.add_argument("--tags", default="", type=optional_text)
    send_parser.set_defaults(func=send)

    list_parser = message.add_parser("list")
    list_parser.add_argument("--recipient", type=required_text)
    list_parser.add_argument("--task", type=identifier, help="Messages about one task")
    add_query_arguments(list_parser, MESSAGES)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_messages)

    redact_parser = message.add_parser("redact")
    redact_parser.add_argument("id", type=identifier)
    redact_parser.add_argument("--actor", required=True, type=identifier)
    redact_parser.add_argument("--reason", required=True, type=required_text)
    redact_parser.set_defaults(func=redact)
    show_parser = message.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)
    register_history(message, "message")
