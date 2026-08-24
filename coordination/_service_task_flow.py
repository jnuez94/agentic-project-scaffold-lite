"""Task claims, status transitions, and releases."""

from __future__ import annotations

from typing import Any

from coordination._service_core import ServiceCore
from coordination._service_validation import (
    MAX_SQLITE_INTEGER,
    _choice,
    _integer,
    _optional,
    _validate,
)
from coordination.core import (
    because_reference,
    identifier,
    optional_text,
)
from coordination.entities import (
    tasks,
)


class TaskFlowOperations(ServiceCore):
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
