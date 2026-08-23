"""Transport-neutral coordination service operations.

The CLI and optional MCP adapter both enter through ``CoordinationService``.
Entity modules retain the canonical SQL, transaction, revision, claim, and
audit behavior; this layer supplies typed operation boundaries, shared input
validation, database/session context, and stable exception translation.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
import functools
import inspect
import sqlite3
import time
from typing import Any, cast

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    IDENTIFIER_PATTERN,
    MAX_AUDIT_CURSOR,
    MAX_IDENTIFIER_ARRAY_ITEMS,
    MAX_LIST_LIMIT,
    MAX_STALE_DAYS,
    MAX_STALE_SECONDS,
    MAX_STALE_SESSION_MINUTES,
    MIN_STALE_SECONDS,
    SCHEMA_VERSION,
    OperationScope,
    Params,
    because_reference,
    canonical_schema_sql,
    connect,
    connection_scope,
    coordination_root_for_database,
    discover_db,
    ensure_supported_schema,
    expected_schema_definitions,
    identifier,
    now,
    operational_path,
    optional_text,
    path_argument,
    required_text,
    schema_details,
    tag_token,
    validate_contained_path,
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
    inbox,
    maintenance,
    messages,
    reports,
    reviews,
    sessions,
    tasks,
)
from coordination.entities.descriptors import timestamp
from coordination.errors import (
    EXIT_BUSY,
    EXIT_CONFLICT,
    EXIT_ENVIRONMENT,
    EXIT_INTERNAL,
    EXIT_USAGE,
    CoordinationError,
    fail,
)


OperationResult = dict[str, Any] | list[dict[str, Any]] | None
OperationLog = Callable[[dict[str, Any]], None]
# Parameters that name the accountable principal or the primary object of an
# operation. The operation log records identifiers only, never free text.
ACCOUNTABLE_PARAMETERS = ("actor", "agent", "reviewer", "owner", "sender", "raised_by")
OBJECT_PARAMETERS = ("id", "task", "input", "output")
MAX_SQLITE_INTEGER = 2_147_483_647


def _validate(
    field: str,
    validator: Callable[[str], Any],
    value: object,
) -> Any:
    if not isinstance(value, str):
        fail(
            "invalid_arguments",
            f"{field} must be a string",
            EXIT_USAGE,
            {"field": field},
        )
    try:
        return validator(value)
    except argparse.ArgumentTypeError as error:
        fail(
            "invalid_arguments",
            f"{field} {error}",
            EXIT_USAGE,
            {"field": field},
        )


def _optional(
    field: str,
    validator: Callable[[str], Any],
    value: object | None,
) -> Any | None:
    if value is None:
        return None
    return _validate(field, validator, value)


def _choice(
    field: str,
    value: object,
    choices: Sequence[str],
) -> str:
    if not isinstance(value, str) or value not in choices:
        fail(
            "invalid_arguments",
            f"{field} must be one of: {', '.join(choices)}",
            EXIT_USAGE,
            {"field": field, "choices": list(choices)},
        )
    return value


def _optional_choice(
    field: str,
    value: object | None,
    choices: Sequence[str],
) -> str | None:
    if value is None:
        return None
    return _choice(field, value, choices)


def _choices(
    field: str,
    value: object | None,
    choices: Sequence[str],
) -> list[str] | None:
    """Accept one choice or a list of choices; return a deduplicated list."""
    if value is None:
        return None
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        fail(
            "invalid_arguments",
            f"{field} must be one of {', '.join(choices)}, or an array of them",
            EXIT_USAGE,
            {"field": field, "choices": list(choices)},
        )
    selected: list[str] = []
    for item in items:
        checked = _choice(field, item, choices)
        if checked not in selected:
            selected.append(checked)
    return selected or None


def _strings(field: str, value: object | None) -> list[str] | None:
    """Accept a list of short strings (repeatable CLI flags, MCP arrays)."""
    if value is None:
        return None
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        fail(
            "invalid_arguments",
            f"{field} must be a string or an array of strings",
            EXIT_USAGE,
            {"field": field},
        )
    if len(items) > MAX_IDENTIFIER_ARRAY_ITEMS or any(
        len(item) > 4096 for item in items
    ):
        fail(
            "invalid_arguments",
            f"{field} has too many or too long entries",
            EXIT_USAGE,
            {"field": field, "maximum": MAX_IDENTIFIER_ARRAY_ITEMS},
        )
    return [item for item in items if item] or None


def _integer(
    field: str,
    value: object,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(
            "invalid_arguments",
            f"{field} must be an integer",
            EXIT_USAGE,
            {"field": field},
        )
    if not minimum <= value <= maximum:
        fail(
            "invalid_arguments",
            f"{field} must be between {minimum} and {maximum}",
            EXIT_USAGE,
            {"field": field, "minimum": minimum, "maximum": maximum},
        )
    return value


def _boolean(field: str, value: object) -> bool:
    if not isinstance(value, bool):
        fail(
            "invalid_arguments",
            f"{field} must be a boolean",
            EXIT_USAGE,
            {"field": field},
        )
    return value


def _identifiers(field: str, value: object) -> list[str]:
    if not isinstance(value, list):
        fail(
            "invalid_arguments",
            f"{field} must be an array of identifiers",
            EXIT_USAGE,
            {"field": field},
        )
    if len(value) > MAX_IDENTIFIER_ARRAY_ITEMS:
        fail(
            "invalid_arguments",
            (f"{field} must contain at most {MAX_IDENTIFIER_ARRAY_ITEMS} identifiers"),
            EXIT_USAGE,
            {
                "field": field,
                "maximum": MAX_IDENTIFIER_ARRAY_ITEMS,
                "actual": len(value),
            },
        )
    return [_validate(field, identifier, item) for item in value]


def _identifier_parameter(
    parameters: Mapping[str, object],
    names: Sequence[str],
) -> str | None:
    """Return the first named parameter that is a well-formed identifier.

    Used only by the operation log, which records principals and object ids
    and never free text; a value that is not identifier-shaped is omitted
    rather than logged.
    """
    for name in names:
        value = parameters.get(name)
        if isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value):
            return value
    return None


class CoordinationService:
    """Typed, transport-neutral entry point for coordination operations."""

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

    def agent_add(
        self,
        *,
        id: str,
        name: str,
        role: str,
        actor_type: str = "ai",
        responsibilities: str = "",
        goal: str = "",
        operating_style: str = "",
        decision_authority: str = "",
        review_authority: str = "",
        escalation_rules: str = "",
        unavailable_for: str = "",
        actor: str | None = None,
    ) -> dict[str, object]:
        params = self._params(
            id=_validate("id", identifier, id),
            name=_validate("name", required_text, name),
            role=_validate("role", required_text, role),
            actor_type=_choice(
                "actor_type",
                actor_type,
                ("ai", "human", "service"),
            ),
            responsibilities=_validate(
                "responsibilities", optional_text, responsibilities
            ),
            goal=_validate("goal", optional_text, goal),
            operating_style=_validate(
                "operating_style", optional_text, operating_style
            ),
            decision_authority=_validate(
                "decision_authority", optional_text, decision_authority
            ),
            review_authority=_validate(
                "review_authority", optional_text, review_authority
            ),
            escalation_rules=_validate(
                "escalation_rules", optional_text, escalation_rules
            ),
            unavailable_for=_validate(
                "unavailable_for", optional_text, unavailable_for
            ),
            actor=_optional("actor", identifier, actor),
        )
        return agents.add(self._connect(), params)

    def agent_list(
        self,
        *,
        all: bool = False,
        actor_type: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
        updated_since: str | None = None,
    ) -> list[dict[str, Any]]:
        params = self._params(
            all=_boolean("all", all),
            actor_type=_optional_choice(
                "actor_type",
                actor_type,
                ("ai", "human", "service"),
            ),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
            where=_strings("where", where),
            order_by=_strings("order_by", order_by),
            updated_since=_optional("updated_since", timestamp, updated_since),
        )
        return agents.list_agents(self._connect(), params)

    def agent_update(
        self,
        *,
        id: str,
        name: str | None = None,
        role: str | None = None,
        actor_type: str | None = None,
        status: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        params = self._params(
            id=_validate("id", identifier, id),
            name=_optional("name", required_text, name),
            role=_optional("role", required_text, role),
            actor_type=_optional_choice(
                "actor_type",
                actor_type,
                ("ai", "human", "service"),
            ),
            status=_optional_choice(
                "status",
                status,
                ("active", "inactive"),
            ),
            actor=_optional("actor", identifier, actor),
        )
        return agents.update(self._connect(), params)

    def session_start(
        self,
        *,
        id: str,
        agent: str,
        harness: str,
        model: str = "",
    ) -> dict[str, object]:
        params = self._params(
            id=_validate("id", identifier, id),
            agent=_validate("agent", identifier, agent),
            harness=_validate("harness", required_text, harness),
            model=_validate("model", optional_text, model),
        )
        return sessions.start(self._connect(), params)

    def session_list(
        self,
        *,
        agent: str | None = None,
        status: str | None = None,
        harness: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params = self._params(
            agent=_optional("agent", identifier, agent),
            status=_optional_choice(
                "status",
                status,
                sessions.SESSION_STATUSES,
            ),
            harness=_optional("harness", required_text, harness),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
            where=_strings("where", where),
            order_by=_strings("order_by", order_by),
        )
        return sessions.list_sessions(self._connect(), params)

    def session_heartbeat(self, *, id: str) -> dict[str, str]:
        params = self._params(id=_validate("id", identifier, id))
        return sessions.heartbeat(self._connect(), params)

    def session_end(self, *, id: str) -> dict[str, str]:
        params = self._params(id=_validate("id", identifier, id))
        return sessions.end(self._connect(), params)

    def session_recover(
        self,
        *,
        id: str,
        actor: str,
        reason: str,
        stale_after_seconds: int = 3600,
        force: bool = False,
    ) -> dict[str, object]:
        params = self._params(
            id=_validate("id", identifier, id),
            actor=_validate("actor", identifier, actor),
            reason=_validate("reason", required_text, reason),
            stale_after_seconds=_integer(
                "stale_after_seconds",
                stale_after_seconds,
                MIN_STALE_SECONDS,
                MAX_STALE_SECONDS,
            ),
            force=_boolean("force", force),
        )
        return sessions.recover(self._connect(), params)

    def session_sweep(
        self,
        *,
        actor: str,
        reason: str,
        stale_after_seconds: int = 3600,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> dict[str, object]:
        params = self._params(
            actor=_validate("actor", identifier, actor),
            reason=_validate("reason", required_text, reason),
            stale_after_seconds=_integer(
                "stale_after_seconds",
                stale_after_seconds,
                MIN_STALE_SECONDS,
                MAX_STALE_SECONDS,
            ),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
        )
        return sessions.sweep(self._connect(), params)

    def task_create(
        self,
        *,
        id: str,
        title: str,
        actor: str,
        description: str = "",
        priority: int = 3,
        tags: str = "",
        acceptance: str = "",
        next_steps: str = "",
        blocked_claims: str = "",
        assignee: list[str] | None = None,
    ) -> dict[str, Any]:
        params = self._params(
            id=_validate("id", identifier, id),
            title=_validate("title", required_text, title),
            actor=_validate("actor", identifier, actor),
            description=_validate("description", optional_text, description),
            priority=_integer("priority", priority, 1, 5),
            tags=_validate("tags", optional_text, tags),
            acceptance=_validate("acceptance", optional_text, acceptance),
            next_steps=_validate("next_steps", optional_text, next_steps),
            blocked_claims=_validate("blocked_claims", optional_text, blocked_claims),
            assignee=_identifiers(
                "assignee",
                [] if assignee is None else assignee,
            ),
        )
        return tasks.create(self._connect(), params)

    def task_list(
        self,
        *,
        status: str | list[str] | None = None,
        assignee: str | None = None,
        tag: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
        updated_since: str | None = None,
    ) -> list[dict[str, Any]]:
        params = self._params(
            status=_choices("status", status, tasks.STATUSES),
            assignee=_optional("assignee", identifier, assignee),
            tag=_optional("tag", tag_token, tag),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
            where=_strings("where", where),
            order_by=_strings("order_by", order_by),
            updated_since=_optional("updated_since", timestamp, updated_since),
        )
        return tasks.list_tasks(self._connect(), params)

    def task_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return tasks.show(self._connect(), params)

    def task_assign(
        self,
        *,
        id: str,
        actor: str,
        if_revision: int,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, Any]:
        params = self._params(
            id=_validate("id", identifier, id),
            actor=_validate("actor", identifier, actor),
            if_revision=_integer(
                "if_revision",
                if_revision,
                1,
                MAX_SQLITE_INTEGER,
            ),
            add=_identifiers("add", [] if add is None else add),
            remove=_identifiers("remove", [] if remove is None else remove),
        )
        return tasks.assign(self._connect(), params)

    def task_update(
        self,
        *,
        id: str,
        actor: str,
        if_revision: int,
        title: str | None = None,
        description: str | None = None,
        priority: int | None = None,
        tags: str | None = None,
        acceptance: str | None = None,
        next_steps: str | None = None,
        blocked_claims: str | None = None,
    ) -> dict[str, Any]:
        params = self._params(
            id=_validate("id", identifier, id),
            actor=_validate("actor", identifier, actor),
            if_revision=_integer(
                "if_revision",
                if_revision,
                1,
                MAX_SQLITE_INTEGER,
            ),
            title=_optional("title", required_text, title),
            description=_optional("description", optional_text, description),
            priority=(
                None if priority is None else _integer("priority", priority, 1, 5)
            ),
            tags=_optional("tags", optional_text, tags),
            acceptance=_optional("acceptance", optional_text, acceptance),
            next_steps=_optional("next_steps", optional_text, next_steps),
            blocked_claims=_optional(
                "blocked_claims",
                optional_text,
                blocked_claims,
            ),
        )
        return tasks.update(self._connect(), params)

    def task_claim(
        self,
        *,
        id: str,
        agent: str,
        if_revision: int,
    ) -> dict[str, Any]:
        params = self._params(
            id=_validate("id", identifier, id),
            agent=_validate("agent", identifier, agent),
            if_revision=_integer(
                "if_revision",
                if_revision,
                1,
                MAX_SQLITE_INTEGER,
            ),
        )
        return tasks.claim(self._connect(), params)

    def task_status(
        self,
        *,
        id: str,
        status: str,
        actor: str,
        if_revision: int,
        note: str = "",
        because: str | None = None,
    ) -> dict[str, Any]:
        params = self._params(
            id=_validate("id", identifier, id),
            status=_choice("status", status, tasks.STATUSES),
            actor=_validate("actor", identifier, actor),
            if_revision=_integer(
                "if_revision",
                if_revision,
                1,
                MAX_SQLITE_INTEGER,
            ),
            note=_validate("note", optional_text, note),
            require_owned_claim=False,
            because=_optional("because", because_reference, because),
        )
        return tasks.status(self._connect(), params)

    def task_release(
        self,
        *,
        id: str,
        status: str,
        actor: str,
        if_revision: int,
        note: str = "",
        because: str | None = None,
    ) -> dict[str, Any]:
        release_status = _choice(
            "status",
            status,
            ("todo", "review", "blocked"),
        )
        params = self._params(
            id=_validate("id", identifier, id),
            status=release_status,
            actor=_validate("actor", identifier, actor),
            if_revision=_integer(
                "if_revision",
                if_revision,
                1,
                MAX_SQLITE_INTEGER,
            ),
            note=_validate("note", optional_text, note),
            # Release is only an owned handback, never a plain transition.
            require_owned_claim=True,
            because=_optional("because", because_reference, because),
        )
        return tasks.status(self._connect(), params)

    def evidence_add(
        self,
        *,
        task: str,
        uri: str,
        actor: str,
        type: str = "artifact",
    ) -> dict[str, object]:
        params = self._params(
            task=_validate("task", identifier, task),
            uri=_validate("uri", required_text, uri),
            actor=_validate("actor", identifier, actor),
            type=_validate("type", required_text, type),
        )
        return evidence.add(self._connect(), params)

    def evidence_list(
        self,
        *,
        task: str,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
    ) -> list[dict[str, object]]:
        params = self._params(
            task=_validate("task", identifier, task),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
            where=_strings("where", where),
            order_by=_strings("order_by", order_by),
        )
        return evidence.list_evidence(self._connect(), params)

    def dependency_add(
        self,
        *,
        task: str,
        depends_on: str,
        actor: str,
        type: str = "blocks",
        rationale: str = "",
    ) -> dict[str, str]:
        params = self._params(
            task=_validate("task", identifier, task),
            depends_on=_validate("depends_on", identifier, depends_on),
            actor=_validate("actor", identifier, actor),
            type=_choice(
                "type",
                type,
                dependencies.DEPENDENCY_TYPES,
            ),
            rationale=_validate("rationale", optional_text, rationale),
        )
        return dependencies.add(self._connect(), params)

    def dependency_resolve(
        self,
        *,
        task: str,
        depends_on: str,
        actor: str,
        type: str = "blocks",
    ) -> dict[str, str]:
        params = self._params(
            task=_validate("task", identifier, task),
            depends_on=_validate("depends_on", identifier, depends_on),
            actor=_validate("actor", identifier, actor),
            type=_choice(
                "type",
                type,
                dependencies.DEPENDENCY_TYPES,
            ),
        )
        return dependencies.resolve(self._connect(), params)

    def review_add(
        self,
        *,
        id: str,
        reviewer: str,
        artifact: str,
        scope: str,
        decision: str,
        task: str | None = None,
        accepted_items: str = "",
        required_changes: str = "",
        risks: str = "",
        blocked_claims: str = "",
        follow_up_tasks: str = "",
    ) -> dict[str, str]:
        params = self._params(
            id=_validate("id", identifier, id),
            reviewer=_validate("reviewer", identifier, reviewer),
            artifact=_validate("artifact", required_text, artifact),
            scope=_validate("scope", required_text, scope),
            decision=_choice(
                "decision",
                decision,
                reviews.REVIEW_DECISIONS,
            ),
            task=_optional("task", identifier, task),
            accepted_items=_validate("accepted_items", optional_text, accepted_items),
            required_changes=_validate(
                "required_changes", optional_text, required_changes
            ),
            risks=_validate("risks", optional_text, risks),
            blocked_claims=_validate("blocked_claims", optional_text, blocked_claims),
            follow_up_tasks=_validate(
                "follow_up_tasks", optional_text, follow_up_tasks
            ),
        )
        return reviews.add(self._connect(), params)

    def review_list(
        self,
        *,
        task: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
    ) -> list[dict[str, object]]:
        params = self._params(
            task=_optional("task", identifier, task),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
            where=_strings("where", where),
            order_by=_strings("order_by", order_by),
        )
        return reviews.list_reviews(self._connect(), params)

    def decision_add(
        self,
        *,
        id: str,
        title: str,
        owner: str,
        context: str,
        decision: str,
        status: str = "proposed",
        options: str = "",
        implications: str = "",
        evidence: str = "",
        blocked_claims: str = "",
        review_required: str = "",
    ) -> dict[str, str]:
        params = self._params(
            id=_validate("id", identifier, id),
            title=_validate("title", required_text, title),
            owner=_validate("owner", identifier, owner),
            context=_validate("context", required_text, context),
            decision=_validate("decision", required_text, decision),
            status=_choice(
                "status",
                status,
                decisions.DECISION_STATUSES,
            ),
            options=_validate("options", optional_text, options),
            implications=_validate("implications", optional_text, implications),
            evidence=_validate("evidence", optional_text, evidence),
            blocked_claims=_validate("blocked_claims", optional_text, blocked_claims),
            review_required=_validate(
                "review_required", optional_text, review_required
            ),
        )
        return decisions.add(self._connect(), params)

    def decision_list(
        self,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
        updated_since: str | None = None,
    ) -> list[dict[str, object]]:
        params = self._params(
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
            where=_strings("where", where),
            order_by=_strings("order_by", order_by),
            updated_since=_optional("updated_since", timestamp, updated_since),
        )
        return decisions.list_decisions(self._connect(), params)

    def decision_status(
        self,
        *,
        id: str,
        status: str,
        actor: str,
        if_status: str | None = None,
        note: str = "",
        because: str | None = None,
    ) -> dict[str, str]:
        params = self._params(
            id=_validate("id", identifier, id),
            status=_choice("status", status, decisions.DECISION_STATUSES),
            actor=_validate("actor", identifier, actor),
            if_status=_optional_choice(
                "if_status", if_status, decisions.DECISION_STATUSES
            ),
            note=_validate("note", optional_text, note),
            because=_optional("because", because_reference, because),
        )
        return decisions.status(self._connect(), params)

    def message_send(
        self,
        *,
        id: str,
        sender: str,
        recipient: str,
        body: str,
        task: str | None = None,
        tags: str = "",
    ) -> dict[str, str]:
        params = self._params(
            id=_validate("id", identifier, id),
            sender=_validate("sender", identifier, sender),
            recipient=_validate("recipient", required_text, recipient),
            body=_validate("body", required_text, body),
            task=_optional("task", identifier, task),
            tags=_validate("tags", optional_text, tags),
        )
        return messages.send(self._connect(), params)

    def message_list(
        self,
        *,
        recipient: str | None = None,
        task: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params = self._params(
            recipient=_optional("recipient", required_text, recipient),
            task=_optional("task", identifier, task),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
            where=_strings("where", where),
            order_by=_strings("order_by", order_by),
        )
        return messages.list_messages(self._connect(), params)

    def message_redact(
        self,
        *,
        id: str,
        actor: str,
        reason: str,
    ) -> dict[str, str]:
        params = self._params(
            id=_validate("id", identifier, id),
            actor=_validate("actor", identifier, actor),
            reason=_validate("reason", required_text, reason),
        )
        return messages.redact(self._connect(), params)

    def artifact_add(
        self,
        *,
        id: str,
        uri: str,
        owner: str,
        type: str,
        status: str = "draft",
        usage_boundaries: str = "",
        task: list[str] | None = None,
        reviewer: list[str] | None = None,
    ) -> dict[str, str]:
        params = self._params(
            id=_validate("id", identifier, id),
            uri=_validate("uri", required_text, uri),
            owner=_validate("owner", identifier, owner),
            type=_validate("type", required_text, type),
            status=_choice(
                "status",
                status,
                artifacts.ARTIFACT_STATUSES,
            ),
            usage_boundaries=_validate(
                "usage_boundaries", optional_text, usage_boundaries
            ),
            task=_identifiers("task", [] if task is None else task),
            reviewer=_identifiers(
                "reviewer",
                [] if reviewer is None else reviewer,
            ),
        )
        return artifacts.add(self._connect(), params)

    def artifact_list(
        self,
        *,
        status: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
        updated_since: str | None = None,
    ) -> list[dict[str, Any]]:
        params = self._params(
            status=_optional_choice(
                "status",
                status,
                artifacts.ARTIFACT_STATUSES,
            ),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
            where=_strings("where", where),
            order_by=_strings("order_by", order_by),
            updated_since=_optional("updated_since", timestamp, updated_since),
        )
        return artifacts.list_artifacts(self._connect(), params)

    def artifact_status(
        self,
        *,
        id: str,
        status: str,
        actor: str,
        if_status: str | None = None,
        because: str | None = None,
    ) -> dict[str, str]:
        params = self._params(
            id=_validate("id", identifier, id),
            status=_choice("status", status, artifacts.ARTIFACT_STATUSES),
            actor=_validate("actor", identifier, actor),
            if_status=_optional_choice(
                "if_status", if_status, artifacts.ARTIFACT_STATUSES
            ),
            because=_optional("because", because_reference, because),
        )
        return artifacts.status(self._connect(), params)

    def artifact_update(
        self,
        *,
        id: str,
        actor: str,
        uri: str | None = None,
        type: str | None = None,
        usage_boundaries: str | None = None,
        if_status: str | None = None,
    ) -> dict[str, Any]:
        params = self._params(
            id=_validate("id", identifier, id),
            actor=_validate("actor", identifier, actor),
            uri=_optional("uri", required_text, uri),
            type=_optional("type", required_text, type),
            usage_boundaries=_optional(
                "usage_boundaries", optional_text, usage_boundaries
            ),
            if_status=_optional_choice(
                "if_status", if_status, artifacts.ARTIFACT_STATUSES
            ),
        )
        return artifacts.update(self._connect(), params)

    def escalation_add(
        self,
        *,
        id: str,
        raised_by: str,
        owner: str,
        issue: str,
        requested_decision: str,
        related_tasks: str = "",
        needed_by: str | None = None,
    ) -> dict[str, str]:
        params = self._params(
            id=_validate("id", identifier, id),
            raised_by=_validate("raised_by", identifier, raised_by),
            owner=_validate("owner", required_text, owner),
            issue=_validate("issue", required_text, issue),
            requested_decision=_validate(
                "requested_decision",
                required_text,
                requested_decision,
            ),
            related_tasks=_validate(
                "related_tasks",
                optional_text,
                related_tasks,
            ),
            needed_by=_optional("needed_by", required_text, needed_by),
        )
        return escalations.add(self._connect(), params)

    def escalation_list(
        self,
        *,
        status: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params = self._params(
            status=_optional_choice(
                "status",
                status,
                escalations.ESCALATION_STATUSES,
            ),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
            where=_strings("where", where),
            order_by=_strings("order_by", order_by),
        )
        return escalations.list_escalations(self._connect(), params)

    def escalation_resolve(
        self,
        *,
        id: str,
        resolution: str,
        actor: str,
        status: str = "resolved",
        follow_up_tasks: str = "",
        if_status: str | None = None,
        because: str | None = None,
    ) -> dict[str, str]:
        params = self._params(
            id=_validate("id", identifier, id),
            resolution=_validate("resolution", required_text, resolution),
            actor=_validate("actor", identifier, actor),
            status=_choice(
                "status",
                status,
                ("resolved", "closed_no_action"),
            ),
            follow_up_tasks=_validate(
                "follow_up_tasks",
                optional_text,
                follow_up_tasks,
            ),
            if_status=_optional_choice(
                "if_status", if_status, escalations.ESCALATION_STATUSES
            ),
            because=_optional("because", because_reference, because),
        )
        return escalations.resolve(self._connect(), params)

    def health(
        self,
        *,
        stale_days: int = 7,
        stale_session_minutes: int = 60,
        limit: int = DEFAULT_LIST_LIMIT,
        section: str | list[str] | None = None,
    ) -> dict[str, object]:
        params = self._params(
            stale_days=_integer(
                "stale_days",
                stale_days,
                0,
                MAX_STALE_DAYS,
            ),
            stale_session_minutes=_integer(
                "stale_session_minutes",
                stale_session_minutes,
                0,
                MAX_STALE_SESSION_MINUTES,
            ),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            section=_choices("section", section, reports.HEALTH_SECTIONS),
        )
        return reports.health(self._connect(), params)

    def summary(
        self,
        *,
        section: str | list[str] | None = None,
    ) -> dict[str, object]:
        params = self._params(
            section=_choices("section", section, reports.SUMMARY_SECTIONS),
        )
        return reports.summary(self._connect(), params)

    def task_history(
        self,
        *,
        id: str,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            object_type="task",
            id=_validate("id", identifier, id),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.history(self._connect(), params)

    def agent_history(
        self,
        *,
        id: str,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            object_type="agent",
            id=_validate("id", identifier, id),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.history(self._connect(), params)

    def session_history(
        self,
        *,
        id: str,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            object_type="session",
            id=_validate("id", identifier, id),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.history(self._connect(), params)

    def artifact_history(
        self,
        *,
        id: str,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            object_type="artifact",
            id=_validate("id", identifier, id),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.history(self._connect(), params)

    def decision_history(
        self,
        *,
        id: str,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            object_type="decision",
            id=_validate("id", identifier, id),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.history(self._connect(), params)

    def message_history(
        self,
        *,
        id: str,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            object_type="message",
            id=_validate("id", identifier, id),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.history(self._connect(), params)

    def review_history(
        self,
        *,
        id: str,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            object_type="review",
            id=_validate("id", identifier, id),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.history(self._connect(), params)

    def escalation_history(
        self,
        *,
        id: str,
        since: int = 0,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = self._params(
            object_type="escalation",
            id=_validate("id", identifier, id),
            since=_integer("since", since, 0, MAX_AUDIT_CURSOR),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return audit.history(self._connect(), params)

    def inbox_list(
        self,
        *,
        agent: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        params = self._params(
            agent=_optional("agent", identifier, agent),
            limit=_integer("limit", limit, 1, MAX_LIST_LIMIT),
            offset=_integer("offset", offset, 0, MAX_SQLITE_INTEGER),
        )
        return inbox.list_inbox(self._connect(), params)

    def inbox_mark_read(
        self,
        *,
        cursor: int,
        agent: str | None = None,
    ) -> dict[str, Any]:
        params = self._params(
            agent=_optional("agent", identifier, agent),
            cursor=_integer("cursor", cursor, 0, MAX_AUDIT_CURSOR),
        )
        return inbox.mark_read(self._connect(), params)

    def agent_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return agents.show(self._connect(), params)

    def session_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return sessions.show(self._connect(), params)

    def artifact_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return artifacts.show(self._connect(), params)

    def decision_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return decisions.show(self._connect(), params)

    def message_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return messages.show(self._connect(), params)

    def review_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return reviews.show(self._connect(), params)

    def escalation_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return escalations.show(self._connect(), params)

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


SERVICE_OPERATIONS = frozenset(
    name
    for name, value in vars(CoordinationService).items()
    if callable(value)
    and not name.startswith("_")
    and name not in {"invoke", "invoke_cli"}
)


def _release_connections_after(method: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with connection_scope():
            return method(*args, **kwargs)

    return wrapper


# Each operation releases its own connections and advisory locks, whether it was
# reached through `invoke` or called directly as library API. Scopes nest, so
# the redundant scope in `invoke` costs nothing. Without this a long-lived
# caller accumulates shared locks on the database lock file until `restore`
# cannot take its exclusive lock -- and neither can any other process.
for _operation in SERVICE_OPERATIONS:
    setattr(
        CoordinationService,
        _operation,
        _release_connections_after(getattr(CoordinationService, _operation)),
    )
del _operation
