"""Task entity commands and shared task query."""

from __future__ import annotations

import argparse
from typing import Any, Iterable

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    audit,
    connect,
    discover_db,
    emit,
    identifier,
    list_limit,
    list_offset,
    now,
    optional_text,
    positive_revision,
    require_active_session,
    require_active_actor,
    require_row,
    require_unique,
    required_text,
    read_transaction,
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
        tc.claimed_at
      FROM tasks t
      LEFT JOIN task_claims tc ON tc.task_id = t.id"""


def shape_tasks(
    connection: Any,
    task_rows: Iterable[Any],
) -> list[dict[str, Any]]:
    values = [dict(row) for row in task_rows]
    if not values:
        return []
    task_ids = [str(value["id"]) for value in values]
    assignees: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    evidence_counts = {task_id: 0 for task_id in task_ids}
    for offset in range(0, len(task_ids), 400):
        batch = task_ids[offset : offset + 400]
        placeholders = ",".join("?" for _ in batch)
        for row in connection.execute(
            f"""SELECT task_id, agent_id FROM task_assignees
                WHERE task_id IN ({placeholders})
                ORDER BY task_id, agent_id""",
            batch,
        ):
            assignees[str(row["task_id"])].append(str(row["agent_id"]))
        for row in connection.execute(
            f"""SELECT task_id, COUNT(*) AS evidence_count FROM task_evidence
                WHERE task_id IN ({placeholders})
                GROUP BY task_id
                ORDER BY task_id""",
            batch,
        ):
            evidence_counts[str(row["task_id"])] = int(row["evidence_count"])
    for value in values:
        task_id = str(value["id"])
        value["assignees"] = assignees[task_id]
        value["evidence_count"] = evidence_counts[task_id]
    return values


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
    require_unique(args.assignee, "--assignee")
    with transaction(connection):
        require_active_actor(connection, args.actor)
        for assignee in args.assignee:
            require_row(
                connection,
                "SELECT id FROM agents WHERE id = ?",
                (assignee,),
                f"agent {assignee}",
            )
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
            "assignees": sorted(args.assignee),
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
    query += " ORDER BY t.priority, t.updated_at, t.id LIMIT ? OFFSET ?"
    parameters.extend((args.limit, args.offset))
    with read_transaction(connection):
        result = shape_tasks(connection, connection.execute(query, parameters))
    emit(result)


def show(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with read_transaction(connection):
        task = require_row(
            connection,
            task_query() + " WHERE t.id = ?",
            (args.id,),
            f"task {args.id}",
        )
        result = shape_tasks(connection, [task])[0]
        result["evidence"] = rows(
            connection.execute(
                """SELECT * FROM task_evidence
                   WHERE task_id = ? ORDER BY created_at, id""",
                (args.id,),
            )
        )
        result["dependencies"] = rows(
            connection.execute(
                """SELECT * FROM task_dependencies
                   WHERE task_id = ?
                   ORDER BY depends_on_task_id, dependency_type""",
                (args.id,),
            )
        )
        result["reviews"] = rows(
            connection.execute(
                "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at, id",
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
        require_active_actor(connection, args.agent)
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
        require_active_actor(connection, args.actor)
        if args.session:
            require_active_session(connection, args.session, args.actor)
        task = require_row(
            connection,
            "SELECT status, revision FROM tasks WHERE id = ?",
            (args.id,),
            f"task {args.id}",
        )
        if task["revision"] != args.if_revision:
            reject_stale_revision(args.id, args.if_revision, task["revision"])
        if task["status"] == "in_progress" and not args.session:
            fail(
                "session_required",
                "Leaving in_progress requires the active claiming session",
                EXIT_USAGE,
                {"task": args.id},
            )
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
    create_parser.add_argument("--id", required=True, type=identifier)
    create_parser.add_argument("--title", required=True, type=required_text)
    create_parser.add_argument("--description", default="", type=optional_text)
    create_parser.add_argument("--priority", type=int, choices=range(1, 6), default=3)
    create_parser.add_argument("--tags", default="", type=optional_text)
    create_parser.add_argument("--acceptance", default="", type=optional_text)
    create_parser.add_argument("--next-steps", default="", type=optional_text)
    create_parser.add_argument("--blocked-claims", default="", type=optional_text)
    create_parser.add_argument("--actor", required=True, type=identifier)
    create_parser.add_argument(
        "--assignee",
        action="append",
        default=[],
        type=identifier,
    )
    create_parser.set_defaults(func=create)

    list_parser = task.add_parser("list")
    list_parser.add_argument("--status", choices=STATUSES)
    list_parser.add_argument("--assignee", type=identifier)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_tasks)

    show_parser = task.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)

    claim_parser = task.add_parser("claim")
    claim_parser.add_argument("id", type=identifier)
    claim_parser.add_argument("--agent", required=True, type=identifier)
    claim_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    claim_parser.set_defaults(func=claim)

    status_parser = task.add_parser("status")
    status_parser.add_argument("id", type=identifier)
    status_parser.add_argument("status", choices=STATUSES)
    status_parser.add_argument("--actor", required=True, type=identifier)
    status_parser.add_argument("--note", default="", type=optional_text)
    status_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    status_parser.set_defaults(func=status)
