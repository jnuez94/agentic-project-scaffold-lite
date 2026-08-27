"""Schema v2 ledger: append-only enforcement and the audit change hook."""

from __future__ import annotations

from collections.abc import Iterator
import sqlite3

import pytest

from coordination.core import audit, canonical_schema_sql


STAMP = "2026-01-01T00:00:00+00:00"


@pytest.fixture()
def connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    connection.executescript(canonical_schema_sql())
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "INSERT INTO agents(id, name, role, created_at, updated_at)"
        " VALUES ('alice', 'Alice', 'engineering', ?, ?)",
        (STAMP, STAMP),
    )
    yield connection
    connection.close()


def audit_row(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        "INSERT INTO audit_log(actor, action, object_type, object_id, detail,"
        " created_at) VALUES ('alice', 'update', 'task', 'T-1', 'was: x', ?)",
        (STAMP,),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def test_audit_delete_is_refused(connection: sqlite3.Connection) -> None:
    audit_row(connection)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM audit_log")


def test_audit_update_is_refused(connection: sqlite3.Connection) -> None:
    row_id = audit_row(connection)
    for statement, parameters in [
        ("UPDATE audit_log SET detail = 'rewritten' WHERE id = ?", (row_id,)),
        ("UPDATE audit_log SET actor = 'alice' WHERE id = ?", (row_id,)),
        ("UPDATE audit_log SET created_at = ? WHERE id = ?", (STAMP, row_id)),
        (
            "UPDATE audit_log SET detail = '[redacted:not-a-number]' WHERE id = ?",
            (row_id,),
        ),
        (
            "UPDATE audit_log SET detail = '[redacted:9]', action = 'x' WHERE id = ?",
            (row_id,),
        ),
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="redaction"):
            connection.execute(statement, parameters)


def test_audit_detail_redaction_is_permitted(
    connection: sqlite3.Connection,
) -> None:
    row_id = audit_row(connection)
    connection.execute(
        "UPDATE audit_log SET detail = '[redacted:99]' WHERE id = ?",
        (row_id,),
    )
    detail = connection.execute(
        "SELECT detail FROM audit_log WHERE id = ?", (row_id,)
    ).fetchone()[0]
    assert detail == "[redacted:99]"


def test_audit_helper_writes_change_rows(connection: sqlite3.Connection) -> None:
    audit_id = audit(
        connection,
        "alice",
        "update",
        "task",
        "T-1",
        "updated",
        changes={"title": ("old", "new"), "priority": (3, 4), "needed_by": (None, "x")},
    )
    rows = connection.execute(
        "SELECT field, old_value, new_value FROM change_log"
        " WHERE audit_id = ? ORDER BY field",
        (audit_id,),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("needed_by", None, "x"),
        ("priority", "3", "4"),
        ("title", "old", "new"),
    ]


def test_change_log_delete_is_refused(connection: sqlite3.Connection) -> None:
    audit(connection, "alice", "update", "task", "T-1", changes={"title": ("a", "b")})
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM change_log")


def test_change_log_update_is_refused(connection: sqlite3.Connection) -> None:
    audit(connection, "alice", "update", "task", "T-1", changes={"title": ("a", "b")})
    for statement in [
        "UPDATE change_log SET new_value = 'rewritten'",
        "UPDATE change_log SET field = 'other'",
        "UPDATE change_log SET old_value = '[redacted:9]', new_value = NULL",
        "UPDATE change_log SET old_value = NULL, new_value = '[redacted:9]'",
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="redaction"):
            connection.execute(statement)


def test_change_log_value_redaction_is_permitted(
    connection: sqlite3.Connection,
) -> None:
    audit_id = audit(
        connection, "alice", "update", "task", "T-1", changes={"title": ("a", "b")}
    )
    connection.execute(
        "UPDATE change_log SET old_value = '[redacted:7]', new_value = '[redacted:7]'"
        " WHERE audit_id = ?",
        (audit_id,),
    )
    row = connection.execute(
        "SELECT old_value, new_value FROM change_log WHERE audit_id = ?",
        (audit_id,),
    ).fetchone()
    assert tuple(row) == ("[redacted:7]", "[redacted:7]")
