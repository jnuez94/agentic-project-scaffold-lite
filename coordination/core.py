"""Shared database, discovery, audit, and output infrastructure."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable


LATEST_SCHEMA_VERSION = 2


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


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
    raise SystemExit("No SQLite coordination project found. Run from the project or pass --db PATH.")


def schema_path() -> Path:
    package = Path(__file__).resolve()
    candidates: list[Path] = []
    for ancestor in package.parents:
        candidates.extend((ancestor / "sqlite" / "schema.sql", ancestor / "assets" / "sqlite" / "schema.sql"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("SQLite schema not found in: " + ", ".join(str(candidate) for candidate in candidates))


def migration_path(version: int) -> Path:
    package = Path(__file__).resolve()
    filename = f"{version:04d}_" if version else ""
    for ancestor in package.parents:
        directory = ancestor / "sqlite" / "migrations"
        if directory.is_dir():
            matches = sorted(directory.glob(f"{filename}*.sql"))
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise SystemExit(f"Multiple migrations found for schema version {version}")
    raise SystemExit(f"SQLite migration not found for schema version {version}")


def connect(path: Path, require_initialized: bool = True) -> sqlite3.Connection:
    if require_initialized and not path.is_file():
        raise SystemExit(f"Coordination database not found: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
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
            raise SystemExit("A session-aware mutation requires an actor")
        session = require_row(
            connection,
            "SELECT agent_id, status FROM agent_sessions WHERE id = ?",
            (session_id,),
            f"agent session {session_id}",
        )
        if session["agent_id"] != actor:
            raise SystemExit(
                f"Session {session_id} belongs to {session['agent_id']}, not actor {actor}"
            )
        if session["status"] != "active":
            raise SystemExit(f"Agent session {session_id} is not active")
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
        raise SystemExit(f"Not found: {label}")
    return value
