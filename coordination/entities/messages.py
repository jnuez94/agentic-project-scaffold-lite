"""Message entity commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
    connect,
    discover_db,
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
from coordination.errors import EXIT_CONFLICT, fail


def send(args: argparse.Namespace) -> dict[str, str]:
    connection = connect(discover_db(args.db))
    with transaction(connection):
        require_active_actor(connection, args.sender)
        if args.task:
            require_row(
                connection,
                "SELECT id FROM tasks WHERE id = ?",
                (args.task,),
                f"task {args.task}",
            )
        connection.execute(
            """INSERT INTO messages(
                 id, sender_id, recipient, task_id, body, tags, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                args.id,
                args.sender,
                args.recipient,
                args.task,
                args.body,
                args.tags,
                now(),
            ),
        )
        audit(
            connection,
            args.sender,
            "send",
            "message",
            args.id,
            args.recipient,
            session_id=args.session,
        )
    return {"id": args.id, "status": "sent"}


def list_messages(args: argparse.Namespace) -> list[dict[str, Any]]:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM messages"
    conditions: list[str] = []
    parameters: list[Any] = []
    if args.recipient:
        conditions.append("recipient IN (?, 'team')")
        parameters.append(args.recipient)
    if getattr(args, "task", None):
        conditions.append("task_id = ?")
        parameters.append(args.task)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at, id LIMIT ? OFFSET ?"
    parameters.extend((args.limit, args.offset))
    return rows(connection.execute(query, parameters))


REDACTED_BODY = "[redacted]"


def redact(args: argparse.Namespace) -> dict[str, str]:
    """Remove a message's content while keeping the fact that it was sent.

    The project tells users to keep secrets and regulated data out of
    coordination records; until now the only remediation was editing the
    database by hand, which the same guidance forbids. Redaction replaces the
    body with a marker, leaves the row, sender, recipient, task, and timestamps
    intact, and records the redaction itself -- an audit trail that can be
    silently rewritten is not an audit trail.
    """
    connection = connect(discover_db(args.db))
    with transaction(connection):
        require_active_actor(connection, args.actor)
        current = require_row(
            connection,
            "SELECT body FROM messages WHERE id = ?",
            (args.id,),
            f"message {args.id}",
        )
        if current["body"] == REDACTED_BODY:
            fail(
                "already_redacted",
                f"Message {args.id} is already redacted",
                EXIT_CONFLICT,
                {"message": args.id},
            )
        connection.execute(
            "UPDATE messages SET body = ? WHERE id = ?",
            (REDACTED_BODY, args.id),
        )
        audit(
            connection,
            args.actor,
            "redact",
            "message",
            args.id,
            args.reason,
            session_id=args.session,
        )
    return {"id": args.id, "status": "redacted"}


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
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_messages)

    redact_parser = message.add_parser("redact")
    redact_parser.add_argument("id", type=identifier)
    redact_parser.add_argument("--actor", required=True, type=identifier)
    redact_parser.add_argument("--reason", required=True, type=required_text)
    redact_parser.set_defaults(func=redact)
