"""The canonical schema-version-2 object inventory."""

from __future__ import annotations


REQUIRED_COLUMNS = {
    "metadata": frozenset({"key", "value"}),
    "agents": frozenset(
        {
            "id",
            "name",
            "role",
            "actor_type",
            "status",
            "responsibilities",
            "goal",
            "operating_style",
            "decision_authority",
            "review_authority",
            "escalation_rules",
            "unavailable_for",
            "created_at",
            "updated_at",
        }
    ),
    "agent_sessions": frozenset(
        {
            "id",
            "agent_id",
            "harness",
            "model",
            "status",
            "started_at",
            "last_seen_at",
            "ended_at",
        }
    ),
    "tasks": frozenset(
        {
            "id",
            "title",
            "description",
            "status",
            "priority",
            "tags",
            "acceptance_criteria",
            "next_steps",
            "blocked_claims",
            "notes",
            "revision",
            "created_by",
            "created_at",
            "updated_at",
        }
    ),
    "task_assignees": frozenset({"task_id", "agent_id", "assigned_at"}),
    "change_log": frozenset(
        {
            "id",
            "audit_id",
            "object_type",
            "object_id",
            "field",
            "old_value",
            "new_value",
            "created_at",
        }
    ),
    "task_claims": frozenset({"task_id", "agent_id", "session_id", "claimed_at"}),
    "task_dependencies": frozenset(
        {
            "task_id",
            "depends_on_task_id",
            "dependency_type",
            "status",
            "rationale",
            "created_at",
        }
    ),
    "task_evidence": frozenset(
        {"id", "task_id", "uri", "evidence_type", "added_by", "created_at"}
    ),
    "messages": frozenset(
        {"id", "sender_id", "recipient", "task_id", "body", "tags", "created_at"}
    ),
    "reviews": frozenset(
        {
            "id",
            "task_id",
            "reviewer_id",
            "artifact_uri",
            "scope",
            "decision",
            "accepted_items",
            "required_changes",
            "remaining_risks",
            "blocked_claims",
            "follow_up_tasks",
            "created_at",
        }
    ),
    "decisions": frozenset(
        {
            "id",
            "title",
            "owner_id",
            "status",
            "context",
            "decision",
            "options_considered",
            "implications",
            "evidence",
            "blocked_claims",
            "review_required",
            "created_at",
            "updated_at",
        }
    ),
    "artifacts": frozenset(
        {
            "id",
            "uri",
            "owner_id",
            "type",
            "status",
            "usage_boundaries",
            "created_at",
            "updated_at",
        }
    ),
    "artifact_tasks": frozenset({"artifact_id", "task_id"}),
    "artifact_reviewers": frozenset({"artifact_id", "reviewer_id"}),
    "escalations": frozenset(
        {
            "id",
            "raised_by",
            "owner",
            "status",
            "related_tasks",
            "needed_by",
            "issue",
            "requested_decision",
            "resolution",
            "follow_up_tasks",
            "created_at",
            "updated_at",
        }
    ),
    "audit_log": frozenset(
        {
            "id",
            "actor",
            "session_id",
            "action",
            "object_type",
            "object_id",
            "detail",
            "created_at",
        }
    ),
}

REQUIRED_TABLES = frozenset(REQUIRED_COLUMNS)

REQUIRED_INDEXES = frozenset(
    {
        "idx_tasks_status_priority",
        "idx_agent_sessions_agent_status",
        "idx_task_assignees_agent",
        "idx_task_claims_agent",
        "idx_evidence_task",
        "idx_reviews_task",
        "idx_messages_recipient",
        "idx_escalations_status",
        "idx_audit_session",
        "idx_change_log_audit",
        "idx_change_log_object",
    }
)

REQUIRED_TRIGGERS = frozenset(
    {
        "audit_log_append_only_delete",
        "audit_log_redaction_only_update",
        "change_log_append_only_delete",
        "change_log_redaction_only_update",
        "task_claim_requires_active_session",
        "task_claim_requires_claimable_state",
        "task_enter_in_progress_requires_claim",
        "task_insert_done_requires_evidence",
        "task_status_requires_next_revision",
        "task_update_done_requires_evidence",
    }
)
