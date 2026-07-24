"""Message entity commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
    connect,
    discover_db,
    emit,
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


def send(args: argparse.Namespace) -> None:
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
    emit({"id": args.id, "status": "sent"})


def list_messages(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM messages"
    parameters: tuple[Any, ...] = ()
    if args.recipient:
        query += " WHERE recipient IN (?, 'team')"
        parameters = (args.recipient,)
    query += " ORDER BY created_at, id LIMIT ? OFFSET ?"
    parameters = (*parameters, args.limit, args.offset)
    emit(rows(connection.execute(query, parameters)))


def register(commands: argparse._SubParsersAction) -> None:
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
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_messages)
