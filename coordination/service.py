"""Transport-neutral coordination services over the entity modules.

This module is the stable import surface: `CoordinationService` recombines
the operation mixin modules, each within the 250-line file budget, and every
operation still validates its parameters before any database discovery.
"""

from __future__ import annotations

from collections.abc import Callable
import functools
from typing import Any

from coordination.core import connection_scope


# fmt: off
# isort: off
from coordination._service_validation import (
    _boolean as _boolean, _choice as _choice, _choices as _choices,
    _identifier_parameter as _identifier_parameter, _identifiers as _identifiers,
    _integer as _integer, _optional as _optional,
    _optional_choice as _optional_choice, _strings as _strings,
    _validate as _validate, ACCOUNTABLE_PARAMETERS as ACCOUNTABLE_PARAMETERS,
    MAX_SQLITE_INTEGER as MAX_SQLITE_INTEGER,
    OBJECT_PARAMETERS as OBJECT_PARAMETERS, OperationLog as OperationLog,
    OperationResult as OperationResult,
)
from coordination._service_core import ServiceCore as ServiceCore
from coordination._service_admin import AdminOperations as AdminOperations
from coordination._service_agents import AgentOperations as AgentOperations
from coordination._service_sessions import SessionOperations as SessionOperations
from coordination._service_tasks import TaskOperations as TaskOperations
from coordination._service_task_flow import TaskFlowOperations as TaskFlowOperations
from coordination._service_reviews import ReviewOperations as ReviewOperations
from coordination._service_messaging import MessagingOperations as MessagingOperations
from coordination._service_artifacts import ArtifactOperations as ArtifactOperations
from coordination._service_escalations import (
    EscalationOperations as EscalationOperations,
)
from coordination._service_reports import ReportOperations as ReportOperations
# isort: on
# fmt: on


class CoordinationService(
    AdminOperations,
    AgentOperations,
    SessionOperations,
    TaskOperations,
    TaskFlowOperations,
    ReviewOperations,
    MessagingOperations,
    ArtifactOperations,
    EscalationOperations,
    ReportOperations,
    ServiceCore,
):
    """The complete coordination service; see the mixin modules."""


SERVICE_OPERATIONS = frozenset(
    name
    for klass in CoordinationService.__mro__
    for name, value in vars(klass).items()
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


# Each operation releases its own connections and advisory locks, whether it
# was reached through `invoke` or called directly as library API. Scopes nest,
# so the redundant scope in `invoke` costs nothing. Without this a long-lived
# caller accumulates shared locks on the database lock file until `restore`
# cannot take its exclusive lock -- and neither can any other process.
for _operation in SERVICE_OPERATIONS:
    setattr(
        CoordinationService,
        _operation,
        _release_connections_after(getattr(CoordinationService, _operation)),
    )
del _operation
