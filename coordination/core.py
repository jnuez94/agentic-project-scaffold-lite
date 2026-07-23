"""Shared database, discovery, audit, and output infrastructure."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from coordination.errors import (
    EXIT_CONFLICT,
    EXIT_ENVIRONMENT,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    fail,
)


SCHEMA_VERSION = 1
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
            "created_by",
            "created_at",
            "updated_at",
        }
    ),
    "task_assignees": frozenset({"task_id", "agent_id", "assigned_at"}),
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
        "idx_evidence_task",
        "idx_reviews_task",
        "idx_messages_recipient",
        "idx_escalations_status",
        "idx_audit_session",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "task_insert_done_requires_evidence",
        "task_update_done_requires_evidence",
    }
)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if require_initialized:
        ensure_supported_schema(connection)
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


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
