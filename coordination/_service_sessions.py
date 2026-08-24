"""Execution-session lifecycle and recovery operations."""

from __future__ import annotations

from typing import Any

from coordination._service_core import ServiceCore
from coordination._service_validation import (
    MAX_SQLITE_INTEGER,
    _boolean,
    _integer,
    _optional,
    _optional_choice,
    _strings,
    _validate,
)
from coordination.core import (
    DEFAULT_LIST_LIMIT,
    MAX_AUDIT_CURSOR,
    MAX_LIST_LIMIT,
    MAX_STALE_SECONDS,
    MIN_STALE_SECONDS,
    identifier,
    optional_text,
    required_text,
)
from coordination.entities import (
    audit,
    sessions,
)


class SessionOperations(ServiceCore):
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

    def session_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return sessions.show(self._connect(), params)

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
