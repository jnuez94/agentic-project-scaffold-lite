"""CLI version and database diagnostic commands."""

from __future__ import annotations

import argparse
import os
import stat

from coordination.core import (
    SCHEMA_VERSION,
    check_database_integrity,
    check_coordination_invariants,
    connect,
    discover_db,
    emit,
    read_transaction,
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
    if not path.is_file():
        connection = connect(path)
        connection.close()
        return
    database_mode = stat.S_IMODE(path.stat().st_mode)
    directory_mode = stat.S_IMODE(path.parent.stat().st_mode)
    database_writable = bool(database_mode & 0o222) and os.access(path, os.W_OK)
    directory_writable = bool(directory_mode & 0o222) and os.access(
        path.parent, os.W_OK
    )
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
    connection = connect(path)
    with read_transaction(connection):
        checks = check_database_integrity(connection)
        invariant_checks = check_coordination_invariants(connection)
        metadata_version = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
        synchronous_level = int(
            connection.execute("PRAGMA synchronous").fetchone()[0]
        )
        busy_timeout_ms = int(
            connection.execute("PRAGMA busy_timeout").fetchone()[0]
        )
        foreign_keys = bool(
            connection.execute("PRAGMA foreign_keys").fetchone()[0]
        )
        journal_mode = str(
            connection.execute("PRAGMA journal_mode").fetchone()[0]
        ).lower()
        schema_version = int(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )
    synchronous_names = {0: "off", 1: "normal", 2: "full", 3: "extra"}
    emit(
        {
            "healthy": True,
            "cli_version": runtime_version(),
            "database": str(path),
            "database_writable": database_writable,
            "directory_writable": directory_writable,
            "busy_timeout_ms": busy_timeout_ms,
            "foreign_keys": foreign_keys,
            **checks,
            **invariant_checks,
            "journal_mode": journal_mode,
            "metadata_schema_version": int(metadata_version),
            "schema_version": schema_version,
            "synchronous": synchronous_names.get(
                synchronous_level, str(synchronous_level)
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
