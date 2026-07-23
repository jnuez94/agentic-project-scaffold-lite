"""CLI version and database diagnostic commands."""

from __future__ import annotations

import argparse
import os

from coordination.core import (
    SCHEMA_VERSION,
    connect,
    discover_db,
    emit,
    runtime_version,
)
from coordination.errors import EXIT_ENVIRONMENT, fail


def version(args: argparse.Namespace) -> None:
    emit(
        {
            "cli_version": runtime_version(),
            "schema_version": SCHEMA_VERSION,
        }
    )


def doctor(args: argparse.Namespace) -> None:
    path = discover_db(args.db)
    connection = connect(path)
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity != "ok":
        fail(
            "database_corrupt",
            "SQLite integrity check failed",
            EXIT_ENVIRONMENT,
            {"integrity_check": integrity},
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
    database_writable = os.access(path, os.W_OK)
    directory_writable = os.access(path.parent, os.W_OK)
    if not database_writable or not directory_writable:
        fail(
            "database_not_writable",
            "Coordination database and its directory must be writable",
            EXIT_ENVIRONMENT,
            {
                "database_writable": database_writable,
                "directory_writable": directory_writable,
            },
        )
    metadata_version = connection.execute(
        "SELECT value FROM metadata WHERE key = 'schema_version'"
    ).fetchone()[0]
    emit(
        {
            "healthy": True,
            "cli_version": runtime_version(),
            "database": str(path),
            "database_writable": database_writable,
            "directory_writable": directory_writable,
            "busy_timeout_ms": int(
                connection.execute("PRAGMA busy_timeout").fetchone()[0]
            ),
            "foreign_keys": bool(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
            "foreign_key_check": "ok",
            "integrity_check": integrity,
            "journal_mode": str(
                connection.execute("PRAGMA journal_mode").fetchone()[0]
            ).lower(),
            "metadata_schema_version": int(metadata_version),
            "schema_version": int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            ),
        }
    )


def register(commands: argparse._SubParsersAction) -> None:
    version_parser = commands.add_parser(
        "version",
        help="Report CLI and supported schema versions",
    )
    version_parser.set_defaults(func=version)

    doctor_parser = commands.add_parser(
        "doctor",
        help="Validate the discovered SQLite coordination installation",
    )
    doctor_parser.set_defaults(func=doctor)
