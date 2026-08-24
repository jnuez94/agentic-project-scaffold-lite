"""Artifact operations."""

from __future__ import annotations

from typing import Any

from coordination._service_core import ServiceCore
from coordination._service_validation import (
    MAX_SQLITE_INTEGER,
    _choice,
    _identifiers,
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
    artifacts,
    audit,
)
from coordination.entities.descriptors import timestamp


class ArtifactOperations(ServiceCore):
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

    def artifact_show(self, *, id: str) -> dict[str, Any]:
        params = self._params(id=_validate("id", identifier, id))
        return artifacts.show(self._connect(), params)

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
