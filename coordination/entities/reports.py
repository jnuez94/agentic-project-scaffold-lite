"""Coordination health and export commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile

from coordination.core import connect, discover_db, emit, now, rows
from coordination.entities.tasks import task_query
from coordination.errors import EXIT_CONFLICT, EXIT_USAGE, fail


def atomic_write_text(output: Path, content: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def health(args: argparse.Namespace) -> None:
    if args.stale_days < 0 or args.stale_session_minutes < 0:
        fail(
            "invalid_arguments",
            "Health stale thresholds must be zero or greater",
            EXIT_USAGE,
        )
    connection = connect(discover_db(args.db))
    task_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=args.stale_days)
    ).replace(microsecond=0).isoformat()
    session_cutoff = (
        datetime.now(timezone.utc)
        - timedelta(minutes=args.stale_session_minutes)
    ).replace(microsecond=0).isoformat()
    report = {
        "unowned_tasks": rows(
            connection.execute(
                """SELECT * FROM tasks t
                   WHERE status <> 'done'
                     AND NOT EXISTS (
                       SELECT 1 FROM task_assignees a WHERE a.task_id = t.id
                     )
                   ORDER BY priority, id"""
            )
        ),
        "stale_tasks": rows(
            connection.execute(
                """SELECT * FROM tasks
                   WHERE status IN ('in_progress', 'review', 'blocked')
                     AND updated_at < ?
                   ORDER BY updated_at""",
                (task_cutoff,),
            )
        ),
        "stale_sessions": rows(
            connection.execute(
                """SELECT * FROM agent_sessions
                   WHERE status = 'active' AND last_seen_at <= ?
                   ORDER BY last_seen_at, id""",
                (session_cutoff,),
            )
        ),
        "unclaimed_in_progress_tasks": rows(
            connection.execute(
                """SELECT * FROM tasks t
                   WHERE status = 'in_progress'
                     AND NOT EXISTS (
                       SELECT 1 FROM task_claims c WHERE c.task_id = t.id
                     )
                   ORDER BY priority, id"""
            )
        ),
        "invalid_active_claims": rows(
            connection.execute(
                """SELECT c.*, t.status AS task_status,
                          s.status AS session_status,
                          s.agent_id AS session_agent_id
                   FROM task_claims c
                   JOIN tasks t ON t.id = c.task_id
                   JOIN agent_sessions s ON s.id = c.session_id
                   WHERE t.status <> 'in_progress'
                      OR s.status <> 'active'
                      OR s.agent_id <> c.agent_id
                   ORDER BY c.task_id"""
            )
        ),
        "active_blockers": rows(
            connection.execute(
                "SELECT * FROM tasks WHERE status = 'blocked' ORDER BY priority, updated_at"
            )
        ),
        "done_without_evidence": rows(
            connection.execute(
                """SELECT * FROM tasks t
                   WHERE status = 'done'
                     AND NOT EXISTS (
                       SELECT 1 FROM task_evidence e WHERE e.task_id = t.id
                     )"""
            )
        ),
        "open_escalations": rows(
            connection.execute(
                """SELECT * FROM escalations
                   WHERE status IN ('open', 'in_review')
                   ORDER BY created_at"""
            )
        ),
    }
    report["healthy"] = not any(report.values())
    emit(report)


def export(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    task_values = rows(
        connection.execute(task_query() + " GROUP BY t.id ORDER BY t.priority, t.id")
    )
    lines = ["# Coordination Export", "", f"Generated: {now()}", "", "## Tasks", ""]
    for task in task_values:
        lines.extend(
            [
                f"### {task['id']}: {task['title']}",
                "",
                f"- Status: `{task['status']}`",
                f"- Priority: {task['priority']}",
                f"- Assignees: {task['assignees'] or 'unassigned'}",
                f"- Evidence records: {task['evidence_count']}",
                "",
            ]
        )
    content = "\n".join(lines) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        if output.exists() and not args.force:
            fail(
                "output_exists",
                f"Export already exists: {output}. Pass --force to replace it.",
                EXIT_CONFLICT,
                {"output": str(output)},
            )
        atomic_write_text(output, content)
        emit({"output": str(output), "tasks": len(task_values)})
    else:
        print(content, end="")


def register(commands: argparse._SubParsersAction) -> None:
    health_parser = commands.add_parser("health", help="Report coordination health")
    health_parser.add_argument("--stale-days", type=int, default=7)
    health_parser.add_argument("--stale-session-minutes", type=int, default=60)
    health_parser.set_defaults(func=health)

    export_parser = commands.add_parser("export", help="Export a Markdown report")
    export_parser.add_argument("--output")
    export_parser.add_argument("--force", action="store_true")
    export_parser.set_defaults(func=export)
