"""Migration preparation: v1 validation, the verified v1 backup, staged DDL.

The staged copy receives the version-2 objects from the canonical schema
definitions, so a migrated database is definition-identical to a fresh init.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile

from coordination.core import (
    SCHEMA_VERSION,
    audit,
    check_coordination_invariants,
    check_database_integrity,
    ensure_supported_schema,
    expected_schema_definitions,
    fsync_directory,
    fsync_file,
    require_active_actor,
    transaction,
)
from coordination.entities._maintenance_backup import _raw_connection
from coordination.entities._maintenance_restore_support import (
    _active_target_sessions,
    _safety_backup_path,
)
from coordination.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, fail


V2_OBJECTS = (
    ("table", "change_log"),
    ("index", "idx_change_log_audit"),
    ("index", "idx_change_log_object"),
    ("trigger", "audit_log_append_only_delete"),
    ("trigger", "audit_log_redaction_only_update"),
    ("trigger", "change_log_append_only_delete"),
    ("trigger", "change_log_redaction_only_update"),
)


def _require_version_one(connection: sqlite3.Connection, database: Path) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version == SCHEMA_VERSION:
        fail(
            "already_current",
            f"Database already uses schema {SCHEMA_VERSION}; nothing to migrate",
            EXIT_CONFLICT,
            {"database": str(database), "schema_version": version},
        )
    if version != 1:
        fail(
            "unsupported_schema",
            f"Only schema 1 can be migrated; this database is schema {version}",
            EXIT_ENVIRONMENT,
            {"database_schema": version, "supported_schema": SCHEMA_VERSION},
        )
    try:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row is None or str(row[0]) != "1":
        fail(
            "schema_mismatch",
            "Database metadata does not record schema version 1",
            EXIT_ENVIRONMENT,
            {
                "database": str(database),
                "metadata_schema": None if row is None else str(row[0]),
            },
        )


def _require_migratable_source(
    connection: sqlite3.Connection,
    database: Path,
    actor: str,
) -> None:
    """A migratable source is a healthy version-1 database with no writers."""
    _require_version_one(connection, database)
    reserved = [name for _, name in V2_OBJECTS]
    placeholders = ", ".join("?" for _ in reserved)
    colliding = sorted(
        str(row[0])
        for row in connection.execute(
            f"SELECT name FROM sqlite_master WHERE name IN ({placeholders})",
            reserved,
        )
    )
    if colliding:
        fail(
            "migration_blocked",
            "Database defines objects whose names schema 2 reserves",
            EXIT_CONFLICT,
            {
                "database": str(database),
                "objects": colliding,
                "target_unchanged": True,
            },
        )
    check_database_integrity(connection)
    check_coordination_invariants(connection)
    active_sessions = _active_target_sessions(connection)
    if active_sessions:
        fail(
            "migrate_active_sessions",
            "End or recover every active session before migrating",
            EXIT_CONFLICT,
            {"sessions": active_sessions},
        )
    require_active_actor(connection, actor)


def _verified_v1_backup(
    source: sqlite3.Connection,
    database: Path,
    stamp: str,
) -> str:
    """Publish a verified version-1 copy; migration refuses to run without one."""
    destination = _safety_backup_path(database, f"pre-migrate-{stamp}.sqlite3")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    copy: sqlite3.Connection | None = None
    try:
        copy = _raw_connection(temporary)
        source.backup(copy)
        _require_version_one(copy, temporary)
        check_database_integrity(copy)
        check_coordination_invariants(copy)
        copy.close()
        copy = None
        os.chmod(temporary, 0o600)
        fsync_file(temporary)
        os.replace(temporary, destination)
        fsync_directory(destination.parent)
    finally:
        if copy is not None:
            copy.close()
        temporary.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{temporary}{suffix}").unlink(missing_ok=True)
    return str(destination)


def _staged_migrated_copy(
    source: sqlite3.Connection,
    target_path: Path,
    stamp: str,
    actor: str,
    backup_path: str,
) -> tuple[Path, int]:
    """Stage a copy, apply the canonical v2 objects, verify, and audit."""
    row_counts = {
        str(row[0]): int(
            source.execute(f'SELECT COUNT(*) FROM "{row[0]}"').fetchone()[0]
        )
        for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'"
        )
    }
    definitions = expected_schema_definitions()
    descriptor, staged_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.migrate.{stamp}.",
        suffix=".tmp",
        dir=target_path.parent,
    )
    os.close(descriptor)
    staged = Path(staged_name)
    connection: sqlite3.Connection | None = None
    try:
        connection = _raw_connection(staged)
        source.backup(connection)
        connection.execute("BEGIN IMMEDIATE")
        for object_type, name in V2_OBJECTS:
            connection.execute(definitions[(object_type, name)][1])
        cursor = connection.execute(
            "UPDATE metadata SET value = '2' WHERE key = 'schema_version'"
        )
        if cursor.rowcount != 1:
            fail(
                "migration_verification_failed",
                "Staged migration could not update the schema-version metadata",
                EXIT_ENVIRONMENT,
                {"database": str(target_path), "target_unchanged": True},
            )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
        ensure_supported_schema(connection)
        check_database_integrity(connection)
        check_coordination_invariants(connection)
        preserved = {
            table: int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for table in row_counts
        }
        if preserved != row_counts:
            fail(
                "migration_verification_failed",
                "Staged migration did not preserve every record",
                EXIT_ENVIRONMENT,
                {
                    "database": str(target_path),
                    "target_unchanged": True,
                    "expected": row_counts,
                    "actual": preserved,
                },
            )
        with transaction(connection):
            audit_id = audit(
                connection,
                actor,
                "migrate",
                "database",
                str(target_path),
                f"schema 1 -> {SCHEMA_VERSION}; backup {backup_path}",
            )
        connection.close()
        connection = None
        os.chmod(staged, 0o600)
        fsync_file(staged)
    except BaseException:
        if connection is not None:
            connection.close()
        staged.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{staged}{suffix}").unlink(missing_ok=True)
        raise
    finally:
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{staged}{suffix}").unlink(missing_ok=True)
    return staged, audit_id
