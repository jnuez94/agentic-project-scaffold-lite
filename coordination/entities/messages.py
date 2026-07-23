"""Message entity commands."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import audit, connect, discover_db, emit, now, rows


def send(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
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
    query += " ORDER BY created_at"
    emit(rows(connection.execute(query, parameters)))


def register(commands: argparse._SubParsersAction) -> None:
    message = commands.add_parser("message", help="Manage messages").add_subparsers(
        dest="message_command",
        required=True,
    )
    send_parser = message.add_parser("send")
    send_parser.add_argument("--id", required=True)
    send_parser.add_argument("--sender", required=True)
    send_parser.add_argument("--recipient", required=True)
    send_parser.add_argument("--task")
    send_parser.add_argument("--body", required=True)
    send_parser.add_argument("--tags", default="")
    send_parser.set_defaults(func=send)

    list_parser = message.add_parser("list")
    list_parser.add_argument("--recipient")
    list_parser.set_defaults(func=list_messages)
