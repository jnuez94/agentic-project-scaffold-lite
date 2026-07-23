"""Task entity commands and shared task query."""

from __future__ import annotations

import argparse
from typing import Any

from coordination.core import (
    audit,
    connect,
    discover_db,
    emit,
    now,
    require_active_session,
    require_row,
    rows,
    transaction,
)
from coordination.errors import EXIT_CONFLICT, EXIT_USAGE, fail


STATUSES = ("todo", "in_progress", "review", "blocked", "done")
STATUS_TRANSITIONS = {
    "todo": frozenset({"in_progress", "blocked"}),
    "in_progress": frozenset({"todo", "review", "blocked"}),
    "review": frozenset({"in_progress", "blocked", "done"}),
    "blocked": frozenset({"todo", "in_progress"}),
    "done": frozenset(),
}


def task_query() -> str:
    return """SELECT t.*,
        tc.agent_id AS claimed_by,
        tc.session_id AS claim_session_id,
        tc.claimed_at,
        COALESCE(GROUP_CONCAT(DISTINCT ta.agent_id), '') AS assignees,
        COUNT(DISTINCT e.id) AS evidence_count
      FROM tasks t
      LEFT JOIN task_assignees ta ON ta.task_id = t.id
      LEFT JOIN task_claims tc ON tc.task_id = t.id
      LEFT JOIN task_evidence e ON e.task_id = t.id"""


def reject_stale_revision(task_id: str, expected: int, actual: int) -> None:
    fail(
        "stale_task_revision",
        f"Task {task_id} changed after revision {expected}",
        EXIT_CONFLICT,
        {
            "task": task_id,
            "expected_revision": expected,
            "actual_revision": actual,
        },
    )


