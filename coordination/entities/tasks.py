"""Task entity commands and shared task query."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import sqlite3
from typing import Any

from coordination.core import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    SESSION_LEASE_SECONDS,
    audit,
    because_reference,
    connect,
    discover_db,
    identifier,
    list_limit,
    list_offset,
    now,
    optional_text,
    positive_revision,
    read_transaction,
    require_active_actor,
    require_active_session,
    require_row,
    require_unique,
    required_text,
    resolve_reference,
    rows,
    tag_token,
    transaction,
)
from coordination.entities.audit import register_history
from coordination.entities.sessions import recover_session_claims, stale_cutoff
from coordination.errors import EXIT_CONFLICT, EXIT_NOT_FOUND, EXIT_USAGE, fail


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
    evidence_counts = dict.fromkeys(task_ids, 0)
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


def require_claim_ownership(
    connection: sqlite3.Connection,
    task_id: str,
    actor: str,
    session: str | None,
) -> None:
    """Reject mutating a claimed task from anyone but the claim holder.

    An exclusive claim that any actor can write around is not exclusive. Every
    write bumps the revision, so without this an uninvolved actor could keep a
    claimed task's revision moving and stall the owner's own release. Callers
    must hold the write transaction so the claim cannot change underneath.
    Unclaimed tasks stay open to any active actor.
    """
    claim = connection.execute(
        "SELECT agent_id, session_id FROM task_claims WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if claim is None:
        return
    if actor != claim["agent_id"]:
        fail(
            "task_claim_owner_mismatch",
            f"Task {task_id} is claimed by {claim['agent_id']}",
            EXIT_CONFLICT,
            {
                "task": task_id,
                "claimed_by": claim["agent_id"],
                "actor": actor,
            },
        )
    if session != claim["session_id"]:
        fail(
            "task_claim_session_mismatch",
            f"Task {task_id} is claimed by session {claim['session_id']}",
            EXIT_CONFLICT,
            {
                "task": task_id,
                "claim_session_id": claim["session_id"],
                "session_id": session,
            },
        )


def create(args: argparse.Namespace) -> dict[str, Any]:
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
                "INSERT INTO task_assignees(task_id, agent_id, assigned_at)"
                " VALUES (?, ?, ?)",
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
    return {
        "id": args.id,
        "status": "todo",
        "revision": 1,
        "assignees": sorted(args.assignee),
    }


def list_tasks(args: argparse.Namespace) -> list[dict[str, Any]]:
    connection = connect(discover_db(args.db))
    query = task_query()
    conditions: list[str] = []
    parameters: list[Any] = []
    if args.status:
        statuses = [args.status] if isinstance(args.status, str) else list(args.status)
        placeholders = ",".join("?" for _ in statuses)
        conditions.append(f"t.status IN ({placeholders})")
        parameters.extend(statuses)
    if getattr(args, "tag", None):
        # `tags` is free text of comma-separated tokens. Compare against the
        # token list with surrounding whitespace removed, so "a, b" and "a,b"
        # both carry tokens a and b. LIKE wildcards in the tag are escaped.
        escaped = args.tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(
            "(',' || REPLACE(REPLACE(t.tags, ' ', ''), char(9), '') || ',')"
            " LIKE ? ESCAPE '\\'"
        )
        parameters.append(f"%,{escaped},%")
    if args.assignee:
        conditions.append(
            "EXISTS (SELECT 1 FROM task_assignees x"
            " WHERE x.task_id = t.id AND x.agent_id = ?)"
        )
        parameters.append(args.assignee)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY t.priority, t.updated_at, t.id LIMIT ? OFFSET ?"
    parameters.extend((args.limit, args.offset))
    with read_transaction(connection):
        result = shape_tasks(connection, connection.execute(query, parameters))
    return result


def show(args: argparse.Namespace) -> dict[str, Any]:
    connection = connect(discover_db(args.db))
    with read_transaction(connection):
        task = require_row(
            connection,
            task_query() + " WHERE t.id = ?",
            (args.id,),
            f"task {args.id}",
        )
        result = shape_tasks(connection, [task])[0]
        # Each detail array is bounded like every list command. An unbounded
        # inspect grew linearly with attached rows and could hand a client a
        # multi-megabyte response; `evidence_count` and the per-entity list
        # commands remain the complete view. Truncation is reported, never
        # silent.
        truncated: list[str] = []
        for name, query in (
            (
                "evidence",
                """SELECT * FROM task_evidence
                   WHERE task_id = ? ORDER BY created_at, id""",
            ),
            (
                "dependencies",
                """SELECT * FROM task_dependencies
                   WHERE task_id = ?
                   ORDER BY depends_on_task_id, dependency_type""",
            ),
            (
                "reviews",
                "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at, id",
            ),
        ):
            values = rows(
                connection.execute(
                    query + " LIMIT ?",
                    (args.id, MAX_LIST_LIMIT + 1),
                )
            )
            if len(values) > MAX_LIST_LIMIT:
                truncated.append(name)
            result[name] = values[:MAX_LIST_LIMIT]
        result["truncated_sections"] = truncated
    return result


def assign(args: argparse.Namespace) -> dict[str, Any]:
    """Change task assignees with optimistic revision protection."""
    require_unique(args.add, "--add")
    require_unique(args.remove, "--remove")
    overlap = sorted(set(args.add) & set(args.remove))
    if overlap:
        fail(
            "invalid_arguments",
            "Task assignment cannot add and remove the same actor",
            EXIT_USAGE,
            {"actors": overlap},
        )
    if not args.add and not args.remove:
        fail(
            "invalid_arguments",
            "Task assignment requires at least one --add or --remove",
            EXIT_USAGE,
        )
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
        require_claim_ownership(connection, args.id, args.actor, args.session)
        for assignee in args.add:
            require_row(
                connection,
                "SELECT id FROM agents WHERE id = ?",
                (assignee,),
                f"agent {assignee}",
            )
        claim = connection.execute(
            "SELECT agent_id FROM task_claims WHERE task_id = ?",
            (args.id,),
        ).fetchone()
        if claim is not None and str(claim["agent_id"]) in args.remove:
            fail(
                "task_claim_owner_mismatch",
                "The active claim owner cannot be removed from task assignees",
                EXIT_CONFLICT,
                {"task": args.id, "claimed_by": claim["agent_id"]},
            )
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT agent_id FROM task_assignees WHERE task_id = ?",
                (args.id,),
            )
        }
        missing = sorted(set(args.remove) - existing)
        if missing:
            fail(
                "not_found",
                "Task assignee to remove was not found",
                EXIT_NOT_FOUND,
                {"task": args.id, "assignees": missing},
            )
        for assignee in args.add:
            connection.execute(
                """INSERT OR IGNORE INTO task_assignees(
                     task_id, agent_id, assigned_at
                   ) VALUES (?, ?, ?)""",
                (args.id, assignee, stamp),
            )
        for assignee in args.remove:
            connection.execute(
                "DELETE FROM task_assignees WHERE task_id = ? AND agent_id = ?",
                (args.id, assignee),
            )
        updated_assignees = sorted((existing | set(args.add)) - set(args.remove))
        if updated_assignees == sorted(existing):
            fail(
                "invalid_arguments",
                "Task assignment did not change any assignees",
                EXIT_USAGE,
                {"task": args.id},
            )
        cursor = connection.execute(
            """UPDATE tasks
               SET revision = revision + 1, updated_at = ?
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
        audit(
            connection,
            args.actor,
            "assign",
            "task",
            args.id,
            (
                f"add={','.join(sorted(args.add))}; "
                f"remove={','.join(sorted(args.remove))}; "
                f"revision {args.if_revision} -> {args.if_revision + 1}"
            ),
            session_id=args.session,
        )
    return {
        "id": args.id,
        "revision": args.if_revision + 1,
        "assignees": updated_assignees,
    }


