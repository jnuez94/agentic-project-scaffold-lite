"""Coordination health and export commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import html
import os
from pathlib import Path
import re
import tempfile

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    advisory_file_lock,
    connect,
    discover_db,
    emit,
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
    validate_output_path,
)
from coordination.entities.tasks import shape_tasks, task_query


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
    connection: object,
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


def health(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    task_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=args.stale_days)
    ).replace(microsecond=0).isoformat()
    session_cutoff = (
        datetime.now(timezone.utc)
        - timedelta(minutes=args.stale_session_minutes)
    ).replace(microsecond=0).isoformat()
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
    report: dict[str, object] = {}
    truncated: list[str] = []
    with read_transaction(connection):
        for name, (query, parameters) in queries.items():
            values, was_truncated = _limited_rows(
                connection,
                query,
                parameters,
                args.limit,
            )
            report[name] = values
            if was_truncated:
                truncated.append(name)
    report["truncated_sections"] = truncated
    report["healthy"] = not any(report[name] for name in queries)
    emit(report)


def export(args: argparse.Namespace) -> None:
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
                f"### {_markdown_inline(task['id'])}: {_markdown_inline(task['title'])}",
                "",
                f"- Status: `{task['status']}`",
                f"- Priority: {task['priority']}",
                (
                    "- Assignees: "
                    + (
                        ", ".join(_markdown_inline(value) for value in task["assignees"])
                        if task["assignees"]
                        else "unassigned"
                    )
                ),
                f"- Evidence records: {task['evidence_count']}",
                "",
            ]
        )
    content = "\n".join(lines) + "\n"
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
        emit({"output": str(output), "tasks": len(task_values)})
    else:
        print(content, end="")


def register(commands: argparse._SubParsersAction) -> None:
    health_parser = commands.add_parser("health", help="Report coordination health")
    health_parser.add_argument("--stale-days", type=stale_days, default=7)
    health_parser.add_argument(
        "--stale-session-minutes",
        type=stale_session_minutes,
        default=60,
    )
    health_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    health_parser.set_defaults(func=health)

    export_parser = commands.add_parser("export", help="Export a Markdown report")
    export_parser.add_argument("--output", type=path_argument)
    export_parser.add_argument("--force", action="store_true")
    export_parser.set_defaults(func=export)
