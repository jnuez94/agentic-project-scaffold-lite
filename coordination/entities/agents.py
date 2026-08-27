"""Agent entity commands."""

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
    require_row,
    required_text,
    rows,
    transaction,
)
from coordination.entities.audit import register_history
from coordination.entities.descriptors import AGENTS, add_query_arguments, query_options
from coordination.entities.inbox import initialise_cursor
from coordination.errors import EXIT_CONFLICT, EXIT_NOT_FOUND, EXIT_USAGE, fail


def add(connection: sqlite3.Connection, params: Params) -> dict[str, object]:
    stamp = now()
    with transaction(connection):
        connection.execute(
            """INSERT INTO agents(
              id, name, role, actor_type, status, responsibilities, goal,
              operating_style, decision_authority, review_authority,
              escalation_rules, unavailable_for, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                params.id,
                params.name,
                params.role,
                params.actor_type,
                params.responsibilities,
                params.goal,
                params.operating_style,
                params.decision_authority,
                params.review_authority,
                params.escalation_rules,
                params.unavailable_for,
                stamp,
                stamp,
            ),
        )
        created = audit(
            connection,
            params.actor or params.id,
            "create",
            "agent",
            params.id,
            session_id=params.session,
        )
        # A new agent inherits an empty inbox, not the project's history: its
        # read position starts at the audit head, which is its own creation.
        initialise_cursor(connection, params.id, created)
    return {"id": params.id, "actor_type": params.actor_type, "status": "created"}


def list_agents(connection: sqlite3.Connection, params: Params) -> list[dict[str, Any]]:
    query = "SELECT * FROM agents"
    parameters: tuple[Any, ...] = ()
    conditions: list[str] = []
    values: list[Any] = []
    if not params.all:
        conditions.append("status = ?")
        values.append("active")
    if params.actor_type:
        conditions.append("actor_type = ?")
        values.append(params.actor_type)
    extra_conditions, extra_values, order_sql = query_options(AGENTS, params)
    conditions.extend(extra_conditions)
    values.extend(extra_values)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " " + (order_sql or "ORDER BY role, id") + " LIMIT ? OFFSET ?"
    values.extend((params.limit, params.offset))
    parameters = tuple(values)
    return rows(connection.execute(query, parameters))


def update(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:
    changes = {
        "name": params.name,
        "role": params.role,
        "actor_type": params.actor_type,
        "status": params.status,
    }
    selected = {key: value for key, value in changes.items() if value is not None}
    if not selected:
        fail(
            "invalid_arguments",
            "Agent update requires at least one changed field",
            EXIT_USAGE,
        )
    # A status change is the consequential edit: deactivation locks an actor
    # out. Defaulting its attribution to the target wrote "bob deactivated
    # bob" into the audit log for anyone who omitted --actor, which forges
    # the record the tool exists to keep. Profile edits keep the documented
    # default; a status change names its accountable actor explicitly.
    if params.status is not None and not params.actor:
        fail(
            "invalid_arguments",
            "Changing an agent's status requires an explicit --actor",
            EXIT_USAGE,
            {"field": "actor"},
        )
    stamp = now()
    assignments = ", ".join(f"{column} = ?" for column in selected)
    parameters = [*selected.values(), stamp, params.id]
    actor = params.actor or params.id
    with transaction(connection):
        existing = connection.execute(
            "SELECT * FROM agents WHERE id = ?",
            (params.id,),
        ).fetchone()
        if existing is None:
            fail(
                "not_found",
                f"Not found: agent {params.id}",
                EXIT_NOT_FOUND,
                {"resource": f"agent {params.id}"},
            )
        if params.status == "inactive":
            active_sessions = [
                str(row[0])
                for row in connection.execute(
                    """SELECT id FROM agent_sessions
                       WHERE agent_id = ? AND status = 'active'
                       ORDER BY id""",
                    (params.id,),
                )
            ]
            if active_sessions:
                fail(
                    "agent_has_active_sessions",
                    f"Agent {params.id} cannot be deactivated"
                    " while sessions are active",
                    EXIT_CONFLICT,
                    {"agent": params.id, "sessions": active_sessions},
                )
        audit(
            connection,
            actor,
            "update",
            "agent",
            params.id,
            ",".join(selected),
            session_id=params.session,
            changes={
                key: (existing[key], value)
                for key, value in selected.items()
                if existing[key] != value
            },
        )
        cursor = connection.execute(
            f"UPDATE agents SET {assignments}, updated_at = ? WHERE id = ?",
            parameters,
        )
        if cursor.rowcount != 1:
            fail(
                "not_found",
                f"Not found: agent {params.id}",
                EXIT_NOT_FOUND,
                {"resource": f"agent {params.id}"},
            )
        result = dict(
            connection.execute(
                "SELECT * FROM agents WHERE id = ?",
                (params.id,),
            ).fetchone()
        )
    return result


def show(connection: sqlite3.Connection, params: Params) -> dict[str, Any]:

    row = require_row(
        connection,
        "SELECT * FROM agents WHERE id = ?",
        (params.id,),
        f"agent {params.id}",
    )
    result = dict(row)
    return result


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    agent = commands.add_parser("agent", help="Manage agents").add_subparsers(
        dest="agent_command",
        required=True,
    )
    add_parser = agent.add_parser("add")
    add_parser.add_argument("--id", required=True, type=identifier)
    add_parser.add_argument("--name", required=True, type=required_text)
    add_parser.add_argument("--role", required=True, type=required_text)
    add_parser.add_argument(
        "--actor-type",
        choices=("ai", "human", "service"),
        default="ai",
    )
    add_parser.add_argument("--responsibilities", default="", type=optional_text)
    add_parser.add_argument("--goal", default="", type=optional_text)
    add_parser.add_argument("--operating-style", default="", type=optional_text)
    add_parser.add_argument("--decision-authority", default="", type=optional_text)
    add_parser.add_argument("--review-authority", default="", type=optional_text)
    add_parser.add_argument("--escalation-rules", default="", type=optional_text)
    add_parser.add_argument("--unavailable-for", default="", type=optional_text)
    add_parser.add_argument("--actor", type=identifier)
    add_parser.set_defaults(func=add)

    list_parser = agent.add_parser("list")
    list_parser.add_argument("--all", action="store_true")
    list_parser.add_argument("--actor-type", choices=("ai", "human", "service"))
    add_query_arguments(list_parser, AGENTS)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_agents)

    update_parser = agent.add_parser("update")
    update_parser.add_argument("id", type=identifier)
    update_parser.add_argument("--name", type=required_text)
    update_parser.add_argument("--role", type=required_text)
    update_parser.add_argument("--actor-type", choices=("ai", "human", "service"))
    update_parser.add_argument("--status", choices=("active", "inactive"))
    update_parser.add_argument("--actor", type=identifier)
    update_parser.set_defaults(func=update)
    show_parser = agent.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)
    register_history(agent, "agent")
