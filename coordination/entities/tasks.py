"""Task entity commands and shared task query."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import audit, connect, discover_db, emit, now, require_row, rows


STATUSES = ("todo", "in_progress", "review", "blocked", "done")


def task_query() -> str:
    return """SELECT t.*,
        COALESCE(GROUP_CONCAT(DISTINCT ta.agent_id), '') AS assignees,
        COUNT(DISTINCT e.id) AS evidence_count
      FROM tasks t
      LEFT JOIN task_assignees ta ON ta.task_id = t.id
      LEFT JOIN task_evidence e ON e.task_id = t.id"""


def create(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        connection.execute(
            """INSERT INTO tasks(
                id, title, description, priority, tags, acceptance_criteria,
                next_steps, blocked_claims, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                args.id,
                args.title,
                args.description,
                args.priority,
                args.tags,
                args.acceptance,
                args.next_steps,
                args.blocked_claims,
                args.actor,
                stamp,
                stamp,
            ),
        )
        for assignee in args.assignee:
            connection.execute(
                "INSERT INTO task_assignees(task_id, agent_id, assigned_at) VALUES (?, ?, ?)",
                (args.id, assignee, stamp),
            )
        audit(connection, args.actor, "create", "task", args.id)
    emit({"id": args.id, "status": "todo", "assignees": args.assignee})


def list_tasks(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = task_query()
    conditions: list[str] = []
    parameters: list[Any] = []
    if args.status:
        conditions.append("t.status = ?")
        parameters.append(args.status)
    if args.assignee:
        conditions.append(
            "EXISTS (SELECT 1 FROM task_assignees x WHERE x.task_id = t.id AND x.agent_id = ?)"
        )
        parameters.append(args.assignee)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " GROUP BY t.id ORDER BY t.priority, t.updated_at, t.id"
    emit(rows(connection.execute(query, parameters)))


def show(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    task = require_row(
        connection,
        task_query() + " WHERE t.id = ? GROUP BY t.id",
        (args.id,),
        f"task {args.id}",
    )
    result = dict(task)
    result["evidence"] = rows(
        connection.execute(
            "SELECT * FROM task_evidence WHERE task_id = ? ORDER BY created_at",
            (args.id,),
        )
    )
    result["dependencies"] = rows(
        connection.execute(
            "SELECT * FROM task_dependencies WHERE task_id = ? ORDER BY depends_on_task_id",
            (args.id,),
        )
    )
    result["reviews"] = rows(
        connection.execute(
            "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at",
            (args.id,),
        )
    )
    emit(result)


def claim(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        require_row(
            connection,
            "SELECT id FROM agents WHERE id = ? AND status = 'active'",
            (args.agent,),
            f"active agent {args.agent}",
        )
        task = require_row(
            connection,
            "SELECT status FROM tasks WHERE id = ?",
            (args.id,),
            f"task {args.id}",
        )
        if task["status"] not in ("todo", "in_progress"):
            raise SystemExit(f"Task {args.id} cannot be claimed from status {task['status']}")
        connection.execute(
            "INSERT OR IGNORE INTO task_assignees(task_id, agent_id, assigned_at) VALUES (?, ?, ?)",
            (args.id, args.agent, stamp),
        )
        connection.execute(
            "UPDATE tasks SET status = 'in_progress', updated_at = ? WHERE id = ?",
            (stamp, args.id),
        )
        audit(connection, args.agent, "claim", "task", args.id)
    emit({"id": args.id, "status": "in_progress", "agent": args.agent})


def status(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        task = require_row(
            connection,
            "SELECT status FROM tasks WHERE id = ?",
            (args.id,),
            f"task {args.id}",
        )
        connection.execute(
            """UPDATE tasks
               SET status = ?,
                   notes = CASE WHEN ? = '' THEN notes ELSE ? END,
                   updated_at = ?
               WHERE id = ?""",
            (args.status, args.note, args.note, stamp, args.id),
        )
        audit(
            connection,
            args.actor,
            "status",
            "task",
            args.id,
            f"{task['status']} -> {args.status}",
        )
    emit({"id": args.id, "previous_status": task["status"], "status": args.status})


def register(commands: argparse._SubParsersAction) -> None:
    task = commands.add_parser("task", help="Manage tasks").add_subparsers(
        dest="task_command",
        required=True,
    )
    create_parser = task.add_parser("create")
    create_parser.add_argument("--id", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description", default="")
    create_parser.add_argument("--priority", type=int, choices=range(1, 6), default=3)
    create_parser.add_argument("--tags", default="")
    create_parser.add_argument("--acceptance", default="")
    create_parser.add_argument("--next-steps", default="")
    create_parser.add_argument("--blocked-claims", default="")
    create_parser.add_argument("--actor")
    create_parser.add_argument("--assignee", action="append", default=[])
    create_parser.set_defaults(func=create)

    list_parser = task.add_parser("list")
    list_parser.add_argument("--status", choices=STATUSES)
    list_parser.add_argument("--assignee")
    list_parser.set_defaults(func=list_tasks)

    show_parser = task.add_parser("show")
    show_parser.add_argument("id")
    show_parser.set_defaults(func=show)

    claim_parser = task.add_parser("claim")
    claim_parser.add_argument("id")
    claim_parser.add_argument("--agent", required=True)
    claim_parser.set_defaults(func=claim)

    status_parser = task.add_parser("status")
    status_parser.add_argument("id")
    status_parser.add_argument("status", choices=STATUSES)
    status_parser.add_argument("--actor")
    status_parser.add_argument("--note", default="")
    status_parser.set_defaults(func=status)
