"""Decision and message operations."""

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
    decisions,
    messages,
)
from coordination.entities.descriptors import timestamp


class MessagingOperations(ServiceCore):
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

    def decision_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return decisions.show(self._connect(), params)

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

    def message_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return messages.show(self._connect(), params)

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
