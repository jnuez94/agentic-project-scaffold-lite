"""Per-agent inbox: a self-asserted read position over the message ledger.

An agent's cursor is the audit id of the last message it has marked read. It is
a bookmark the agent keeps about its own position -- the same species as
`agent_sessions.last_seen_at` -- and asserts nothing about delivery, receipt,
or anyone else. Cursors live in one `metadata` row (`inbox_cursors`, a JSON
object keyed by agent id) so schema version 1 is unchanged and the 128-char
metadata key limit never meets a 128-char agent id.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
    audit_cursor,
    connect,
    discover_db,
    identifier,
    list_limit,
    list_offset,
    read_transaction,
    require_active_actor,
    require_row,
    rows,
    transaction,
)
from coordination.errors import EXIT_CONFLICT, EXIT_USAGE, fail


CURSORS_KEY = "inbox_cursors"


def load_cursors(connection: Any) -> dict[str, int]:
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = ?", (CURSORS_KEY,)
    ).fetchone()
    if row is None:
        return {}
    try:
        loaded = json.loads(str(row[0]))
    except ValueError:
        loaded = {}
    return (
        {
            str(agent): int(cursor)
            for agent, cursor in loaded.items()
            if isinstance(cursor, int) and not isinstance(cursor, bool)
        }
        if isinstance(loaded, dict)
        else {}
    )


def save_cursors(connection: Any, cursors: dict[str, int]) -> None:
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (CURSORS_KEY, json.dumps(dict(sorted(cursors.items())), sort_keys=True)),
    )


def initialise_cursor(connection: Any, agent_id: str, head: int) -> None:
    """Start a newly registered agent at the current head: an empty inbox."""
    cursors = load_cursors(connection)
    cursors[agent_id] = head
    save_cursors(connection, cursors)


def audit_head(connection: Any) -> int:
    return int(
        connection.execute("SELECT COALESCE(MAX(id), 0) FROM audit_log").fetchone()[0]
    )


def _resolve_agent(connection: Any, args: argparse.Namespace) -> str:
    """The inbox owner: `--agent`, or the agent of the global `--session`."""
    if getattr(args, "agent", None):
        return str(args.agent)
    if args.session:
        session = require_row(
            connection,
            "SELECT agent_id FROM agent_sessions WHERE id = ?",
            (args.session,),
            f"agent session {args.session}",
        )
        return str(session["agent_id"])
    fail(
        "invalid_arguments",
        "inbox requires --agent, or a global --session to derive the agent from",
        EXIT_USAGE,
        {"field": "agent"},
    )


def list_inbox(args: argparse.Namespace) -> dict[str, Any]:
    connection = connect(discover_db(args.db))
    with read_transaction(connection):
        agent = _resolve_agent(connection, args)
        require_row(
            connection, "SELECT id FROM agents WHERE id = ?", (agent,), f"agent {agent}"
        )
        cursor = load_cursors(connection).get(agent, 0)
        head = audit_head(connection)
        messages = rows(
            connection.execute(
                """SELECT m.*, a.id AS audit_id
                     FROM messages m
                     JOIN audit_log a
                       ON a.object_type = 'message' AND a.object_id = m.id
                      AND a.action = 'send'
                    WHERE (m.recipient = ? OR m.recipient = 'team')
                      AND a.id > ?
                    ORDER BY a.id LIMIT ? OFFSET ?""",
                (agent, cursor, args.limit, args.offset),
            )
        )
    return {"agent": agent, "cursor": cursor, "head": head, "messages": messages}


def mark_read(args: argparse.Namespace) -> dict[str, Any]:
    """Advance the agent's cursor, explicitly and only forward.

    A query that silently consumed its own results could not be run twice,
    which makes it useless for exactly the debugging you need it for; the
    cursor moves only when asked. The audited actor is the agent itself: this
    is the agent's own position.
    """
    connection = connect(discover_db(args.db))
    with transaction(connection):
        agent = _resolve_agent(connection, args)
        require_active_actor(connection, agent)
        cursors = load_cursors(connection)
        previous = cursors.get(agent, 0)
        head = audit_head(connection)
        if args.cursor > head:
            fail(
                "invalid_arguments",
                f"Cursor {args.cursor} is beyond the audit head {head}",
                EXIT_USAGE,
                {"cursor": args.cursor, "head": head},
            )
        if args.cursor < previous:
            fail(
                "cursor_not_monotonic",
                f"Inbox cursor for {agent} is already at {previous}",
                EXIT_CONFLICT,
                {"agent": agent, "cursor": previous, "requested": args.cursor},
            )
        cursors[agent] = args.cursor
        save_cursors(connection, cursors)
        audit(
            connection,
            agent,
            "mark_read",
            "agent",
            agent,
            f"inbox cursor {previous} -> {args.cursor}",
            session_id=args.session,
        )
    return {
        "agent": agent,
        "previous_cursor": previous,
        "cursor": args.cursor,
        "head": head,
    }


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    inbox = commands.add_parser(
        "inbox", help="Messages for an agent after its read position"
    ).add_subparsers(dest="inbox_command", required=True)
    list_parser = inbox.add_parser("list")
    list_parser.add_argument(
        "--agent", type=identifier, help="Inbox owner; defaults to the session's agent"
    )
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_inbox)

    mark_parser = inbox.add_parser("mark-read")
    mark_parser.add_argument(
        "--agent", type=identifier, help="Inbox owner; defaults to the session's agent"
    )
    mark_parser.add_argument(
        "--cursor",
        required=True,
        type=audit_cursor,
        help="Audit id of the last message read; must not move backwards",
    )
    mark_parser.set_defaults(func=mark_read)
