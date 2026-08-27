"""Database administration: init, doctor, audit, export, backup, restore."""

from __future__ import annotations

from typing import Any

from coordination._service_core import ServiceCore
from coordination._service_validation import (
    MAX_SQLITE_INTEGER,
    _boolean,
    _integer,
    _optional,
    _validate,
)
from coordination.core import (
    DEFAULT_LIST_LIMIT,
    MAX_AUDIT_CURSOR,
    MAX_LIST_LIMIT,
    SCHEMA_VERSION,
    connect,
    discover_db,
    ensure_supported_schema,
    expected_schema_definitions,
    identifier,
    path_argument,
    required_text,
    schema_details,
)
from coordination.entities import (
    audit,
    diagnostics,
    maintenance,
    reports,
)
from coordination.errors import (
    EXIT_ENVIRONMENT,
    CoordinationError,
)


class AdminOperations(ServiceCore):
    def init(self) -> dict[str, object]:
        schema_sql = self._schema_sql_provider()
        expected_schema_definitions()
        path = discover_db(self.db, for_init=True)
        connection = connect(path, require_initialized=False)
        details = schema_details(connection)
        if details["definitions"] or details["schema_version"] != 0:
            ensure_supported_schema(connection)
            journal_mode = str(
                connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if journal_mode != "wal":
                raise CoordinationError(
                    "database_configuration_error",
                    "Coordination database must use WAL journal mode",
                    EXIT_ENVIRONMENT,
                    {"journal_mode": journal_mode},
                )
            status = "ready"
        else:
            try:
                connection.executescript(schema_sql)
            except BaseException:
                connection.rollback()
                raise
            ensure_supported_schema(connection)
            status = "initialized"
        return {
            "database": str(path),
            "schema_version": SCHEMA_VERSION,
            "status": status,
        }

    def version(self) -> dict[str, object]:
        return diagnostics.version(self._args())

    def doctor(self) -> dict[str, object]:
        return diagnostics.doctor(self._args())

    def project_status(self) -> dict[str, object]:
        return self.doctor()

    def audit_list(
        self,
        *,
        actor: str | None = None,
        session_id: str | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        action: str | None = None,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            actor=_optional("actor", identifier, actor),
            session_id=_optional("session_id", identifier, session_id),
            object_type=_optional("object_type", required_text, object_type),
            object_id=_optional("object_id", required_text, object_id),
            action=_optional("action", required_text, action),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.list_audit(self._connect(), params)

    def audit_changes(
        self,
        *,
        audit_id: int | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            audit_id=(
                None
                if audit_id is None
                else _integer("audit_id", audit_id, 1, MAX_AUDIT_CURSOR)
            ),
            object_type=_optional("object_type", required_text, object_type),
            object_id=_optional("object_id", required_text, object_id),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.changes(self._connect(), params)

    def export(
        self,
        *,
        output: str | None = None,
        force: bool = False,
        actor: str | None = None,
    ) -> dict[str, object] | None:
        """Write a Markdown export, to `output` or to standard output.

        Unlike every other operation here, this one is not fully
        transport-neutral: without `output` it writes Markdown to stdout and
        returns None. That is correct for the CLI, whose stdout the caller
        owns and may redirect, and unusable for a transport that owns stdout
        itself -- on a stdio JSON-RPC connection it would corrupt the stream.
        A transport must therefore either omit this operation or require
        `output`. The shipped MCP tool set omits it, which
        `tests/mcp-security.py` enforces.
        """
        checked_output = _optional("output", path_argument, output)
        if checked_output is not None:
            self._require_contained(
                checked_output, label="Export output", must_exist=False
            )
        return reports.export(
            self._args(
                output=checked_output,
                force=_boolean("force", force),
                actor=_optional("actor", identifier, actor),
            )
        )

    def backup(
        self,
        *,
        output: str,
        force: bool = False,
        actor: str | None = None,
    ) -> dict[str, object]:
        checked_output = _validate("output", path_argument, output)
        self._require_contained(checked_output, label="Backup output", must_exist=False)
        return maintenance.backup(
            self._args(
                output=checked_output,
                force=_boolean("force", force),
                actor=_optional("actor", identifier, actor),
            )
        )

    def restore(
        self,
        *,
        input: str,
        actor: str,
        force: bool = False,
    ) -> dict[str, object]:
        checked_input = _validate("input", path_argument, input)
        self._require_contained(checked_input, label="Restore input", must_exist=True)
        return maintenance.restore(
            self._args(
                input=checked_input,
                actor=_validate("actor", identifier, actor),
                force=_boolean("force", force),
            )
        )
