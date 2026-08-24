"""Session lifecycle: start, heartbeat, end, list, and show."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Any

from coordination.core import (
    Params,
    audit,
    now,
    require_active_actor,
    require_row,
    rows,
    transaction,
)
from coordination.entities.descriptors import (
    SESSIONS,
    query_options,
)
from coordination.errors import EXIT_CONFLICT, fail


SESSION_STATUSES = ("active", "ended")


def require_open_session(
    connection: Any,
    session_id: str,
) -> Any:
    session = require_row(
        connection,
        "SELECT agent_id, status FROM agent_sessions WHERE id = ?",
        (session_id,),
        f"agent session {session_id}",
    )
    if session["status"] != "active":
        fail(
            "inactive_session",
            f"Agent session {session_id} is not active",
            EXIT_CONFLICT,
            {"session_id": session_id},
        )
    return session


def start(connection: sqlite3.Connection, params: Params) -> dict[str, object]:
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, params.agent)
        connection.execute(
            """INSERT INTO agent_sessions(
                 id, agent_id, harness, model, status, started_at, last_seen_at
               ) VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (params.id, params.agent, params.harness, params.model, stamp, stamp),
        )
        audit(
            connection,
            params.agent,
            "start",
            "session",
            params.id,
            params.harness,
            session_id=params.id,
        )
    return {
        "id": params.id,
        "agent_id": params.agent,
        "harness": params.harness,
        "model": params.model,
        "status": "active",
    }


def list_sessions(
    connection: sqlite3.Connection, params: Params
) -> list[dict[str, Any]]:
    query = "SELECT * FROM agent_sessions"
    conditions: list[str] = []
    parameters: list[Any] = []
    if params.agent:
        conditions.append("agent_id = ?")
        parameters.append(params.agent)
    if params.status:
        conditions.append("status = ?")
        parameters.append(params.status)
    if params.harness:
        conditions.append("harness = ?")
        parameters.append(params.harness)
    extra_conditions, extra_parameters, order_sql = query_options(SESSIONS, params)
    conditions.extend(extra_conditions)
    parameters.extend(extra_parameters)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " " + (order_sql or "ORDER BY started_at, id") + " LIMIT ? OFFSET ?"
    parameters.extend((params.limit, params.offset))
    return rows(connection.execute(query, parameters))


def heartbeat(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    with transaction(connection):
        session = require_open_session(connection, params.id)
        audit(
            connection,
            session["agent_id"],
            "heartbeat",
            "session",
            params.id,
            session_id=params.id,
        )
    return {"id": params.id, "status": "active"}


def end(connection: sqlite3.Connection, params: Params) -> dict[str, str]:
    stamp = now()
    with transaction(connection):
        session = require_open_session(connection, params.id)
        claimed_tasks = [
            str(row[0])
            for row in connection.execute(
                "SELECT task_id FROM task_claims WHERE session_id = ? ORDER BY task_id",
                (params.id,),
            )
        ]
        if claimed_tasks:
            fail(
                "session_has_active_claims",
                f"Session {params.id} cannot end while it owns active task claims",
                EXIT_CONFLICT,
                {"session_id": params.id, "tasks": claimed_tasks},
            )
        audit(
            connection,
            session["agent_id"],
            "end",
            "session",
            params.id,
            session_id=params.id,
        )
        connection.execute(
            """UPDATE agent_sessions
               SET status = 'ended', last_seen_at = ?, ended_at = ?
               WHERE id = ?""",
            (stamp, stamp, params.id),
        )
    return {"id": params.id, "status": "ended"}


def stale_cutoff(seconds: int) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(seconds=seconds))
        .replace(microsecond=0)
        .isoformat()
    )


def show(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:

    row = require_row(
        connection,
        "SELECT * FROM agent_sessions WHERE id = ?",
        (params.id,),
        f"session {params.id}",
    )
    result = dict(row)
    return result
