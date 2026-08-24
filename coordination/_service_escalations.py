"""Escalation operations."""

from __future__ import annotations

from typing import Any

from coordination._service_core import ServiceCore
from coordination._service_validation import (
    MAX_SQLITE_INTEGER,
    _choice,
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
    because_reference,
    identifier,
    optional_text,
    required_text,
)
from coordination.entities import (
    audit,
    escalations,
)


class EscalationOperations(ServiceCore):
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

    def escalation_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return escalations.show(self._connect(), params)

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
