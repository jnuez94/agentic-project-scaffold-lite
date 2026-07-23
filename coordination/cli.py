"""Top-level command parser and entity dispatcher."""

from __future__ import annotations

import argparse
import os
import sqlite3

from coordination.core import (
    SCHEMA_VERSION,
    connect,
    discover_db,
    emit,
    ensure_supported_schema,
    schema_details,
    schema_path,
)
from coordination.errors import (
    EXIT_BUSY,
    EXIT_CONFLICT,
    EXIT_ENVIRONMENT,
    EXIT_INTERNAL,
    EXIT_USAGE,
    CoordinationError,
    emit_error,
)
from coordination.entities import (
    agents,
    artifacts,
    decisions,
    dependencies,
    diagnostics,
    escalations,
    evidence,
    messages,
    reports,
    reviews,
    sessions,
    tasks,
)


def command_init(args: argparse.Namespace) -> None:
    path = discover_db(args.db, for_init=True)
    connection = connect(path, require_initialized=False)
    details = schema_details(connection)
    if details["tables"] or details["schema_version"] != 0:
        ensure_supported_schema(connection)
        connection.execute("PRAGMA journal_mode = WAL")
        status = "ready"
    else:
        with connection:
            connection.executescript(schema_path().read_text(encoding="utf-8"))
        ensure_supported_schema(connection)
        status = "initialized"
    emit({"database": str(path), "schema_version": SCHEMA_VERSION, "status": status})


class CoordinationArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CoordinationError("invalid_arguments", message, EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = CoordinationArgumentParser(
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
        diagnostics,
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
    try:
        parser = build_parser()
        args = parser.parse_args()
        args.func(args)
    except CoordinationError as error:
        emit_error(error)
        return error.exit_code
    except sqlite3.IntegrityError as error:
        emit_error(
            CoordinationError(
                "constraint_violation",
                "Coordination constraint failed",
                EXIT_CONFLICT,
                {"database_error": str(error)},
            )
        )
        return EXIT_CONFLICT
    except sqlite3.OperationalError as error:
        message = str(error)
        if "locked" in message.lower() or "busy" in message.lower():
            value = CoordinationError("database_busy", message, EXIT_BUSY)
        else:
            value = CoordinationError("database_error", message, EXIT_ENVIRONMENT)
        emit_error(value)
        return value.exit_code
    except (sqlite3.DatabaseError, OSError) as error:
        emit_error(
            CoordinationError(
                "environment_error",
                str(error),
                EXIT_ENVIRONMENT,
            )
        )
        return EXIT_ENVIRONMENT
    except Exception as error:  # pragma: no cover - final CLI safety boundary
        emit_error(
            CoordinationError(
                "internal_error",
                "Unexpected coordination CLI failure",
                EXIT_INTERNAL,
                {"error_type": type(error).__name__},
            )
        )
        return EXIT_INTERNAL
    return 0