def create(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
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
        audit(
            connection,
            args.actor,
            "create",
            "task",
            args.id,
            session_id=args.session,
        )
    emit(
        {
            "id": args.id,
            "status": "todo",
            "revision": 1,
            "assignees": args.assignee,
        }
    )


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
    if not args.session:
        fail(
            "session_required",
            "Task claims require an active session via --session or COORDINATION_SESSION",
            EXIT_USAGE,
        )
    connection = connect(discover_db(args.db))
    stamp = now()
    result: dict[str, Any]
    with transaction(connection):
        require_row(
            connection,
            "SELECT id FROM agents WHERE id = ? AND status = 'active'",
            (args.agent,),
            f"active agent {args.agent}",
        )
        require_active_session(connection, args.session, args.agent)
        task = require_row(
            connection,
            "SELECT status, revision FROM tasks WHERE id = ?",
            (args.id,),
            f"task {args.id}",
        )
        active_claim = connection.execute(
            "SELECT agent_id, session_id, claimed_at FROM task_claims WHERE task_id = ?",
            (args.id,),
        ).fetchone()
        if task["revision"] != args.if_revision:
            if (
                task["revision"] == args.if_revision + 1
                and task["status"] == "in_progress"
                and active_claim is not None
                and active_claim["agent_id"] == args.agent
                and active_claim["session_id"] == args.session
            ):
                result = {
                    "id": args.id,
                    "status": "in_progress",
                    "revision": task["revision"],
                    "agent": args.agent,
                    "session_id": args.session,
                    "claimed": False,
                    "idempotent_replay": True,
                }
            else:
                reject_stale_revision(args.id, args.if_revision, task["revision"])
        elif task["status"] == "in_progress":
            fail(
                "task_already_claimed",
                f"Task {args.id} already has an active claim",
                EXIT_CONFLICT,
                {
                    "task": args.id,
                    "agent": active_claim["agent_id"] if active_claim else None,
                    "session_id": active_claim["session_id"] if active_claim else None,
                },
            )
        elif task["status"] not in ("todo", "review", "blocked"):
            fail(
                "invalid_task_state",
                f"Task {args.id} cannot be claimed from status {task['status']}",
                EXIT_CONFLICT,
                {"task": args.id, "status": task["status"]},
            )
        else:
            connection.execute(
                """INSERT INTO task_claims(task_id, agent_id, session_id, claimed_at)
                   VALUES (?, ?, ?, ?)""",
                (args.id, args.agent, args.session, stamp),
            )
            cursor = connection.execute(
                """UPDATE tasks
                   SET status = 'in_progress', revision = revision + 1, updated_at = ?
                   WHERE id = ? AND revision = ?""",
                (stamp, args.id, args.if_revision),
            )
            if cursor.rowcount != 1:
                actual = int(
                    connection.execute(
                        "SELECT revision FROM tasks WHERE id = ?", (args.id,)
                    ).fetchone()[0]
                )
                reject_stale_revision(args.id, args.if_revision, actual)
            connection.execute(
                """INSERT OR IGNORE INTO task_assignees(task_id, agent_id, assigned_at)
                   VALUES (?, ?, ?)""",
                (args.id, args.agent, stamp),
            )
            audit(
                connection,
                args.agent,
                "claim",
                "task",
                args.id,
                f"revision {args.if_revision} -> {args.if_revision + 1}",
                session_id=args.session,
            )
            result = {
                "id": args.id,
                "status": "in_progress",
                "revision": args.if_revision + 1,
                "agent": args.agent,
                "session_id": args.session,
                "claimed": True,
                "idempotent_replay": False,
            }
    emit(result)


def status(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
        task = require_row(
            connection,
            "SELECT status, revision FROM tasks WHERE id = ?",
            (args.id,),
            f"task {args.id}",
        )
        if task["revision"] != args.if_revision:
            reject_stale_revision(args.id, args.if_revision, task["revision"])
        if args.status == "in_progress":
            fail(
                "task_claim_required",
                "Use task claim to enter in_progress and establish exclusive ownership",
                EXIT_USAGE,
                {"task": args.id},
            )
        if args.status == task["status"]:
            fail(
                "invalid_task_state",
                f"Task {args.id} is already in status {args.status}",
                EXIT_CONFLICT,
                {"task": args.id, "status": args.status},
            )
        if args.status not in STATUS_TRANSITIONS[task["status"]]:
            fail(
                "invalid_task_transition",
                f"Task {args.id} cannot transition from {task['status']} to {args.status}",
                EXIT_CONFLICT,
                {
                    "task": args.id,
                    "from": task["status"],
                    "to": args.status,
                    "allowed": sorted(STATUS_TRANSITIONS[task["status"]]),
                },
            )
        if task["status"] == "in_progress":
            active_claim = require_row(
                connection,
                "SELECT agent_id, session_id FROM task_claims WHERE task_id = ?",
                (args.id,),
                f"active claim for task {args.id}",
            )
            if args.actor != active_claim["agent_id"]:
                fail(
                    "task_claim_owner_mismatch",
                    f"Task {args.id} is claimed by {active_claim['agent_id']}",
                    EXIT_CONFLICT,
                    {
                        "task": args.id,
                        "claimed_by": active_claim["agent_id"],
                        "actor": args.actor,
                    },
                )
            if args.session != active_claim["session_id"]:
                fail(
                    "task_claim_session_mismatch",
                    f"Task {args.id} is claimed by session {active_claim['session_id']}",
                    EXIT_CONFLICT,
                    {
                        "task": args.id,
                        "claim_session_id": active_claim["session_id"],
                        "session_id": args.session,
                    },
                )
        cursor = connection.execute(
            """UPDATE tasks
               SET status = ?,
                   notes = CASE WHEN ? = '' THEN notes ELSE ? END,
                   revision = revision + 1,
                   updated_at = ?
               WHERE id = ? AND revision = ?""",
            (
                args.status,
                args.note,
                args.note,
                stamp,
                args.id,
                args.if_revision,
            ),
        )
        if cursor.rowcount != 1:
            actual = int(
                connection.execute(
                    "SELECT revision FROM tasks WHERE id = ?", (args.id,)
                ).fetchone()[0]
            )
            reject_stale_revision(args.id, args.if_revision, actual)
        if task["status"] == "in_progress":
            connection.execute("DELETE FROM task_claims WHERE task_id = ?", (args.id,))
        audit(
            connection,
            args.actor,
            "status",
            "task",
            args.id,
            (
                f"{task['status']} -> {args.status}; "
                f"revision {args.if_revision} -> {args.if_revision + 1}"
            ),
            session_id=args.session,
        )
    emit(
        {
            "id": args.id,
            "previous_status": task["status"],
            "status": args.status,
            "revision": args.if_revision + 1,
        }
    )


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
    claim_parser.add_argument("--if-revision", required=True, type=int)
    claim_parser.set_defaults(func=claim)

    status_parser = task.add_parser("status")
    status_parser.add_argument("id")
    status_parser.add_argument("status", choices=STATUSES)
    status_parser.add_argument("--actor")
    status_parser.add_argument("--note", default="")
    status_parser.add_argument("--if-revision", required=True, type=int)
    status_parser.set_defaults(func=status)
