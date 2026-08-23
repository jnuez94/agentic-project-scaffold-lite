"""Entity operations run against an injected in-memory connection.

The point of the entity-signature change (#25): row operations are pure
functions of (connection, params), so their logic is testable here -- no
subprocess, no filesystem, no discovery. The service adds validation,
receipts, and the operation log on top; none of that is required to exercise
entity behavior.
"""

from __future__ import annotations

import sqlite3

import pytest

from coordination.core import Params, canonical_schema_sql
from coordination.entities import agents, inbox, messages, tasks
from coordination.errors import CoordinationError


@pytest.fixture
def connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(canonical_schema_sql())
    yield connection
    connection.close()


def _params(**values: object) -> Params:
    values.setdefault("session", None)
    return Params(**values)


def _agent(connection: sqlite3.Connection, agent_id: str) -> None:
    agents.add(
        connection,
        _params(
            id=agent_id,
            name=agent_id,
            role="r",
            actor_type="ai",
            responsibilities="",
            goal="",
            operating_style="",
            decision_authority="",
            review_authority="",
            escalation_rules="",
            unavailable_for="",
            actor=None,
        ),
    )


def test_task_lifecycle_on_an_injected_connection(
    connection: sqlite3.Connection,
) -> None:
    _agent(connection, "alice")
    created = tasks.create(
        connection,
        _params(
            id="T-1",
            title="t",
            actor="alice",
            description="",
            priority=3,
            tags="",
            acceptance="",
            next_steps="",
            blocked_claims="",
            assignee=[],
        ),
    )
    assert created["revision"] == 1 and created["status"] == "todo"
    listed = tasks.list_tasks(
        connection,
        _params(status=None, assignee=None, tag=None, limit=100, offset=0),
    )
    assert [row["id"] for row in listed] == ["T-1"]
    with pytest.raises(CoordinationError) as caught:
        tasks.update(
            connection,
            _params(
                id="T-1",
                actor="alice",
                if_revision=9,
                title="x",
                description=None,
                priority=None,
                tags=None,
                acceptance=None,
                next_steps=None,
                blocked_claims=None,
            ),
        )
    assert caught.value.code == "stale_task_revision"
    actions = [
        str(row["action"])
        for row in connection.execute(
            "SELECT action FROM audit_log WHERE object_id = 'T-1' ORDER BY id"
        )
    ]
    assert actions == ["create"], "the refused update audited nothing"


def test_inbox_cursor_and_send_share_one_connection(
    connection: sqlite3.Connection,
) -> None:
    _agent(connection, "alice")
    _agent(connection, "bob")
    messages.send(
        connection,
        _params(
            id="M-1", sender="alice", recipient="bob", body="hi", task=None, tags=""
        ),
    )
    unread = inbox.list_inbox(connection, _params(agent="bob", limit=100, offset=0))
    assert [row["id"] for row in unread["messages"]] == ["M-1"]
    assert unread["cursor"] < unread["messages"][0]["audit_id"] <= unread["head"]