def update(args: argparse.Namespace) -> dict[str, Any]:
    """Update task content without changing its workflow state."""
    changes = {
        "title": args.title,
        "description": args.description,
        "priority": args.priority,
        "tags": args.tags,
        "acceptance_criteria": args.acceptance,
        "next_steps": args.next_steps,
        "blocked_claims": args.blocked_claims,
    }
    selected = {key: value for key, value in changes.items() if value is not None}
    if not selected:
        fail(
            "invalid_arguments",
            "Task update requires at least one changed field",
            EXIT_USAGE,
        )
    connection = connect(discover_db(args.db))
    stamp = now()
    with transaction(connection):
        require_active_actor(connection, args.actor)
        if args.session:
            require_active_session(connection, args.session, args.actor)
        task = require_row(
            connection,
            "SELECT revision FROM tasks WHERE id = ?",
            (args.id,),
            f"task {args.id}",
        )
        if task["revision"] != args.if_revision:
            reject_stale_revision(args.id, args.if_revision, task["revision"])
        require_claim_ownership(connection, args.id, args.actor, args.session)
        assignments = ", ".join(f"{column} = ?" for column in selected)
        cursor = connection.execute(
            f"""UPDATE tasks
                SET {assignments}, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?""",
            (*selected.values(), stamp, args.id, args.if_revision),
        )
        if cursor.rowcount != 1:
            actual = int(
                connection.execute(
                    "SELECT revision FROM tasks WHERE id = ?", (args.id,)
                ).fetchone()[0]
            )
            reject_stale_revision(args.id, args.if_revision, actual)
        audit(
            connection,
            args.actor,
            "update",
            "task",
            args.id,
            (
                f"fields={','.join(sorted(selected))}; "
                f"revision {args.if_revision} -> {args.if_revision + 1}"
            ),
            session_id=args.session,
        )
    return {
        "id": args.id,
        "revision": args.if_revision + 1,
        "updated_fields": sorted(selected),
    }


