"""Argument types shared by the MCP tool modules."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from coordination.core import (
    MAX_IDENTIFIER_ARRAY_ITEMS,
)


ActorType = Literal["ai", "human", "service"]

AgentStatus = Literal["active", "inactive"]

TaskStatus = Literal["todo", "in_progress", "review", "blocked", "done"]

ReleaseStatus = Literal["todo", "review", "blocked"]

ReviewDecision = Literal[
    "accepted",
    "conditionally_accepted",
    "changes_requested",
    "rejected",
]

DecisionStatus = Literal["proposed", "accepted", "superseded", "rejected"]

DependencyType = Literal[
    "blocks",
    "informs",
    "review_required",
    "evidence_required",
]

ArtifactStatus = Literal["draft", "review", "accepted", "superseded"]

EscalationStatus = Literal["open", "in_review", "resolved", "closed_no_action"]

EscalationResolution = Literal["resolved", "closed_no_action"]

HealthSection = Literal[
    "unowned_tasks",
    "stale_tasks",
    "stale_sessions",
    "unclaimed_in_progress_tasks",
    "invalid_active_claims",
    "active_blockers",
    "done_without_evidence",
    "open_escalations",
    "tasks_awaiting_review",
]

SummarySection = Literal[
    "totals", "task_status", "task_priority", "workload", "time_in_state"
]

ShowObjectType = Literal[
    "agent", "session", "artifact", "decision", "message", "review", "escalation"
]

HistoryObjectType = Literal[
    "task",
    "agent",
    "session",
    "artifact",
    "decision",
    "message",
    "review",
    "escalation",
]

IdentifierArray = Annotated[
    list[str],
    Field(max_length=MAX_IDENTIFIER_ARRAY_ITEMS),
]
