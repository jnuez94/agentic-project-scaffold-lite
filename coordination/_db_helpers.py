"""Transactions, the audit ledger, and accountable-principal checks."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager
import sqlite3
from typing import Any, cast

from coordination._locking import current_scope
from coordination._primitives import now
from coordination._validators import BECAUSE_TABLES
from coordination.errors import (
    EXIT_CONFLICT,
    EXIT_INTERNAL,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    fail,
)


def resolve_reference(connection: sqlite3.Connection, reference: str) -> str:
    """Require the referenced record to exist; return the canonical reference.

    Causality is a fact the ledger may carry: a status change that names the
    review, decision, or message that caused it. The reference is checked at
    write time so the audit trail never points at a record that was never
    there.
    """
    kind, _, record_id = reference.partition(":")
    table = BECAUSE_TABLES[kind]
    require_row(
        connection,
        f"SELECT id FROM {table} WHERE id = ?",
        (record_id,),
        f"{kind} {record_id}",
    )
    return reference


@contextmanager
def transaction(connection: sqlite3.Connection) -> Generator[None, None, None]:
    """Run a short write transaction that acquires SQLite's writer lock first.

    Reentrancy-safe: inside an already-open transaction it yields without
    beginning or committing, so a future outer owner (a service-held
    transaction spanning calls) can enclose entity code unchanged. Today each
    entity operation opens exactly one.
    """
    if connection.in_transaction:
        yield
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


@contextmanager
def read_transaction(connection: sqlite3.Connection) -> Generator[None, None, None]:
    """Keep multi-statement reports on one coherent SQLite snapshot.

    Reentrancy-safe like `transaction`: inside an open transaction it simply
    yields, inheriting the enclosing snapshot.
    """
    if connection.in_transaction:
        yield
        return
    connection.execute("BEGIN")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def audit(
    connection: sqlite3.Connection,
    actor: str | None,
    action: str,
    object_type: str,
    object_id: str,
    detail: str = "",
    session_id: str | None = None,
    changes: Mapping[str, tuple[object, object]] | None = None,
) -> int:
    stamp = now()
    require_active_actor(connection, actor)
    if session_id:
        require_active_session(connection, session_id, actor)
        connection.execute(
            "UPDATE agent_sessions SET last_seen_at = ? WHERE id = ?",
            (stamp, session_id),
        )
    cursor = connection.execute(
        """INSERT INTO audit_log(
             actor, session_id, action, object_type, object_id, detail, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (actor, session_id, action, object_type, object_id, detail, stamp),
    )
    audit_id = cursor.lastrowid
    if audit_id is None:  # pragma: no cover - INSERT always assigns a row ID
        fail(
            "internal_error",
            "Audit record did not receive a row ID",
            EXIT_INTERNAL,
        )
    if changes:
        connection.executemany(
            """INSERT INTO change_log(
                 audit_id, object_type, object_id, field,
                 old_value, new_value, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    audit_id,
                    object_type,
                    object_id,
                    field,
                    None if old is None else str(old),
                    None if new is None else str(new),
                    stamp,
                )
                for field, (old, new) in sorted(changes.items())
            ],
        )
    scope = current_scope()
    if scope is not None:
        scope.audit_ids.append(int(audit_id))
    return audit_id


def require_active_actor(
    connection: sqlite3.Connection,
    actor: str | None,
) -> sqlite3.Row:
    if not actor:
        fail(
            "invalid_actor",
            "A mutation requires an accountable actor",
            EXIT_USAGE,
        )
    value = connection.execute(
        "SELECT id, status FROM agents WHERE id = ?",
        (actor,),
    ).fetchone()
    if value is None:
        fail(
            "not_found",
            f"Not found: agent {actor}",
            EXIT_NOT_FOUND,
            {"resource": f"agent {actor}"},
        )
    if value["status"] != "active":
        fail(
            "inactive_actor",
            f"Agent {actor} is not active",
            EXIT_CONFLICT,
            {"actor": actor},
        )
    return cast(sqlite3.Row, value)


def require_active_session(
    connection: sqlite3.Connection,
    session_id: str,
    actor: str | None,
) -> sqlite3.Row:
    if not actor:
        fail(
            "invalid_actor",
            "A session-aware mutation requires an actor",
            EXIT_USAGE,
        )
    session = require_row(
        connection,
        """SELECT s.agent_id, s.status, a.status AS agent_status
           FROM agent_sessions s
           JOIN agents a ON a.id = s.agent_id
           WHERE s.id = ?""",
        (session_id,),
        f"agent session {session_id}",
    )
    if session["agent_id"] != actor:
        fail(
            "session_actor_mismatch",
            f"Session {session_id} belongs to {session['agent_id']}, not actor {actor}",
            EXIT_CONFLICT,
        )
    if session["status"] != "active":
        fail(
            "inactive_session",
            f"Agent session {session_id} is not active",
            EXIT_CONFLICT,
        )
    if session["agent_status"] != "active":
        fail(
            "inactive_actor",
            f"Agent {actor} is not active",
            EXIT_CONFLICT,
            {"actor": actor},
        )
    return session


def require_row(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...],
    label: str,
) -> sqlite3.Row:
    value = connection.execute(query, parameters).fetchone()
    if value is None:
        fail("not_found", f"Not found: {label}", EXIT_NOT_FOUND, {"resource": label})
    return cast(sqlite3.Row, value)
