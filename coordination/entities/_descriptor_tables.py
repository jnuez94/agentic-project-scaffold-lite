"""Per-entity descriptor tables: the query capability whitelist."""

from __future__ import annotations

from coordination.entities._descriptor_engine import Column, EntityDescriptor


_TS = Column("timestamp")

_ID = Column("identifier")

_TEXT = Column("text")

AGENTS = EntityDescriptor(
    "agent",
    "",
    {
        "id": _ID,
        "name": _TEXT,
        "role": _TEXT,
        "actor_type": Column("enum", ("ai", "human", "service")),
        "status": Column("enum", ("active", "inactive")),
        "created_at": _TS,
        "updated_at": _TS,
    },
    ("id", "name", "role", "actor_type", "status", "created_at", "updated_at"),
    has_updated_at=True,
)

SESSIONS = EntityDescriptor(
    "session",
    "",
    {
        "id": _ID,
        "agent_id": _ID,
        "harness": _TEXT,
        "model": _TEXT,
        "status": Column("enum", ("active", "ended")),
        "started_at": _TS,
        "last_seen_at": _TS,
        "ended_at": _TS,
    },
    ("id", "agent_id", "harness", "status", "started_at", "last_seen_at", "ended_at"),
)

TASKS = EntityDescriptor(
    "task",
    "t",
    {
        "id": _ID,
        "title": _TEXT,
        "status": Column("enum", ("todo", "in_progress", "review", "blocked", "done")),
        "priority": Column("int"),
        "revision": Column("int"),
        "created_by": _ID,
        "created_at": _TS,
        "updated_at": _TS,
    },
    (
        "id",
        "title",
        "status",
        "priority",
        "revision",
        "created_by",
        "created_at",
        "updated_at",
    ),
    has_updated_at=True,
)

EVIDENCE = EntityDescriptor(
    "evidence",
    "",
    {
        "id": Column("int"),
        "task_id": _ID,
        "evidence_type": _TEXT,
        "added_by": _ID,
        "created_at": _TS,
    },
    ("id", "evidence_type", "added_by", "created_at"),
)

REVIEWS = EntityDescriptor(
    "review",
    "",
    {
        "id": _ID,
        "task_id": _ID,
        "reviewer_id": _ID,
        "scope": _TEXT,
        "decision": Column(
            "enum",
            ("accepted", "conditionally_accepted", "changes_requested", "rejected"),
        ),
        "created_at": _TS,
    },
    ("id", "task_id", "reviewer_id", "decision", "created_at"),
)

DECISIONS = EntityDescriptor(
    "decision",
    "",
    {
        "id": _ID,
        "title": _TEXT,
        "owner_id": _ID,
        "status": Column("enum", ("proposed", "accepted", "superseded", "rejected")),
        "created_at": _TS,
        "updated_at": _TS,
    },
    ("id", "title", "owner_id", "status", "created_at", "updated_at"),
    has_updated_at=True,
)

MESSAGES = EntityDescriptor(
    "message",
    "",
    {
        "id": _ID,
        "sender_id": _ID,
        "recipient": _TEXT,
        "task_id": _ID,
        "created_at": _TS,
    },
    ("id", "sender_id", "recipient", "task_id", "created_at"),
)

ARTIFACTS = EntityDescriptor(
    "artifact",
    "a",
    {
        "id": _ID,
        "uri": _TEXT,
        "owner_id": _ID,
        "type": _TEXT,
        "status": Column("enum", ("draft", "review", "accepted", "superseded")),
        "created_at": _TS,
        "updated_at": _TS,
    },
    ("id", "uri", "owner_id", "type", "status", "created_at", "updated_at"),
    has_updated_at=True,
)

ESCALATIONS = EntityDescriptor(
    "escalation",
    "",
    {
        "id": _ID,
        "raised_by": _ID,
        "owner": _TEXT,
        "status": Column("enum", ("open", "in_review", "resolved", "closed_no_action")),
        "created_at": _TS,
        "updated_at": _TS,
    },
    ("id", "raised_by", "owner", "status", "created_at", "updated_at"),
    has_updated_at=True,
)

DESCRIPTORS = {
    d.name: d
    for d in (
        AGENTS,
        SESSIONS,
        TASKS,
        EVIDENCE,
        REVIEWS,
        DECISIONS,
        MESSAGES,
        ARTIFACTS,
        ESCALATIONS,
    )
}
