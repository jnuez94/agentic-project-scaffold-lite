"""The project summary report."""

from __future__ import annotations

import sqlite3

from coordination.core import (
    MAX_LIST_LIMIT,
    Params,
    read_transaction,
    rows,
)
from coordination.entities._reports_shared import SUMMARY_SECTIONS
from coordination.entities.tasks import STATUSES


def summary(connection: sqlite3.Connection, params: Params) -> dict[str, object]:
    """Aggregate counts computed at one coherent snapshot.

    A client building a dashboard from several `list` calls gets a torn read
    whenever another agent commits between them; only the runtime can answer
    with counts that agree with each other, because only it owns the read
    transaction. `audit_cursor` is the highest audit id at that snapshot, so
    "has anything happened since" is one call and `audit list --since` is the
    follow-up.
    """
    selected = list(getattr(params, "section", None) or SUMMARY_SECTIONS)
    report: dict[str, object] = {}
    with read_transaction(connection):
        report["audit_cursor"] = int(
            connection.execute("SELECT COALESCE(MAX(id), 0) FROM audit_log").fetchone()[
                0
            ]
        )
        if "totals" in selected:
            report["totals"] = {
                name: int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
                for name, table in (
                    ("agents", "agents"),
                    ("sessions", "agent_sessions"),
                    ("tasks", "tasks"),
                    ("evidence", "task_evidence"),
                    ("dependencies", "task_dependencies"),
                    ("reviews", "reviews"),
                    ("decisions", "decisions"),
                    ("messages", "messages"),
                    ("artifacts", "artifacts"),
                    ("escalations", "escalations"),
                    ("audit", "audit_log"),
                )
            }
        if "task_status" in selected:
            counts = dict.fromkeys(STATUSES, 0)
            for row in connection.execute(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
            ):
                counts[str(row["status"])] = int(row["n"])
            report["task_status"] = counts
        if "task_priority" in selected:
            priorities = {str(priority): 0 for priority in range(1, 6)}
            for row in connection.execute(
                "SELECT priority, COUNT(*) AS n FROM tasks GROUP BY priority"
            ):
                priorities[str(row["priority"])] = int(row["n"])
            report["task_priority"] = priorities
        if "workload" in selected:
            values = rows(
                connection.execute(
                    """SELECT a.id AS agent_id, a.status AS agent_status,
                              (SELECT COUNT(*) FROM task_assignees x
                                 JOIN tasks t ON t.id = x.task_id
                                WHERE x.agent_id = a.id AND t.status <> 'done')
                                AS assigned_open_tasks,
                              (SELECT COUNT(*) FROM task_claims c
                                WHERE c.agent_id = a.id) AS claimed_tasks,
                              (SELECT COUNT(*) FROM agent_sessions s
                                WHERE s.agent_id = a.id AND s.status = 'active')
                                AS active_sessions
                       FROM agents a ORDER BY a.id LIMIT ?""",
                    (MAX_LIST_LIMIT + 1,),
                )
            )
            report["workload"] = values[:MAX_LIST_LIMIT]
            report["workload_truncated"] = len(values) > MAX_LIST_LIMIT
        if "time_in_state" in selected:
            # How long open work has sat in its current status, measured from
            # the last status-changing audit row for each task. Derived from
            # the ledger that already exists: no new state.
            ages = {
                status: {"count": 0, "oldest_seconds": 0, "average_seconds": 0}
                for status in STATUSES
                if status != "done"
            }
            for row in connection.execute(
                """SELECT status, COUNT(*) AS n,
                          MAX(age_seconds) AS oldest, AVG(age_seconds) AS average
                     FROM (
                       SELECT t.status,
                              (julianday('now') - julianday(COALESCE(
                                 (SELECT MAX(a.created_at) FROM audit_log a
                                   WHERE a.object_type = 'task'
                                     AND a.object_id = t.id
                                     AND a.action IN
                                       ('create', 'status', 'claim', 'recover_claim')),
                                 t.updated_at))) * 86400 AS age_seconds
                         FROM tasks t
                        WHERE t.status <> 'done')
                    GROUP BY status"""
            ):
                ages[str(row["status"])] = {
                    "count": int(row["n"]),
                    "oldest_seconds": max(0, int(row["oldest"] or 0)),
                    "average_seconds": max(0, int(row["average"] or 0)),
                }
            report["time_in_state"] = ages
    report["sections"] = [name for name in SUMMARY_SECTIONS if name in selected]
    return report
