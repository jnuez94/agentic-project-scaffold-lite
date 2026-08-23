"""Coordination health and export commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import html
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    Params,
    advisory_file_lock,
    audit,
    connect,
    discover_db,
    identifier,
    list_limit,
    now,
    operational_path,
    output_lock_path,
    path_argument,
    publish_temporary_file,
    read_transaction,
    rows,
    stale_days,
    stale_session_minutes,
    transaction,
    validate_output_path,
)
from coordination.entities.tasks import STATUSES, shape_tasks, task_query


def atomic_write_text(output: Path, content: str, *, force: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = f".{output.name}."
    suffix = ".tmp"
    with advisory_file_lock(output_lock_path(output), exclusive=True):
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=prefix,
            suffix=suffix,
            dir=output.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            publish_temporary_file(temporary, output, force=force)
        finally:
            temporary.unlink(missing_ok=True)


def _limited_rows(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...],
    limit: int,
) -> tuple[list[dict[str, object]], bool]:
    values = rows(connection.execute(query + " LIMIT ?", (*parameters, limit + 1)))
    return values[:limit], len(values) > limit


def _markdown_inline(value: object) -> str:
    collapsed = re.sub(r"\s+", " ", str(value)).strip()
    escaped = html.escape(collapsed, quote=False)
    return re.sub(r"([\\`*_\[\]{}|])", r"\\\1", escaped)


HEALTH_ANOMALY_SECTIONS = (
    "unowned_tasks",
    "stale_tasks",
    "stale_sessions",
    "unclaimed_in_progress_tasks",
    "invalid_active_claims",
    "active_blockers",
    "done_without_evidence",
    "open_escalations",
)
HEALTH_INFORMATIONAL_SECTIONS = ("tasks_awaiting_review",)
HEALTH_SECTIONS = HEALTH_ANOMALY_SECTIONS + HEALTH_INFORMATIONAL_SECTIONS


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


SUMMARY_SECTIONS = (
    "totals",
    "task_status",
    "task_priority",
    "workload",
    "time_in_state",
)


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


def export(args: argparse.Namespace) -> dict[str, object] | None:
    database = discover_db(args.db)
    connection = connect(database)
    with read_transaction(connection):
        task_values = shape_tasks(
            connection,
            connection.execute(task_query() + " ORDER BY t.priority, t.id"),
        )
    lines = ["# Coordination Export", "", f"Generated: {now()}", "", "## Tasks", ""]
    for task in task_values:
        lines.extend(
            [
                f"### {_markdown_inline(task['id'])}"
                f": {_markdown_inline(task['title'])}",
                "",
                f"- Status: `{task['status']}`",
                f"- Priority: {task['priority']}",
                (
                    "- Assignees: "
                    + (
                        ", ".join(
                            _markdown_inline(value) for value in task["assignees"]
                        )
                        if task["assignees"]
                        else "unassigned"
                    )
                ),
                f"- Evidence records: {task['evidence_count']}",
                "",
            ]
        )
    content = "\n".join(lines) + "\n"
    actor = getattr(args, "actor", None)
    if actor:
        with transaction(connection):
            audit(
                connection,
                actor,
                "export",
                "database",
                str(database),
                f"output {args.output}" if args.output else "output stdout",
                session_id=args.session,
            )
    if args.output:
        output = operational_path(
            args.output,
            label="Export output",
            must_exist=False,
        )
        validate_output_path(
            output,
            database,
            label="Export output",
            database_namespace=False,
        )
        atomic_write_text(output, content, force=args.force)
        return {"output": str(output), "tasks": len(task_values)}
    print(content, end="")
    return None


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    health_parser = commands.add_parser("health", help="Report coordination health")
    health_parser.add_argument("--stale-days", type=stale_days, default=7)
    health_parser.add_argument(
        "--stale-session-minutes",
        type=stale_session_minutes,
        default=60,
    )
    health_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    health_parser.add_argument(
        "--section",
        choices=HEALTH_SECTIONS,
        action="append",
        help="Repeatable; compute only these sections",
    )
    health_parser.set_defaults(func=health)

    summary_parser = commands.add_parser(
        "summary", help="Aggregate counts at one coherent snapshot"
    )
    summary_parser.add_argument(
        "--section",
        choices=SUMMARY_SECTIONS,
        action="append",
        help="Repeatable; compute only these sections",
    )
    summary_parser.set_defaults(func=summary)

    export_parser = commands.add_parser("export", help="Export a Markdown report")
    export_parser.add_argument("--output", type=path_argument)
    export_parser.add_argument("--force", action="store_true")
    export_parser.add_argument(
        "--actor",
        type=identifier,
        help="Record the export in the audit log, attributed to this actor",
    )
    export_parser.set_defaults(func=export)
