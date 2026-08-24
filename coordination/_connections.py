"""Opening verified connections and database-level consistency checks."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
import sqlite3
from typing import Any

from coordination._locking import (
    _CONNECTION_LOCKS,
    _acquire_file_lock,
    _release_file_lock,
    _track_connection,
    configured_busy_timeout_ms,
    database_lock_path,
)
from coordination._output import rows
from coordination._paths import validate_database_operational_files
from coordination._primitives import MAX_DIAGNOSTIC_FINDINGS
from coordination._schema import ensure_supported_schema
from coordination.errors import EXIT_ENVIRONMENT, EXIT_NOT_FOUND, fail


def connect(
    path: Path,
    require_initialized: bool = True,
    *,
    configure_journal: bool = True,
) -> sqlite3.Connection:
    if require_initialized and not path.is_file():
        fail(
            "database_not_found",
            f"Coordination database not found: {path}",
            EXIT_NOT_FOUND,
        )
    validate_database_operational_files(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = configured_busy_timeout_ms()
    handle = _acquire_file_lock(
        database_lock_path(path),
        exclusive=False,
        timeout_ms=timeout_ms,
    )
    try:
        validate_database_operational_files(path)
        connection = sqlite3.connect(path, timeout=timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
        if require_initialized:
            ensure_supported_schema(connection)
            if configure_journal:
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
                ).lower()
                if journal_mode != "wal":
                    fail(
                        "database_configuration_error",
                        "Coordination database must use WAL journal mode",
                        EXIT_ENVIRONMENT,
                        {"journal_mode": journal_mode},
                    )
        connection.execute("PRAGMA synchronous = FULL")
        synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])
        if synchronous != 2:
            fail(
                "database_configuration_error",
                "Coordination database must use FULL synchronous durability",
                EXIT_ENVIRONMENT,
                {"synchronous": synchronous},
            )
    except BaseException:
        # `connection` stays unbound when sqlite3.connect itself raised.
        with suppress(UnboundLocalError):
            connection.close()
        _release_file_lock(handle)
        raise
    _CONNECTION_LOCKS[id(connection)] = handle
    _track_connection(connection)
    return connection


def connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        fail(
            "database_not_found",
            f"Coordination database not found: {path}",
            EXIT_NOT_FOUND,
        )
    validate_database_operational_files(path)
    timeout_ms = configured_busy_timeout_ms()
    handle = _acquire_file_lock(
        database_lock_path(path),
        exclusive=False,
        timeout_ms=timeout_ms,
    )
    try:
        validate_database_operational_files(path)
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro",
            timeout=timeout_ms / 1000,
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
        ensure_supported_schema(connection)
    except BaseException:
        # `connection` stays unbound when sqlite3.connect itself raised.
        with suppress(UnboundLocalError):
            connection.close()
        _release_file_lock(handle)
        raise
    _CONNECTION_LOCKS[id(connection)] = handle
    _track_connection(connection)
    return connection


def check_database_integrity(connection: sqlite3.Connection) -> dict[str, str]:
    integrity_results: list[str] = []
    integrity_result_count = 0
    for row in connection.execute("PRAGMA integrity_check"):
        integrity_result_count += 1
        if len(integrity_results) < 10:
            integrity_results.append(str(row[0]))
    if integrity_results != ["ok"]:
        fail(
            "database_corrupt",
            "SQLite integrity check failed",
            EXIT_ENVIRONMENT,
            {
                "integrity_check": integrity_results,
                "result_count": integrity_result_count,
                "truncated": integrity_result_count > len(integrity_results),
            },
        )
    foreign_key_violations: list[dict[str, Any]] = []
    foreign_key_violation_count = 0
    for row in connection.execute("PRAGMA foreign_key_check"):
        foreign_key_violation_count += 1
        if len(foreign_key_violations) < 10:
            foreign_key_violations.append(dict(row))
    if foreign_key_violation_count:
        fail(
            "foreign_key_violation",
            "SQLite foreign-key consistency check failed",
            EXIT_ENVIRONMENT,
            {
                "violation_count": foreign_key_violation_count,
                "violations": foreign_key_violations,
                "truncated": (
                    foreign_key_violation_count > len(foreign_key_violations)
                ),
            },
        )
    return {"integrity_check": "ok", "foreign_key_check": "ok"}


def check_coordination_invariants(connection: sqlite3.Connection) -> dict[str, str]:
    truncated_sections: list[str] = []

    def bounded_ids(name: str, query: str) -> list[str]:
        values = [
            str(row[0])
            for row in connection.execute(
                query + " LIMIT ?",
                (MAX_DIAGNOSTIC_FINDINGS + 1,),
            )
        ]
        if len(values) > MAX_DIAGNOSTIC_FINDINGS:
            truncated_sections.append(name)
        return values[:MAX_DIAGNOSTIC_FINDINGS]

    def bounded_rows(name: str, query: str) -> list[dict[str, Any]]:
        values = rows(
            connection.execute(
                query + " LIMIT ?",
                (MAX_DIAGNOSTIC_FINDINGS + 1,),
            )
        )
        if len(values) > MAX_DIAGNOSTIC_FINDINGS:
            truncated_sections.append(name)
        return values[:MAX_DIAGNOSTIC_FINDINGS]

    unclaimed = bounded_ids(
        "unclaimed_in_progress_tasks",
        """SELECT t.id FROM tasks t
           WHERE t.status = 'in_progress'
             AND NOT EXISTS (
               SELECT 1 FROM task_claims c WHERE c.task_id = t.id
             )
           ORDER BY t.id""",
    )
    invalid_claims = bounded_rows(
        "invalid_active_claims",
        """SELECT c.task_id, c.agent_id, c.session_id,
                  t.status AS task_status,
                  s.status AS session_status,
                  s.agent_id AS session_agent_id,
                  a.status AS agent_status
           FROM task_claims c
           JOIN tasks t ON t.id = c.task_id
           JOIN agent_sessions s ON s.id = c.session_id
           JOIN agents a ON a.id = c.agent_id
           WHERE t.status <> 'in_progress'
              OR s.status <> 'active'
              OR s.agent_id <> c.agent_id
              OR a.status <> 'active'
           ORDER BY c.task_id""",
    )
    done_without_evidence = bounded_ids(
        "done_without_evidence",
        """SELECT t.id FROM tasks t
           WHERE t.status = 'done'
             AND NOT EXISTS (
               SELECT 1 FROM task_evidence e WHERE e.task_id = t.id
             )
           ORDER BY t.id""",
    )
    invalid_sessions = bounded_rows(
        "invalid_sessions",
        """SELECT s.id, s.agent_id, s.status, s.ended_at,
                  a.status AS agent_status
           FROM agent_sessions s
           JOIN agents a ON a.id = s.agent_id
           WHERE (s.status = 'active' AND (
                    s.ended_at IS NOT NULL OR a.status <> 'active'
                 ))
              OR (s.status = 'ended' AND s.ended_at IS NULL)
           ORDER BY s.id""",
    )
    if unclaimed or invalid_claims or done_without_evidence or invalid_sessions:
        fail(
            "coordination_invariant_violation",
            "Coordination state invariants failed",
            EXIT_ENVIRONMENT,
            {
                "unclaimed_in_progress_tasks": unclaimed,
                "invalid_active_claims": invalid_claims,
                "done_without_evidence": done_without_evidence,
                "invalid_sessions": invalid_sessions,
                "truncated_sections": truncated_sections,
            },
        )
    return {"coordination_invariants": "ok"}
