"""Health, summary, and inbox operations."""

from __future__ import annotations

from typing import Any

from coordination._service_core import ServiceCore
from coordination._service_validation import (
    MAX_SQLITE_INTEGER,
    _choices,
    _integer,
    _optional,
)
from coordination.core import (
    DEFAULT_LIST_LIMIT,
    MAX_AUDIT_CURSOR,
    MAX_LIST_LIMIT,
    MAX_STALE_DAYS,
    MAX_STALE_SESSION_MINUTES,
    identifier,
)
from coordination.entities import (
    inbox,
    reports,
)


class ReportOperations(ServiceCore):
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
