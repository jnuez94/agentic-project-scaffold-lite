"""Evidence, dependency, and review operations."""

from __future__ import annotations

from typing import Any

from coordination._service_core import ServiceCore
from coordination._service_validation import (
    MAX_SQLITE_INTEGER,
    _choice,
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
)
from coordination.entities import (
    audit,
    dependencies,
    evidence,
    reviews,
)


class ReviewOperations(ServiceCore):
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

    def review_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return reviews.show(self._connect(), params)

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
