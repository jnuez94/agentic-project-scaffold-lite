"""The health report: anomaly and informational sections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

from coordination.core import (
    Params,
    read_transaction,
)
from coordination.entities._reports_shared import HEALTH_SECTIONS, _limited_rows


def health(connection: sqlite3.Connection, params: Params) -> dict[str, object]:
    task_cutoff = (
        (datetime.now(timezone.utc) - timedelta(days=params.stale_days))
        .replace(microsecond=0)
        .isoformat()
    )
    session_cutoff = (
        (datetime.now(timezone.utc) - timedelta(minutes=params.stale_session_minutes))
        .replace(microsecond=0)
        .isoformat()
    )
    queries: dict[str, tuple[str, tuple[object, ...]]] = {
        "unowned_tasks": (
            """SELECT * FROM tasks t
                   WHERE status <> 'done'
                     AND NOT EXISTS (
                       SELECT 1 FROM task_assignees a WHERE a.task_id = t.id
                     )
                   ORDER BY priority, id""",
            (),
        ),
        "stale_tasks": (
            """SELECT * FROM tasks
                   WHERE status IN ('in_progress', 'review', 'blocked')
                     AND updated_at < ?
                   ORDER BY updated_at, id""",
            (task_cutoff,),
        ),
        "stale_sessions": (
            """SELECT * FROM agent_sessions
                   WHERE status = 'active' AND last_seen_at <= ?
                   ORDER BY last_seen_at, id""",
            (session_cutoff,),
        ),
        "unclaimed_in_progress_tasks": (
            """SELECT * FROM tasks t
                   WHERE status = 'in_progress'
                     AND NOT EXISTS (
                       SELECT 1 FROM task_claims c WHERE c.task_id = t.id
                     )
                   ORDER BY priority, id""",
            (),
        ),
        "invalid_active_claims": (
            """SELECT c.*, t.status AS task_status,
                          s.status AS session_status,
                          s.agent_id AS session_agent_id,
                          a.status AS agent_status
                   FROM task_claims c
                   JOIN tasks t ON t.id = c.task_id
                   JOIN agent_sessions s ON s.id = c.session_id
                   JOIN agents a ON a.id = c.agent_id
                   WHERE t.status <> 'in_progress'
                      OR s.status <> 'active'
                      OR s.agent_id <> c.agent_id
                      OR a.status <> 'active'
                   ORDER BY c.task_id""",
            (),
        ),
        "active_blockers": (
            """SELECT * FROM tasks WHERE status = 'blocked'
               ORDER BY priority, updated_at, id""",
            (),
        ),
        "done_without_evidence": (
            """SELECT * FROM tasks t
                   WHERE status = 'done'
                     AND NOT EXISTS (
                       SELECT 1 FROM task_evidence e WHERE e.task_id = t.id
                     )
                   ORDER BY id""",
            (),
        ),
        "open_escalations": (
            """SELECT * FROM escalations
                   WHERE status IN ('open', 'in_review')
                   ORDER BY created_at, id""",
            (),
        ),
    }
    informational: dict[str, tuple[str, tuple[object, ...]]] = {
        "tasks_awaiting_review": (
            """SELECT * FROM tasks WHERE status = 'review'
               ORDER BY priority, updated_at, id""",
            (),
        ),
    }
    selected = list(getattr(params, "section", None) or HEALTH_SECTIONS)
    report: dict[str, object] = {}
    anomalies: dict[str, object] = {}
    informational_report: dict[str, object] = {}
    truncated: list[str] = []
    with read_transaction(connection):
        for name in HEALTH_SECTIONS:
            if name not in selected:
                continue
            query, parameters = (
                queries[name] if name in queries else informational[name]
            )
            values, was_truncated = _limited_rows(
                connection,
                query,
                parameters,
                params.limit,
            )
            report[name] = values
            (anomalies if name in queries else informational_report)[name] = values
            if was_truncated:
                truncated.append(name)
    # Every anomaly section describes decay; every informational section
    # describes normal workflow worth surfacing. Only anomalies can make a
    # project unhealthy, so a board with tasks awaiting review is not a
    # permanently unhealthy board. Top-level keys stay for existing clients.
    report["anomalies"] = anomalies
    report["informational"] = informational_report
    report["truncated_sections"] = truncated
    report["healthy"] = not any(anomalies.values())
    return report
