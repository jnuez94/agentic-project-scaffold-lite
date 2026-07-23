"""Top-level command parser and entity dispatcher."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import sys

from coordination.core import (
    LATEST_SCHEMA_VERSION,
    connect,
    discover_db,
    emit,
    migration_path,
    schema_path,
)
from coordination.entities import (
    agents,
    artifacts,
    decisions,
    dependencies,
    escalations,
    evidence,
    messages,
    reports,
    reviews,
    sessions,
    tasks,
)


def backup_before_migration(
    connection: sqlite3.Connection,
    database: Path,
    schema_version: int,
) -> Path:
    backup_dir = database.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_dir / (
        f"{database.stem}-pre-schema-v{schema_version}-{timestamp}.sqlite3"
    )
    backup_connection = sqlite3.connect(destination)
    try:
        connection.backup(backup_connection)
    finally:
        backup_connection.close()
    return destination


def command_init(args: argparse.Namespace) -> None:
    path = discover_db(args.db, for_init=True)
    connection = connect(path, require_initialized=False)
    current_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if current_version > LATEST_SCHEMA_VERSION:
        raise SystemExit(
            f"Database schema {current_version} is newer than supported "
            f"schema {LATEST_SCHEMA_VERSION}"
        )
    migration_backup: Path | None = None
    if current_version == 0:
        connection.executescript(schema_path().read_text(encoding="utf-8"))
        status = "initialized"
    else:
        if current_version < LATEST_SCHEMA_VERSION:
            migration_backup = backup_before_migration(connection, path, current_version)
        for version in range(current_version + 1, LATEST_SCHEMA_VERSION + 1):
            connection.executescript(migration_path(version).read_text(encoding="utf-8"))
        connection.executescript(schema_path().read_text(encoding="utf-8"))
        status = "migrated" if current_version < LATEST_SCHEMA_VERSION else "ready"
    final_version = connection.execute("PRAGMA user_version").fetchone()[0]
    result = {"database": str(path), "schema_version": final_version, "status": status}
    if migration_backup:
        result["backup"] = str(migration_backup)
    emit(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coordination",
        description="Local multi-agent coordination backed by SQLite",
    )
    parser.add_argument("--db", help="Path to coordination.sqlite3; otherwise discover the nearest project")
    parser.add_argument(
        "--session",
        default=os.environ.get("COORDINATION_SESSION"),
        help="Active agent session ID used for audit attribution; defaults to COORDINATION_SESSION",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Initialize the database")
    init.set_defaults(func=command_init)

    for entity in (
        agents,
        sessions,
        tasks,
        evidence,
        dependencies,
        reviews,
        decisions,
        messages,
        artifacts,
        escalations,
        reports,
    ):
        entity.register(commands)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except sqlite3.IntegrityError as error:
        print(f"Coordination constraint failed: {error}", file=sys.stderr)
        return 2
    return 0
