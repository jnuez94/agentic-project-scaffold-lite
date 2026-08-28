#!/usr/bin/env python3
"""Qualify migrate: verified backup, staged upgrade, atomic publish, rollback.

The version-1 fixture is the frozen schema shipped with release 1.4.0, taken
from that tag, so migration is exercised against a real historical database
rather than a synthetic downgrade.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.entities import _maintenance_migrate as migrate_engine  # noqa: E402
from coordination.entities import maintenance  # noqa: E402
from coordination.errors import CoordinationError  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


V1_SCHEMA = (ROOT / "tests" / "fixtures" / "schema-v1.sql").read_text()
STAMP = "2026-01-01T00:00:00+00:00"


def make_v1(database: Path, *, active_session: bool = False) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.executescript(V1_SCHEMA)
    connection.execute(
        "INSERT INTO agents(id, name, role, created_at, updated_at)"
        " VALUES ('alice', 'Alice', 'r', ?, ?)",
        (STAMP, STAMP),
    )
    connection.execute(
        "INSERT INTO tasks(id, title, created_by, created_at, updated_at)"
        " VALUES ('T-1', 'v1 task', 'alice', ?, ?)",
        (STAMP, STAMP),
    )
    connection.execute(
        "INSERT INTO audit_log(actor, action, object_type, object_id, detail,"
        " created_at) VALUES ('alice', 'create', 'task', 'T-1', '', ?)",
        (STAMP,),
    )
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES ('carried-forward', 'yes')"
    )
    if active_session:
        connection.execute(
            "INSERT INTO agent_sessions(id, agent_id, harness, started_at,"
            " last_seen_at) VALUES ('run-1', 'alice', 'codex', ?, ?)",
            (STAMP, STAMP),
        )
    connection.commit()
    connection.close()


def namespace(database: Path, actor: str = "alice") -> argparse.Namespace:
    return argparse.Namespace(db=str(database), actor=actor, session=None)


def schema_version(database: Path) -> int:
    with sqlite3.connect(database) as raw:
        return int(raw.execute("PRAGMA user_version").fetchone()[0])


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def test_successful_migration(database: Path) -> None:
    make_v1(database)
    result = maintenance.migrate(namespace(database))
    assert result["from_schema"] == 1 and result["to_schema"] == 2
    assert result["verified"] is True and result["audit_recorded"] is True
    assert schema_version(database) == 2

    backup = Path(str(result["backup"]))
    assert backup.is_file() and schema_version(backup) == 1
    with sqlite3.connect(backup) as raw:
        assert raw.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1

    service = CoordinationService(db=str(database))
    doctor = service.invoke("doctor", {})
    assert doctor["healthy"] is True and doctor["schema_version"] == 2
    task = service.invoke("task_show", {"id": "T-1"})
    assert task["title"] == "v1 task"
    with sqlite3.connect(database) as raw:
        assert raw.execute("SELECT COUNT(*) FROM change_log").fetchone()[0] == 0
        carried = raw.execute(
            "SELECT value FROM metadata WHERE key = 'carried-forward'"
        ).fetchone()[0]
        migrated = raw.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'migrate'"
        ).fetchone()[0]
    assert carried == "yes" and migrated == 1

    # The ledger works from migration day: an update writes change rows.
    service.invoke(
        "task_update",
        {"id": "T-1", "actor": "alice", "if_revision": 1, "title": "post-migration"},
    )
    changes = service.invoke(
        "audit_changes", {"object_type": "task", "object_id": "T-1"}
    )
    assert [(row["old_value"], row["new_value"]) for row in changes] == [
        ("v1 task", "post-migration")
    ]

    expect("already_current", lambda: maintenance.migrate(namespace(database)))


def test_refusals_leave_the_database_untouched(database: Path) -> None:
    make_v1(database, active_session=True)
    expect("migrate_active_sessions", lambda: maintenance.migrate(namespace(database)))
    assert schema_version(database) == 1

    reserved = database.parent / "reserved-name.sqlite3"
    make_v1(reserved)
    with sqlite3.connect(reserved) as raw:
        raw.execute("CREATE TABLE change_log(x INTEGER)")
    error = expect(
        "migration_blocked", lambda: maintenance.migrate(namespace(reserved))
    )
    assert (error.details or {})["objects"] == ["change_log"]
    assert (error.details or {})["target_unchanged"] is True
    assert schema_version(reserved) == 1

    other = database.parent / "unknown-actor.sqlite3"
    make_v1(other)
    try:
        maintenance.migrate(namespace(other, actor="nobody"))
    except CoordinationError:
        pass
    else:
        raise AssertionError("unknown actor unexpectedly migrated")
    assert schema_version(other) == 1


def test_publication_failure_is_atomic(database: Path) -> None:
    make_v1(database)
    original_replace = migrate_engine.os.replace
    target = database.resolve()

    def failed_replace(source: object, destination: object) -> None:
        if Path(destination).resolve() == target and ".migrate." in Path(source).name:
            raise OSError("injected publication failure")
        original_replace(source, destination)

    migrate_engine.os.replace = failed_replace
    try:
        error = expect(
            "migration_publication_failed",
            lambda: maintenance.migrate(namespace(database)),
        )
    finally:
        migrate_engine.os.replace = original_replace
    details = error.details or {}
    assert details["target_unchanged"] is True
    assert schema_version(database) == 1
    with sqlite3.connect(database) as raw:
        assert raw.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_verification_failure_rolls_back(database: Path) -> None:
    make_v1(database)
    original_fsync = migrate_engine.fsync_file
    target = database.resolve()
    injected = False

    def failed_fsync(path: Path) -> None:
        nonlocal injected
        if Path(path).resolve() == target and not injected:
            injected = True
            raise OSError("injected post-publication fsync failure")
        original_fsync(path)

    migrate_engine.fsync_file = failed_fsync
    try:
        error = expect(
            "migration_verification_failed",
            lambda: maintenance.migrate(namespace(database)),
        )
    finally:
        migrate_engine.fsync_file = original_fsync
    details = error.details or {}
    assert details["rollback_performed"] is True
    assert details["rollback_succeeded"] is True
    assert details["rollback_verified"] is True
    assert schema_version(database) == 1
    with sqlite3.connect(database) as raw:
        assert raw.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert (
            raw.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'migrate'"
            ).fetchone()[0]
            == 0
        )


def test_postrename_interrupt_rolls_back(database: Path) -> None:
    make_v1(database)
    original_replace = migrate_engine.os.replace
    target = database.resolve()

    def interrupted_replace(source: object, destination: object) -> None:
        original_replace(source, destination)
        if Path(destination).resolve() == target and ".migrate." in Path(source).name:
            raise CoordinationError(
                "operation_interrupted",
                "injected interruption after atomic publication",
                5,
            )

    migrate_engine.os.replace = interrupted_replace
    try:
        error = expect(
            "migration_verification_failed",
            lambda: maintenance.migrate(namespace(database)),
        )
    finally:
        migrate_engine.os.replace = original_replace
    details = error.details or {}
    assert details["rollback_performed"] is True
    assert details["rollback_verified"] is True
    assert schema_version(database) == 1


def test_rollback_failure_is_reported(database: Path) -> None:
    make_v1(database)
    original_fsync = migrate_engine.fsync_file
    original_rollback = migrate_engine._rollback_published_migration
    target = database.resolve()
    injected = False

    def failed_fsync(path: Path) -> None:
        nonlocal injected
        if Path(path).resolve() == target and not injected:
            injected = True
            raise OSError("injected verification failure")
        original_fsync(path)

    def failed_rollback(*_args: object, **_kwargs: object) -> bool:
        raise OSError("injected rollback failure")

    migrate_engine.fsync_file = failed_fsync
    migrate_engine._rollback_published_migration = failed_rollback
    try:
        error = expect(
            "migration_verification_failed",
            lambda: maintenance.migrate(namespace(database)),
        )
    finally:
        migrate_engine.fsync_file = original_fsync
        migrate_engine._rollback_published_migration = original_rollback
    details = error.details or {}
    assert details["rollback_performed"] is True
    assert details["rollback_succeeded"] is False
    assert details["rollback_verified"] is False


def test_cli_parity(database: Path) -> None:
    make_v1(database)
    completed = subprocess.run(
        [
            str(ROOT / "scripts" / "coordination.py"),
            "--db",
            str(database),
            "migrate",
            "--actor",
            "alice",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    envelope = json.loads(completed.stdout)
    assert envelope["ok"] is True
    assert envelope["data"]["to_schema"] == 2
    assert "audit_range" in envelope
    assert schema_version(database) == 2


def main() -> int:
    for test in (
        test_successful_migration,
        test_refusals_leave_the_database_untouched,
        test_publication_failure_is_atomic,
        test_verification_failure_rolls_back,
        test_postrename_interrupt_rolls_back,
        test_rollback_failure_is_reported,
        test_cli_parity,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-migrate-") as name:
            test(Path(name) / ".coordination" / "coordination.sqlite3")
    print("Migration qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
