"""Shared database, discovery, audit, and output infrastructure."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Generator, Iterable

from coordination.errors import (
    EXIT_CONFLICT,
    EXIT_ENVIRONMENT,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    fail,
)


SCHEMA_VERSION = 1
DEFAULT_BUSY_TIMEOUT_MS = 5000
MAX_BUSY_TIMEOUT_MS = 60000
REQUIRED_COLUMNS = {
    "metadata": frozenset({"key", "value"}),
    "agents": frozenset(
        {
            "id",
            "name",
            "role",
            "actor_type",
            "status",
            "responsibilities",
            "goal",
            "operating_style",
            "decision_authority",
            "review_authority",
            "escalation_rules",
            "unavailable_for",
            "created_at",
            "updated_at",
        }
    ),
    "agent_sessions": frozenset(
        {
            "id",
            "agent_id",
            "harness",
            "model",
            "status",
            "started_at",
            "last_seen_at",
            "ended_at",
        }
    ),
    "tasks": frozenset(
        {
            "id",
            "title",
            "description",
            "status",
            "priority",
            "tags",
            "acceptance_criteria",
            "next_steps",
            "blocked_claims",
            "notes",
            "revision",
            "created_by",
            "created_at",
            "updated_at",
        }
    ),
    "task_assignees": frozenset({"task_id", "agent_id", "assigned_at"}),
    "task_claims": frozenset({"task_id", "agent_id", "session_id", "claimed_at"}),
    "task_dependencies": frozenset(
        {
            "task_id",
            "depends_on_task_id",
            "dependency_type",
            "status",
            "rationale",
            "created_at",
        }
    ),
    "task_evidence": frozenset(
        {"id", "task_id", "uri", "evidence_type", "added_by", "created_at"}
    ),
    "messages": frozenset(
        {"id", "sender_id", "recipient", "task_id", "body", "tags", "created_at"}
    ),
    "reviews": frozenset(
        {
            "id",
            "task_id",
            "reviewer_id",
            "artifact_uri",
            "scope",
            "decision",
            "accepted_items",
            "required_changes",
            "remaining_risks",
            "blocked_claims",
            "follow_up_tasks",
            "created_at",
        }
    ),
    "decisions": frozenset(
        {
            "id",
            "title",
            "owner_id",
            "status",
            "context",
            "decision",
            "options_considered",
            "implications",
            "evidence",
            "blocked_claims",
            "review_required",
            "created_at",
            "updated_at",
        }
    ),
    "artifacts": frozenset(
        {
            "id",
            "uri",
            "owner_id",
            "type",
            "status",
            "usage_boundaries",
            "created_at",
            "updated_at",
        }
    ),
    "artifact_tasks": frozenset({"artifact_id", "task_id"}),
    "artifact_reviewers": frozenset({"artifact_id", "reviewer_id"}),
    "escalations": frozenset(
        {
            "id",
            "raised_by",
            "owner",
            "status",
            "related_tasks",
            "needed_by",
            "issue",
            "requested_decision",
            "resolution",
            "follow_up_tasks",
            "created_at",
            "updated_at",
        }
    ),
    "audit_log": frozenset(
        {
            "id",
            "actor",
            "session_id",
            "action",
            "object_type",
            "object_id",
            "detail",
            "created_at",
        }
    ),
}
REQUIRED_TABLES = frozenset(REQUIRED_COLUMNS)
REQUIRED_INDEXES = frozenset(
    {
        "idx_tasks_status_priority",
        "idx_agent_sessions_agent_status",
        "idx_task_assignees_agent",
        "idx_task_claims_agent",
        "idx_evidence_task",
        "idx_reviews_task",
        "idx_messages_recipient",
        "idx_escalations_status",
        "idx_audit_session",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "task_claim_requires_active_session",
        "task_claim_requires_claimable_state",
        "task_enter_in_progress_requires_claim",
        "task_insert_done_requires_evidence",
        "task_status_requires_next_revision",
        "task_update_done_requires_evidence",
    }
)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def configured_busy_timeout_ms() -> int:
    raw = os.environ.get("COORDINATION_BUSY_TIMEOUT_MS", str(DEFAULT_BUSY_TIMEOUT_MS))
    try:
        value = int(raw)
    except ValueError:
        fail(
            "configuration_error",
            "COORDINATION_BUSY_TIMEOUT_MS must be an integer",
            EXIT_ENVIRONMENT,
            {"value": raw},
        )
    if not 0 <= value <= MAX_BUSY_TIMEOUT_MS:
        fail(
            "configuration_error",
            f"COORDINATION_BUSY_TIMEOUT_MS must be between 0 and {MAX_BUSY_TIMEOUT_MS}",
            EXIT_ENVIRONMENT,
            {"value": value},
        )
    return value


def emit(value: Any) -> None:
    print(json.dumps({"ok": True, "data": value}, indent=2, sort_keys=True))


def rows(values: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(value) for value in values]


def discover_db(explicit: str | None, for_init: bool = False) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        coordination = directory / ".coordination"
        config = coordination / "config.yml"
        if config.is_file():
            database = "coordination.sqlite3"
            for line in config.read_text(encoding="utf-8").splitlines():
                if line.startswith("database:"):
                    database = line.split(":", 1)[1].strip()
            return coordination / database
    if for_init:
        return current / ".coordination" / "coordination.sqlite3"
    fail(
        "configuration_error",
        "No SQLite coordination project found. Run from the project or pass --db PATH.",
        EXIT_ENVIRONMENT,
    )


def schema_path() -> Path:
    package = Path(__file__).resolve()
    candidates: list[Path] = []
    for ancestor in package.parents:
        candidates.extend((ancestor / "sqlite" / "schema.sql", ancestor / "assets" / "sqlite" / "schema.sql"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    fail(
        "installation_error",
        "SQLite schema is not installed with the coordination runtime",
        EXIT_ENVIRONMENT,
    )


def runtime_version() -> str:
    package = Path(__file__).resolve()
    for ancestor in package.parents:
        version = ancestor / "VERSION"
        if version.is_file():
            return version.read_text(encoding="utf-8").strip()
    fail(
        "installation_error",
        "VERSION is not installed with the coordination runtime",
        EXIT_ENVIRONMENT,
    )


def schema_details(connection: sqlite3.Connection) -> dict[str, Any]:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    objects: dict[str, set[str]] = {"table": set(), "index": set(), "trigger": set()}
    for row in connection.execute(
        """SELECT type, name FROM sqlite_master
           WHERE type IN ('table', 'index', 'trigger')
             AND name NOT LIKE 'sqlite_%'"""
    ):
        objects[str(row[0])].add(str(row[1]))
    tables = objects["table"]
    columns = {
        table: {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        for table in REQUIRED_TABLES & tables
    }
    metadata_version: str | None = None
    if REQUIRED_COLUMNS["metadata"] <= columns.get("metadata", set()):
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None:
            metadata_version = str(row[0])
    return {
        "schema_version": version,
        "metadata_schema_version": metadata_version,
        "tables": tables,
        "columns": columns,
        "indexes": objects["index"],
        "triggers": objects["trigger"],
    }


def ensure_supported_schema(connection: sqlite3.Connection) -> dict[str, Any]:
    details = schema_details(connection)
    version = details["schema_version"]
    if version != SCHEMA_VERSION:
        fail(
            "unsupported_schema",
            f"Database schema {version} is unsupported; this runtime supports schema {SCHEMA_VERSION}",
            EXIT_ENVIRONMENT,
            {"database_schema": version, "supported_schema": SCHEMA_VERSION},
        )
    missing_tables = sorted(REQUIRED_TABLES - details["tables"])
    if missing_tables:
        fail(
            "incomplete_schema",
            "Database schema is missing required tables",
            EXIT_ENVIRONMENT,
            {"missing_tables": missing_tables},
        )
    missing_columns = {
        table: sorted(required - details["columns"].get(table, set()))
        for table, required in REQUIRED_COLUMNS.items()
        if required - details["columns"].get(table, set())
    }
    missing_indexes = sorted(REQUIRED_INDEXES - details["indexes"])
    missing_triggers = sorted(REQUIRED_TRIGGERS - details["triggers"])
    if missing_columns or missing_indexes or missing_triggers:
        problems: dict[str, Any] = {}
        if missing_columns:
            problems["missing_columns"] = missing_columns
        if missing_indexes:
            problems["missing_indexes"] = missing_indexes
        if missing_triggers:
            problems["missing_triggers"] = missing_triggers
        fail(
            "incomplete_schema",
            "Database schema is missing required objects",
            EXIT_ENVIRONMENT,
            problems,
        )
    if details["metadata_schema_version"] != str(SCHEMA_VERSION):
        fail(
            "schema_mismatch",
            "Database metadata does not match PRAGMA user_version",
            EXIT_ENVIRONMENT,
            {
                "database_schema": version,
                "metadata_schema": details["metadata_schema_version"],
            },
        )
    return details


def connect(path: Path, require_initialized: bool = True) -> sqlite3.Connection:
    if require_initialized and not path.is_file():
        fail(
            "database_not_found",
            f"Coordination database not found: {path}",
            EXIT_NOT_FOUND,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = configured_busy_timeout_ms()
    connection = sqlite3.connect(path, timeout=timeout_ms / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
    if require_initialized:
        ensure_supported_schema(connection)
        connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        fail(
            "database_not_found",
            f"Coordination database not found: {path}",
            EXIT_NOT_FOUND,
        )
    timeout_ms = configured_busy_timeout_ms()
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro",
        timeout=timeout_ms / 1000,
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
    ensure_supported_schema(connection)
    return connection


def check_database_integrity(connection: sqlite3.Connection) -> dict[str, str]:
    integrity_results = [
        str(row[0]) for row in connection.execute("PRAGMA integrity_check")
    ]
    if integrity_results != ["ok"]:
        fail(
            "database_corrupt",
            "SQLite integrity check failed",
            EXIT_ENVIRONMENT,
            {"integrity_check": integrity_results[:10]},
        )
    foreign_key_violations = [
        dict(row) for row in connection.execute("PRAGMA foreign_key_check")
    ]
    if foreign_key_violations:
        fail(
            "foreign_key_violation",
            "SQLite foreign-key consistency check failed",
            EXIT_ENVIRONMENT,
            {
                "violation_count": len(foreign_key_violations),
                "violations": foreign_key_violations[:10],
            },
        )
    return {"integrity_check": "ok", "foreign_key_check": "ok"}


def check_coordination_invariants(connection: sqlite3.Connection) -> dict[str, str]:
    unclaimed = [
        str(row[0])
        for row in connection.execute(
            """SELECT t.id FROM tasks t
               WHERE t.status = 'in_progress'
                 AND NOT EXISTS (
                   SELECT 1 FROM task_claims c WHERE c.task_id = t.id
                 )
               ORDER BY t.id"""
        )
    ]
    invalid_claims = rows(
        connection.execute(
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
               ORDER BY c.task_id"""
        )
    )
    if unclaimed or invalid_claims:
        fail(
            "coordination_invariant_violation",
            "Coordination claim invariants failed",
            EXIT_ENVIRONMENT,
            {
                "unclaimed_in_progress_tasks": unclaimed,
                "invalid_active_claims": invalid_claims,
            },
        )
    return {"coordination_invariants": "ok"}


@contextmanager
def transaction(connection: sqlite3.Connection) -> Generator[None, None, None]:
    """Run a short write transaction that acquires SQLite's writer lock first."""
    connection.execute("BEGIN IMMEDIATE")
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
) -> None:
    stamp = now()
    if session_id:
        require_active_session(connection, session_id, actor)
        connection.execute(
            "UPDATE agent_sessions SET last_seen_at = ? WHERE id = ?",
            (stamp, session_id),
        )
    connection.execute(
        """INSERT INTO audit_log(
             actor, session_id, action, object_type, object_id, detail, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (actor, session_id, action, object_type, object_id, detail, stamp),
    )


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
        "SELECT agent_id, status FROM agent_sessions WHERE id = ?",
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
    return value
