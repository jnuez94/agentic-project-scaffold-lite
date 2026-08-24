"""Agent registry operations."""

from __future__ import annotations

from typing import Any

from coordination._service_core import ServiceCore
from coordination._service_validation import (
    MAX_SQLITE_INTEGER,
    _boolean,
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
    identifier,
    optional_text,
    required_text,
)
from coordination.entities import (
    agents,
    audit,
)
from coordination.entities.descriptors import timestamp


class AgentOperations(ServiceCore):
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

    def agent_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return agents.show(self._connect(), params)

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
