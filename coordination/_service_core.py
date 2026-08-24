"""Connection discovery, parameter binding, dispatch, and receipts."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from contextlib import suppress
import inspect
import sqlite3
import time
from typing import Any, cast

from coordination._service_validation import (
    ACCOUNTABLE_PARAMETERS,
    OBJECT_PARAMETERS,
    OperationLog,
    OperationResult,
    _boolean,
    _identifier_parameter,
    _optional,
    _validate,
)
from coordination.core import (
    OperationScope,
    Params,
    canonical_schema_sql,
    connect,
    connection_scope,
    coordination_root_for_database,
    discover_db,
    identifier,
    now,
    operational_path,
    path_argument,
    validate_contained_path,
)
from coordination.errors import (
    EXIT_BUSY,
    EXIT_CONFLICT,
    EXIT_ENVIRONMENT,
    EXIT_INTERNAL,
    EXIT_USAGE,
    CoordinationError,
    fail,
)


class ServiceCore:
    def __init__(
        self,
        *,
        db: str | None = None,
        session: str | None = None,
        schema_sql_provider: Callable[[], str] = canonical_schema_sql,
        contain_paths: bool = False,
        transport: str = "cli",
        operation_log: OperationLog | None = None,
    ) -> None:
        self.db = _optional("db", path_argument, db)
        self.session = _optional("session", identifier, session)
        self._schema_sql_provider = schema_sql_provider
        self.transport = _validate("transport", identifier, transport)
        # The dispatch boundary is the observability boundary: it is the only
        # place that sees every operation, including the ones the database
        # never records -- refusals, conflicts, busy timeouts. The sink gets
        # one record per invocation. `last_receipt` is the caller-facing
        # summary of the most recent invocation.
        self._operation_log = operation_log
        self.last_receipt: dict[str, Any] = {}
        # Transport policy. The CLI reads and writes wherever its operator
        # points it. A transport whose caller is an agent acting on text it
        # did not write must not: with it, `backup --output ~/.zshrc --force`
        # is a prompt-injection away. Containment keeps every file path an
        # agent supplies inside the coordination root.
        self.contain_paths = _boolean("contain_paths", contain_paths)

    def _require_contained(
        self,
        value: str,
        *,
        label: str,
        must_exist: bool,
    ) -> None:
        if not self.contain_paths:
            return
        candidate = operational_path(value, label=label, must_exist=must_exist)
        root = coordination_root_for_database(discover_db(self.db))
        validate_contained_path(candidate, root, label=label)

    def _args(self, **values: object) -> Params:
        """Parameter bag for the file/system operations that own their I/O.

        `backup`, `restore`, `export`, and the diagnostics discover paths,
        stat files, and manage their own connections; they receive `db` and
        resolve it themselves. Row operations use `_connect` + `_params`.
        """
        return Params(db=self.db, session=self.session, **values)

    def _connect(self) -> sqlite3.Connection:
        """Open the configured database for one row operation.

        The service owns discovery and connection for row operations; entity
        functions receive the connection and a validated parameter bag, and
        never see a path or the CLI's namespace (#25). Release is owned by the
        dispatch boundary's connection scope.
        """
        return connect(discover_db(self.db))

    def _params(self, **values: object) -> Params:
        return Params(session=self.session, **values)

    def invoke(
        self,
        operation: str,
        parameters: Mapping[str, object],
    ) -> OperationResult:
        """Validate and execute one named service operation."""
        # The operation contract is derived from the final recombined
        # class, so it can only live in coordination.service; importing it
        # at call time avoids a circular import and costs one dict lookup.
        from coordination.service import SERVICE_OPERATIONS

        if operation.startswith("_") or operation not in SERVICE_OPERATIONS:
            fail(
                "invalid_arguments",
                f"Unknown coordination service operation: {operation}",
                EXIT_USAGE,
                {"operation": operation},
            )
        method = getattr(self, operation)
        try:
            bound = inspect.signature(method).bind(**dict(parameters))
        except TypeError as error:
            fail(
                "invalid_arguments",
                str(error),
                EXIT_USAGE,
                {"operation": operation},
            )
        started = time.monotonic()
        scope: OperationScope | None = None
        failure: CoordinationError | None = None
        try:
            # Every connection this operation opens is released here, so a
            # long-lived transport never accumulates advisory locks between
            # calls. Without it, restore cannot take its exclusive lock.
            with connection_scope() as scope:
                result = cast(OperationResult, method(*bound.args, **bound.kwargs))
        except CoordinationError as error:
            failure = error
            raise
        except sqlite3.IntegrityError as error:
            failure = CoordinationError(
                "constraint_violation",
                "Coordination constraint failed",
                EXIT_CONFLICT,
                {"database_error": str(error)},
            )
            raise failure from error
        except sqlite3.OperationalError as error:
            message = str(error)
            if "locked" in message.lower() or "busy" in message.lower():
                failure = CoordinationError("database_busy", message, EXIT_BUSY)
            else:
                failure = CoordinationError(
                    "database_error",
                    message,
                    EXIT_ENVIRONMENT,
                )
            raise failure from error
        except (sqlite3.DatabaseError, OSError) as error:
            failure = CoordinationError(
                "environment_error",
                str(error),
                EXIT_ENVIRONMENT,
            )
            raise failure from error
        except Exception as error:
            failure = CoordinationError(
                "internal_error",
                "Unexpected coordination service failure",
                EXIT_INTERNAL,
                {"error_type": type(error).__name__},
            )
            raise failure from error
        finally:
            self._finish(operation, parameters, scope, started, failure)
        return result

    def _finish(
        self,
        operation: str,
        parameters: Mapping[str, object],
        scope: OperationScope | None,
        started: float,
        failure: CoordinationError | None,
    ) -> None:
        audit_range = (
            [min(scope.audit_ids), max(scope.audit_ids)]
            if scope is not None and scope.audit_ids and failure is None
            else None
        )
        self.last_receipt = {
            "audit_range": audit_range,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "lock_wait_ms": int(scope.lock_wait_ms) if scope is not None else 0,
        }
        if self._operation_log is None:
            return
        record: dict[str, Any] = {
            "ts": now(),
            "transport": self.transport,
            "operation": operation,
            "actor": _identifier_parameter(parameters, ACCOUNTABLE_PARAMETERS),
            "session": self.session or _identifier_parameter(parameters, ("session",)),
            "object": _identifier_parameter(parameters, OBJECT_PARAMETERS),
            "outcome": "ok" if failure is None else "error",
            **self.last_receipt,
        }
        if failure is not None:
            record["code"] = failure.code
            record["exit_code"] = failure.exit_code
        # Logging must never change an operation's outcome.
        with suppress(Exception):
            self._operation_log(record)

    def invoke_cli(self, args: argparse.Namespace) -> OperationResult:
        """Dispatch a parsed CLI namespace through the shared service API."""
        command = str(args.command).replace("-", "_")
        subcommand = getattr(args, f"{command}_command", None)
        operation = (
            f"{command}_{str(subcommand).replace('-', '_')}"
            if subcommand is not None
            else command
        )
        method = getattr(self, operation, None)
        if method is None:
            fail(
                "invalid_arguments",
                f"Unknown coordination command operation: {operation}",
                EXIT_USAGE,
            )
        parameter_names = inspect.signature(method).parameters
        values = vars(args)
        parameters = {name: values[name] for name in parameter_names}
        return self.invoke(operation, parameters)
