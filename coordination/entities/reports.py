"""Coordination health, export, and backup commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from coordination.core import connect, discover_db, emit, now, rows
from coordination.entities.tasks import task_query
from coordination.errors import EXIT_CONFLICT, EXIT_USAGE, fail


def health(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=args.stale_days)
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
                (cutoff,),
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
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        emit({"output": str(output), "tasks": len(task_values)})
    else:
        print(content, end="")


def backup(args: argparse.Namespace) -> None:
    source = discover_db(args.db)
    destination = Path(args.output).expanduser().resolve()
    if source == destination:
        fail(
            "invalid_arguments",
            "Backup destination must differ from the source database",
            EXIT_USAGE,
        )
    if destination.exists() and not args.force:
        fail(
            "output_exists",
            f"Backup already exists: {destination}. Pass --force to replace it.",
            EXIT_CONFLICT,
            {"output": str(destination)},
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = connect(source)
    destination_connection = sqlite3.connect(destination)
    with destination_connection:
        source_connection.backup(destination_connection)
    destination_connection.close()
    emit({"backup": str(destination), "source": str(source)})


def register(commands: argparse._SubParsersAction) -> None:
    health_parser = commands.add_parser("health", help="Report coordination health")
    health_parser.add_argument("--stale-days", type=int, default=7)
    health_parser.set_defaults(func=health)

    export_parser = commands.add_parser("export", help="Export a Markdown report")
    export_parser.add_argument("--output")
    export_parser.add_argument("--force", action="store_true")
    export_parser.set_defaults(func=export)

    backup_parser = commands.add_parser("backup", help="Create a consistent SQLite backup")
    backup_parser.add_argument("--output", required=True)
    backup_parser.add_argument("--force", action="store_true")
    backup_parser.set_defaults(func=backup)
