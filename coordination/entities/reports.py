"""Coordination health and export commands."""

from __future__ import annotations


# fmt: off
# isort: off
from coordination.entities._reports_shared import (
    _limited_rows as _limited_rows, _markdown_inline as _markdown_inline,
    atomic_write_text as atomic_write_text,
    HEALTH_ANOMALY_SECTIONS as HEALTH_ANOMALY_SECTIONS,
    HEALTH_INFORMATIONAL_SECTIONS as HEALTH_INFORMATIONAL_SECTIONS,
    HEALTH_SECTIONS as HEALTH_SECTIONS, SUMMARY_SECTIONS as SUMMARY_SECTIONS,
)
from coordination.entities._reports_health import (
    health as health,
)
from coordination.entities._reports_summary import (
    summary as summary,
)
import argparse
from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
    connect,
    discover_db,
    identifier,
    list_limit,
    now,
    operational_path,
    path_argument,
    read_transaction,
    stale_days,
    stale_session_minutes,
    transaction,
    validate_output_path,
)
from coordination.entities.tasks import shape_tasks, task_query
# isort: on
# fmt: on


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
