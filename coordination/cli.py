"""Top-level command parser and entity dispatcher."""

from __future__ import annotations

import argparse
import os
import signal
import sqlite3
from typing import Any, NoReturn

from coordination.core import (
    canonical_schema_sql,
    emit,
    identifier,
    path_argument,
)
from coordination.entities import (
    agents,
    artifacts,
    audit,
    decisions,
    dependencies,
    diagnostics,
    escalations,
    evidence,
    maintenance,
    messages,
    reports,
    reviews,
    sessions,
    tasks,
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
from coordination.service import CoordinationService


class CoordinationArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> NoReturn:
        raise CoordinationError("invalid_arguments", message, EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = CoordinationArgumentParser(
        prog="coordination",
        description="Local multi-agent coordination backed by SQLite",
    )
    parser.add_argument(
        "--db",
        type=path_argument,
        help="Path to coordination.sqlite3; otherwise discover the nearest project",
    )
    parser.add_argument(
        "--session",
        default=os.environ.get("COORDINATION_SESSION"),
        type=identifier,
        help=(
            "Active agent session ID used for audit attribution; "
            "defaults to COORDINATION_SESSION"
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Initialize the database")

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
        maintenance,
        reports,
        audit,
    ):
        entity.register(commands)
    return parser


def _interrupt(signum: int, _frame: object) -> None:
    raise CoordinationError(
        "operation_interrupted",
        "Coordination operation was interrupted",
        EXIT_ENVIRONMENT,
        {"signal": signum},
    )


def main() -> int:
    for signal_name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), _interrupt)
    try:
        parser = build_parser()
        args = parser.parse_args()
        result = CoordinationService(
            db=args.db,
            session=args.session,
            schema_sql_provider=canonical_schema_sql,
        ).invoke_cli(args)
        if result is not None:
            emit(result)
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
    except KeyboardInterrupt:
        emit_error(
            CoordinationError(
                "operation_interrupted",
                "Coordination operation was interrupted",
                EXIT_ENVIRONMENT,
            )
        )
        return EXIT_ENVIRONMENT
    # The outermost boundary must map anything at all to a stable JSON envelope.
    except Exception as error:  # noqa: BLE001  # pragma: no cover
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