def claim(args: argparse.Namespace) -> dict[str, Any]:
    if not args.session:
        fail(
            "session_required",
            "Task claims require an active session via --session"
            " or COORDINATION_SESSION",
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
            "SELECT agent_id, session_id, claimed_at FROM task_claims"
            " WHERE task_id = ?",
            (args.id,),
        ).fetchone()
        # The revision the claim UPDATE must match. Reaping an expired lease
        # first bumps it by one, so the caller's `if_revision` is checked
        # against what they observed, and the claim lands on the next revision.
        claim_revision = args.if_revision
        reaped_session: str | None = None
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
                    "reaped_session": None,
                }
                return result
            reject_stale_revision(args.id, args.if_revision, task["revision"])
        if task["status"] == "in_progress":
            # An exclusive claim is a lease, not a lock. When the holding
            # session has been silent past SESSION_LEASE_SECONDS it is reaped
            # here -- the same recovery `session recover` performs, attributed
            # to the claimant -- and the claim proceeds from `blocked`. A live
            # holder is never displaced. Checked inside the write transaction
            # so the holder cannot heartbeat between the check and the reap.
            holder = (
                connection.execute(
                    "SELECT id, last_seen_at FROM agent_sessions WHERE id = ?",
                    (active_claim["session_id"],),
                ).fetchone()
                if active_claim is not None
                else None
            )
            if holder is None or holder["last_seen_at"] > stale_cutoff(
                SESSION_LEASE_SECONDS
            ):
                fail(
                    "task_already_claimed",
                    f"Task {args.id} already has an active claim",
                    EXIT_CONFLICT,
                    {
                        "task": args.id,
                        "agent": active_claim["agent_id"] if active_claim else None,
                        "session_id": (
                            active_claim["session_id"] if active_claim else None
                        ),
                    },
                )
            recover_session_claims(
                connection,
                str(holder["id"]),
                actor=args.agent,
                reason=(
                    f"claim lease expired after {SESSION_LEASE_SECONDS} seconds"
                    f" of silence; reclaimed by {args.agent}"
                ),
                operator_session=args.session,
                stamp=stamp,
            )
            reaped_session = str(holder["id"])
            claim_revision = args.if_revision + 1
        elif task["status"] not in ("todo", "review", "blocked"):
            fail(
                "invalid_task_state",
                f"Task {args.id} cannot be claimed from status {task['status']}",
                EXIT_CONFLICT,
                {"task": args.id, "status": task["status"]},
            )
        connection.execute(
            """INSERT INTO task_claims(task_id, agent_id, session_id, claimed_at)
               VALUES (?, ?, ?, ?)""",
            (args.id, args.agent, args.session, stamp),
        )
        cursor = connection.execute(
            """UPDATE tasks
               SET status = 'in_progress', revision = revision + 1, updated_at = ?
               WHERE id = ? AND revision = ?""",
            (stamp, args.id, claim_revision),
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
            f"revision {claim_revision} -> {claim_revision + 1}"
            + (f"; reaped session {reaped_session}" if reaped_session else ""),
            session_id=args.session,
        )
        result = {
            "id": args.id,
            "status": "in_progress",
            "revision": claim_revision + 1,
            "agent": args.agent,
            "session_id": args.session,
            "claimed": True,
            "idempotent_replay": False,
            "reaped_session": reaped_session,
        }
    return result


