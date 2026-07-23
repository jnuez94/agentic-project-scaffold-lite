"""Shared database, discovery, audit, and output infrastructure."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable


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
) -> None:
    connection.execute(
        "INSERT INTO audit_log(actor, action, object_type, object_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (actor, action, object_type, object_id, detail, now()),
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
