"""Task creation, reads, assignment, and revision-guarded updates."""

from __future__ import annotations

from typing import Any

from coordination._service_core import ServiceCore
from coordination._service_validation import (
    MAX_SQLITE_INTEGER,
    _choices,
    _identifiers,
    _integer,
    _optional,
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
    tag_token,
)
from coordination.entities import (
    audit,
    tasks,
)
from coordination.entities.descriptors import timestamp


class TaskOperations(ServiceCore):
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