def status(args: argparse.Namespace) -> dict[str, Any]:
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
        because = getattr(args, "because", None)
        if because:
            because = resolve_reference(connection, because)
        # `task release` is documented as an owned transition out of
        # in_progress, so it must not silently degrade into a plain status
        # change on a task nobody holds. Checked inside the transaction so the
        # claim cannot disappear between the check and the update.
        if getattr(args, "require_owned_claim", False) and task["status"] != (
            "in_progress"
        ):
            fail(
                "task_not_claimed",
                f"Task {args.id} is not claimed; release requires an"
                " in_progress task the actor and session own",
                EXIT_CONFLICT,
                {"task": args.id, "status": task["status"]},
            )
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
                f"Task {args.id} cannot transition from {task['status']}"
                f" to {args.status}",
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
                    f"Task {args.id} is claimed by session"
                    f" {active_claim['session_id']}",
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
                + (f"; because={because}" if because else "")
            ),
            session_id=args.session,
        )
    return {
        "id": args.id,
        "previous_status": task["status"],
        "status": args.status,
        "revision": args.if_revision + 1,
    }


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
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
    list_parser.add_argument(
        "--status",
        choices=STATUSES,
        action="append",
        help="Repeatable; tasks in any of the given statuses",
    )
    list_parser.add_argument("--assignee", type=identifier)
    list_parser.add_argument(
        "--tag",
        type=tag_token,
        help="Tasks whose comma-separated tags contain this token",
    )
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_tasks)

    show_parser = task.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)

    assign_parser = task.add_parser("assign")
    assign_parser.add_argument("id", type=identifier)
    assign_parser.add_argument("--actor", required=True, type=identifier)
    assign_parser.add_argument("--add", action="append", default=[], type=identifier)
    assign_parser.add_argument(
        "--remove",
        action="append",
        default=[],
        type=identifier,
    )
    assign_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    assign_parser.set_defaults(func=assign)

    update_parser = task.add_parser("update")
    update_parser.add_argument("id", type=identifier)
    update_parser.add_argument("--actor", required=True, type=identifier)
    update_parser.add_argument("--title", type=required_text)
    update_parser.add_argument("--description", type=optional_text)
    update_parser.add_argument("--priority", type=int, choices=range(1, 6))
    update_parser.add_argument("--tags", type=optional_text)
    update_parser.add_argument("--acceptance", type=optional_text)
    update_parser.add_argument("--next-steps", type=optional_text)
    update_parser.add_argument("--blocked-claims", type=optional_text)
    update_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    update_parser.set_defaults(func=update)

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
        "--because",
        type=because_reference,
        help="Record the review, decision, or message (TYPE:ID) that caused this",
    )
    status_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    status_parser.set_defaults(func=status, require_owned_claim=False)

    release_parser = task.add_parser(
        "release",
        help="Release the active claim and move the task out of in_progress",
    )
    release_parser.add_argument("id", type=identifier)
    release_parser.add_argument(
        "--to",
        dest="status",
        choices=("todo", "review", "blocked"),
        required=True,
    )
    release_parser.add_argument("--actor", required=True, type=identifier)
    release_parser.add_argument("--note", default="", type=optional_text)
    release_parser.add_argument(
        "--because",
        type=because_reference,
        help="Record the review, decision, or message (TYPE:ID) that caused this",
    )
    release_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    release_parser.set_defaults(func=status, require_owned_claim=True)
    register_history(task, "task")
