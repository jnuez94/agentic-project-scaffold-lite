#!/usr/bin/env python3
"""Deterministic local coordination CLI backed by SQLite."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Any, Iterable


STATUSES = ("todo", "in_progress", "review", "blocked", "done")
REVIEW_DECISIONS = ("accepted", "conditionally_accepted", "changes_requested", "rejected")
DEPENDENCY_TYPES = ("blocks", "informs", "review_required", "evidence_required")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def rows(values: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(value) for value in values]


def discover_db(explicit: str | None, for_init: bool = False) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        coordination = directory / ".coordination"
        config = coordination / "config.yml"
        if config.is_file():
            database = "coordination.sqlite3"
            for line in config.read_text(encoding="utf-8").splitlines():
                if line.startswith("database:"):
                    database = line.split(":", 1)[1].strip()
            return coordination / database
    if for_init:
        return current / ".coordination" / "coordination.sqlite3"
    raise SystemExit("No SQLite coordination project found. Run from the project or pass --db PATH.")


def schema_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    candidates = (root / "sqlite" / "schema.sql", root / "assets" / "sqlite" / "schema.sql")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("SQLite schema not found in: " + ", ".join(str(candidate) for candidate in candidates))


def connect(path: Path, require_initialized: bool = True) -> sqlite3.Connection:
    if require_initialized and not path.is_file():
        raise SystemExit(f"Coordination database not found: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def audit(connection: sqlite3.Connection, actor: str | None, action: str, object_type: str, object_id: str, detail: str = "") -> None:
    connection.execute(
        "INSERT INTO audit_log(actor, action, object_type, object_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (actor, action, object_type, object_id, detail, now()),
    )


def require_row(connection: sqlite3.Connection, query: str, parameters: tuple[Any, ...], label: str) -> sqlite3.Row:
    value = connection.execute(query, parameters).fetchone()
    if value is None:
        raise SystemExit(f"Not found: {label}")
    return value


def command_init(args: argparse.Namespace) -> None:
    path = discover_db(args.db, for_init=True)
    connection = connect(path, require_initialized=False)
    with connection:
        connection.executescript(schema_path().read_text(encoding="utf-8"))
    emit({"database": str(path), "schema_version": 1, "status": "initialized"})


def command_agent_add(args: argparse.Namespace) -> None:
    path = discover_db(args.db)
    connection = connect(path)
    stamp = now()
    with connection:
        connection.execute(
            """INSERT INTO agents(
              id, name, role, status, responsibilities, goal, operating_style,
              decision_authority, review_authority, escalation_rules, unavailable_for,
              created_at, updated_at
            ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (args.id, args.name, args.role, args.responsibilities, args.goal, args.operating_style, args.decision_authority, args.review_authority, args.escalation_rules, args.unavailable_for, stamp, stamp),
        )
        audit(connection, args.id, "create", "agent", args.id)
    emit({"id": args.id, "status": "created"})


def command_agent_list(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM agents"
    parameters: tuple[Any, ...] = ()
    if not args.all:
        query += " WHERE status = ?"
        parameters = ("active",)
    query += " ORDER BY role, id"
    emit(rows(connection.execute(query, parameters)))


def command_task_create(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        connection.execute(
            """INSERT INTO tasks(
                id, title, description, priority, tags, acceptance_criteria, next_steps, blocked_claims,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (args.id, args.title, args.description, args.priority, args.tags, args.acceptance, args.next_steps, args.blocked_claims, args.actor, stamp, stamp),
        )
        for assignee in args.assignee:
            connection.execute(
                "INSERT INTO task_assignees(task_id, agent_id, assigned_at) VALUES (?, ?, ?)",
                (args.id, assignee, stamp),
            )
        audit(connection, args.actor, "create", "task", args.id)
    emit({"id": args.id, "status": "todo", "assignees": args.assignee})


def task_query() -> str:
    return """SELECT t.*,
        COALESCE(GROUP_CONCAT(DISTINCT ta.agent_id), '') AS assignees,
        COUNT(DISTINCT e.id) AS evidence_count
      FROM tasks t
      LEFT JOIN task_assignees ta ON ta.task_id = t.id
      LEFT JOIN task_evidence e ON e.task_id = t.id"""


def command_task_list(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = task_query()
    conditions: list[str] = []
    parameters: list[Any] = []
    if args.status:
        conditions.append("t.status = ?")
        parameters.append(args.status)
    if args.assignee:
        conditions.append("EXISTS (SELECT 1 FROM task_assignees x WHERE x.task_id = t.id AND x.agent_id = ?)")
        parameters.append(args.assignee)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " GROUP BY t.id ORDER BY t.priority, t.updated_at, t.id"
    emit(rows(connection.execute(query, parameters)))


def command_task_show(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    task = require_row(connection, task_query() + " WHERE t.id = ? GROUP BY t.id", (args.id,), f"task {args.id}")
    result = dict(task)
    result["evidence"] = rows(connection.execute("SELECT * FROM task_evidence WHERE task_id = ? ORDER BY created_at", (args.id,)))
    result["dependencies"] = rows(connection.execute("SELECT * FROM task_dependencies WHERE task_id = ? ORDER BY depends_on_task_id", (args.id,)))
    result["reviews"] = rows(connection.execute("SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at", (args.id,)))
    emit(result)


def command_task_claim(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        require_row(connection, "SELECT id FROM agents WHERE id = ? AND status = 'active'", (args.agent,), f"active agent {args.agent}")
        task = require_row(connection, "SELECT status FROM tasks WHERE id = ?", (args.id,), f"task {args.id}")
        if task["status"] not in ("todo", "in_progress"):
            raise SystemExit(f"Task {args.id} cannot be claimed from status {task['status']}")
        connection.execute(
            "INSERT OR IGNORE INTO task_assignees(task_id, agent_id, assigned_at) VALUES (?, ?, ?)",
            (args.id, args.agent, stamp),
        )
        connection.execute("UPDATE tasks SET status = 'in_progress', updated_at = ? WHERE id = ?", (stamp, args.id))
        audit(connection, args.agent, "claim", "task", args.id)
    emit({"id": args.id, "status": "in_progress", "agent": args.agent})


def command_task_status(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        task = require_row(connection, "SELECT status FROM tasks WHERE id = ?", (args.id,), f"task {args.id}")
        connection.execute(
            "UPDATE tasks SET status = ?, notes = CASE WHEN ? = '' THEN notes ELSE ? END, updated_at = ? WHERE id = ?",
            (args.status, args.note, args.note, stamp, args.id),
        )
        audit(connection, args.actor, "status", "task", args.id, f"{task['status']} -> {args.status}")
    emit({"id": args.id, "previous_status": task["status"], "status": args.status})


def command_evidence_add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
        require_row(connection, "SELECT id FROM tasks WHERE id = ?", (args.task,), f"task {args.task}")
        cursor = connection.execute(
            "INSERT INTO task_evidence(task_id, uri, evidence_type, added_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (args.task, args.uri, args.type, args.actor, now()),
        )
        audit(connection, args.actor, "add", "evidence", str(cursor.lastrowid), args.task)
    emit({"id": cursor.lastrowid, "task_id": args.task, "status": "created"})


def command_evidence_list(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    emit(rows(connection.execute("SELECT * FROM task_evidence WHERE task_id = ? ORDER BY created_at", (args.task,))))


def command_dependency_add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
        connection.execute(
            "INSERT INTO task_dependencies(task_id, depends_on_task_id, dependency_type, rationale, created_at) VALUES (?, ?, ?, ?, ?)",
            (args.task, args.depends_on, args.type, args.rationale, now()),
        )
        audit(connection, args.actor, "add", "dependency", f"{args.task}:{args.depends_on}:{args.type}")
    emit({"task_id": args.task, "depends_on": args.depends_on, "type": args.type, "status": "active"})


def command_dependency_resolve(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
        cursor = connection.execute(
            "UPDATE task_dependencies SET status = 'resolved' WHERE task_id = ? AND depends_on_task_id = ? AND dependency_type = ?",
            (args.task, args.depends_on, args.type),
        )
        if cursor.rowcount != 1:
            raise SystemExit("Dependency not found")
        audit(connection, args.actor, "resolve", "dependency", f"{args.task}:{args.depends_on}:{args.type}")
    emit({"task_id": args.task, "depends_on": args.depends_on, "type": args.type, "status": "resolved"})


def command_review_add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
        connection.execute(
            """INSERT INTO reviews(
              id, task_id, reviewer_id, artifact_uri, scope, decision, accepted_items,
              required_changes, remaining_risks, blocked_claims, follow_up_tasks, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (args.id, args.task, args.reviewer, args.artifact, args.scope, args.decision, args.accepted_items, args.required_changes, args.risks, args.blocked_claims, args.follow_up_tasks, now()),
        )
        audit(connection, args.reviewer, "create", "review", args.id, args.decision)
    emit({"id": args.id, "decision": args.decision, "status": "created"})


def command_review_list(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    if args.task:
        result = connection.execute("SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at", (args.task,))
    else:
        result = connection.execute("SELECT * FROM reviews ORDER BY created_at")
    emit(rows(result))


def command_decision_add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        connection.execute(
            """INSERT INTO decisions(
              id, title, owner_id, status, context, decision, options_considered,
              implications, evidence, blocked_claims, review_required, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (args.id, args.title, args.owner, args.status, args.context, args.decision, args.options, args.implications, args.evidence, args.blocked_claims, args.review_required, stamp, stamp),
        )
        audit(connection, args.owner, "create", "decision", args.id, args.status)
    emit({"id": args.id, "status": args.status})


def command_decision_list(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    emit(rows(connection.execute("SELECT * FROM decisions ORDER BY created_at, id")))


def command_message_send(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
        connection.execute(
            "INSERT INTO messages(id, sender_id, recipient, task_id, body, tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (args.id, args.sender, args.recipient, args.task, args.body, args.tags, now()),
        )
        audit(connection, args.sender, "send", "message", args.id, args.recipient)
    emit({"id": args.id, "status": "sent"})


def command_message_list(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM messages"
    parameters: tuple[Any, ...] = ()
    if args.recipient:
        query += " WHERE recipient IN (?, 'team')"
        parameters = (args.recipient,)
    query += " ORDER BY created_at"
    emit(rows(connection.execute(query, parameters)))


def command_artifact_add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        connection.execute(
            """INSERT INTO artifacts(
              id, uri, owner_id, type, status, usage_boundaries, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (args.id, args.uri, args.owner, args.type, args.status, args.usage_boundaries, stamp, stamp),
        )
        for task_id in args.task:
            connection.execute("INSERT INTO artifact_tasks(artifact_id, task_id) VALUES (?, ?)", (args.id, task_id))
        for reviewer in args.reviewer:
            connection.execute("INSERT INTO artifact_reviewers(artifact_id, reviewer_id) VALUES (?, ?)", (args.id, reviewer))
        audit(connection, args.owner, "create", "artifact", args.id, args.uri)
    emit({"id": args.id, "status": args.status})


def command_artifact_list(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = """SELECT a.*,
      COALESCE(GROUP_CONCAT(DISTINCT at.task_id), '') AS related_tasks,
      COALESCE(GROUP_CONCAT(DISTINCT ar.reviewer_id), '') AS reviewers
      FROM artifacts a
      LEFT JOIN artifact_tasks at ON at.artifact_id = a.id
      LEFT JOIN artifact_reviewers ar ON ar.artifact_id = a.id"""
    parameters: tuple[Any, ...] = ()
    if args.status:
        query += " WHERE a.status = ?"
        parameters = (args.status,)
    query += " GROUP BY a.id ORDER BY a.updated_at, a.id"
    emit(rows(connection.execute(query, parameters)))


def command_artifact_status(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
        cursor = connection.execute("UPDATE artifacts SET status = ?, updated_at = ? WHERE id = ?", (args.status, now(), args.id))
        if cursor.rowcount != 1:
            raise SystemExit(f"Not found: artifact {args.id}")
        audit(connection, args.actor, "status", "artifact", args.id, args.status)
    emit({"id": args.id, "status": args.status})


def command_escalation_add(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    stamp = now()
    with connection:
        connection.execute(
            """INSERT INTO escalations(
              id, raised_by, owner, status, related_tasks, needed_by, issue,
              requested_decision, created_at, updated_at
            ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)""",
            (args.id, args.raised_by, args.owner, args.related_tasks, args.needed_by, args.issue, args.requested_decision, stamp, stamp),
        )
        audit(connection, args.raised_by, "create", "escalation", args.id)
    emit({"id": args.id, "status": "open"})


def command_escalation_list(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    query = "SELECT * FROM escalations"
    parameters: tuple[Any, ...] = ()
    if args.status:
        query += " WHERE status = ?"
        parameters = (args.status,)
    query += " ORDER BY created_at, id"
    emit(rows(connection.execute(query, parameters)))


def command_escalation_resolve(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    with connection:
        cursor = connection.execute(
            "UPDATE escalations SET status = ?, resolution = ?, follow_up_tasks = ?, updated_at = ? WHERE id = ?",
            (args.status, args.resolution, args.follow_up_tasks, now(), args.id),
        )
        if cursor.rowcount != 1:
            raise SystemExit(f"Not found: escalation {args.id}")
        audit(connection, args.actor, "resolve", "escalation", args.id, args.status)
    emit({"id": args.id, "status": args.status})


def command_health(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.stale_days)).replace(microsecond=0).isoformat()
    report = {
        "unowned_tasks": rows(connection.execute(
            "SELECT * FROM tasks t WHERE status <> 'done' AND NOT EXISTS (SELECT 1 FROM task_assignees a WHERE a.task_id = t.id) ORDER BY priority, id"
        )),
        "stale_tasks": rows(connection.execute(
            "SELECT * FROM tasks WHERE status IN ('in_progress', 'review', 'blocked') AND updated_at < ? ORDER BY updated_at", (cutoff,)
        )),
        "active_blockers": rows(connection.execute(
            "SELECT * FROM tasks WHERE status = 'blocked' ORDER BY priority, updated_at"
        )),
        "done_without_evidence": rows(connection.execute(
            "SELECT * FROM tasks t WHERE status = 'done' AND NOT EXISTS (SELECT 1 FROM task_evidence e WHERE e.task_id = t.id)"
        )),
        "open_escalations": rows(connection.execute(
            "SELECT * FROM escalations WHERE status IN ('open', 'in_review') ORDER BY created_at"
        )),
    }
    report["healthy"] = not any(report[key] for key in report if key != "healthy")
    emit(report)


def command_export(args: argparse.Namespace) -> None:
    connection = connect(discover_db(args.db))
    task_values = rows(connection.execute(task_query() + " GROUP BY t.id ORDER BY t.priority, t.id"))
    lines = ["# Coordination Export", "", f"Generated: {now()}", "", "## Tasks", ""]
    for task in task_values:
        lines.extend([
            f"### {task['id']}: {task['title']}", "",
            f"- Status: `{task['status']}`", f"- Priority: {task['priority']}",
            f"- Assignees: {task['assignees'] or 'unassigned'}", f"- Evidence records: {task['evidence_count']}", "",
        ])
    content = "\n".join(lines) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        if output.exists() and not args.force:
            raise SystemExit(f"Export already exists: {output}. Pass --force to replace it.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        emit({"output": str(output), "tasks": len(task_values)})
    else:
        print(content, end="")


def command_backup(args: argparse.Namespace) -> None:
    source = discover_db(args.db)
    destination = Path(args.output).expanduser().resolve()
    if source == destination:
        raise SystemExit("Backup destination must differ from the source database")
    if destination.exists() and not args.force:
        raise SystemExit(f"Backup already exists: {destination}. Pass --force to replace it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = connect(source)
    destination_connection = sqlite3.connect(destination)
    with destination_connection:
        source_connection.backup(destination_connection)
    destination_connection.close()
    emit({"backup": str(destination), "source": str(source)})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coordination", description="Local multi-agent coordination backed by SQLite")
    parser.add_argument("--db", help="Path to coordination.sqlite3; otherwise discover the nearest project")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Initialize the database")
    init.set_defaults(func=command_init)

    agent = commands.add_parser("agent", help="Manage agents").add_subparsers(dest="agent_command", required=True)
    agent_add = agent.add_parser("add")
    agent_add.add_argument("--id", required=True)
    agent_add.add_argument("--name", required=True)
    agent_add.add_argument("--role", required=True)
    agent_add.add_argument("--responsibilities", default="")
    agent_add.add_argument("--goal", default="")
    agent_add.add_argument("--operating-style", default="")
    agent_add.add_argument("--decision-authority", default="")
    agent_add.add_argument("--review-authority", default="")
    agent_add.add_argument("--escalation-rules", default="")
    agent_add.add_argument("--unavailable-for", default="")
    agent_add.set_defaults(func=command_agent_add)
    agent_list = agent.add_parser("list")
    agent_list.add_argument("--all", action="store_true")
    agent_list.set_defaults(func=command_agent_list)

    task = commands.add_parser("task", help="Manage tasks").add_subparsers(dest="task_command", required=True)
    task_create = task.add_parser("create")
    task_create.add_argument("--id", required=True)
    task_create.add_argument("--title", required=True)
    task_create.add_argument("--description", default="")
    task_create.add_argument("--priority", type=int, choices=range(1, 6), default=3)
    task_create.add_argument("--tags", default="")
    task_create.add_argument("--acceptance", default="")
    task_create.add_argument("--next-steps", default="")
    task_create.add_argument("--blocked-claims", default="")
    task_create.add_argument("--actor")
    task_create.add_argument("--assignee", action="append", default=[])
    task_create.set_defaults(func=command_task_create)
    task_list = task.add_parser("list")
    task_list.add_argument("--status", choices=STATUSES)
    task_list.add_argument("--assignee")
    task_list.set_defaults(func=command_task_list)
    task_show = task.add_parser("show")
    task_show.add_argument("id")
    task_show.set_defaults(func=command_task_show)
    task_claim = task.add_parser("claim")
    task_claim.add_argument("id")
    task_claim.add_argument("--agent", required=True)
    task_claim.set_defaults(func=command_task_claim)
    task_status = task.add_parser("status")
    task_status.add_argument("id")
    task_status.add_argument("status", choices=STATUSES)
    task_status.add_argument("--actor")
    task_status.add_argument("--note", default="")
    task_status.set_defaults(func=command_task_status)

    evidence = commands.add_parser("evidence", help="Manage task evidence").add_subparsers(dest="evidence_command", required=True)
    evidence_add = evidence.add_parser("add")
    evidence_add.add_argument("--task", required=True)
    evidence_add.add_argument("--uri", required=True)
    evidence_add.add_argument("--type", default="artifact")
    evidence_add.add_argument("--actor")
    evidence_add.set_defaults(func=command_evidence_add)
    evidence_list = evidence.add_parser("list")
    evidence_list.add_argument("--task", required=True)
    evidence_list.set_defaults(func=command_evidence_list)

    dependency = commands.add_parser("dependency", help="Manage dependencies").add_subparsers(dest="dependency_command", required=True)
    dependency_add = dependency.add_parser("add")
    dependency_add.add_argument("--task", required=True)
    dependency_add.add_argument("--depends-on", required=True)
    dependency_add.add_argument("--type", choices=DEPENDENCY_TYPES, default="blocks")
    dependency_add.add_argument("--rationale", default="")
    dependency_add.add_argument("--actor")
    dependency_add.set_defaults(func=command_dependency_add)
    dependency_resolve = dependency.add_parser("resolve")
    dependency_resolve.add_argument("--task", required=True)
    dependency_resolve.add_argument("--depends-on", required=True)
    dependency_resolve.add_argument("--type", choices=DEPENDENCY_TYPES, default="blocks")
    dependency_resolve.add_argument("--actor")
    dependency_resolve.set_defaults(func=command_dependency_resolve)

    review = commands.add_parser("review", help="Manage reviews").add_subparsers(dest="review_command", required=True)
    review_add = review.add_parser("add")
    review_add.add_argument("--id", required=True)
    review_add.add_argument("--task")
    review_add.add_argument("--reviewer", required=True)
    review_add.add_argument("--artifact", required=True)
    review_add.add_argument("--scope", required=True)
    review_add.add_argument("--decision", choices=REVIEW_DECISIONS, required=True)
    review_add.add_argument("--accepted-items", default="")
    review_add.add_argument("--required-changes", default="")
    review_add.add_argument("--risks", default="")
    review_add.add_argument("--blocked-claims", default="")
    review_add.add_argument("--follow-up-tasks", default="")
    review_add.set_defaults(func=command_review_add)
    review_list = review.add_parser("list")
    review_list.add_argument("--task")
    review_list.set_defaults(func=command_review_list)

    decision = commands.add_parser("decision", help="Manage decisions").add_subparsers(dest="decision_command", required=True)
    decision_add = decision.add_parser("add")
    decision_add.add_argument("--id", required=True)
    decision_add.add_argument("--title", required=True)
    decision_add.add_argument("--owner", required=True)
    decision_add.add_argument("--status", choices=("proposed", "accepted", "superseded", "rejected"), default="proposed")
    decision_add.add_argument("--context", required=True)
    decision_add.add_argument("--decision", required=True)
    decision_add.add_argument("--options", default="")
    decision_add.add_argument("--implications", default="")
    decision_add.add_argument("--evidence", default="")
    decision_add.add_argument("--blocked-claims", default="")
    decision_add.add_argument("--review-required", default="")
    decision_add.set_defaults(func=command_decision_add)
    decision_list = decision.add_parser("list")
    decision_list.set_defaults(func=command_decision_list)

    message = commands.add_parser("message", help="Manage messages").add_subparsers(dest="message_command", required=True)
    message_send = message.add_parser("send")
    message_send.add_argument("--id", required=True)
    message_send.add_argument("--sender", required=True)
    message_send.add_argument("--recipient", required=True)
    message_send.add_argument("--task")
    message_send.add_argument("--body", required=True)
    message_send.add_argument("--tags", default="")
    message_send.set_defaults(func=command_message_send)
    message_list = message.add_parser("list")
    message_list.add_argument("--recipient")
    message_list.set_defaults(func=command_message_list)

    artifact = commands.add_parser("artifact", help="Manage artifacts").add_subparsers(dest="artifact_command", required=True)
    artifact_add = artifact.add_parser("add")
    artifact_add.add_argument("--id", required=True)
    artifact_add.add_argument("--uri", required=True)
    artifact_add.add_argument("--owner", required=True)
    artifact_add.add_argument("--type", required=True)
    artifact_add.add_argument("--status", choices=("draft", "review", "accepted", "superseded"), default="draft")
    artifact_add.add_argument("--usage-boundaries", default="")
    artifact_add.add_argument("--task", action="append", default=[])
    artifact_add.add_argument("--reviewer", action="append", default=[])
    artifact_add.set_defaults(func=command_artifact_add)
    artifact_list = artifact.add_parser("list")
    artifact_list.add_argument("--status", choices=("draft", "review", "accepted", "superseded"))
    artifact_list.set_defaults(func=command_artifact_list)
    artifact_status = artifact.add_parser("status")
    artifact_status.add_argument("id")
    artifact_status.add_argument("status", choices=("draft", "review", "accepted", "superseded"))
    artifact_status.add_argument("--actor")
    artifact_status.set_defaults(func=command_artifact_status)

    escalation = commands.add_parser("escalation", help="Manage escalations").add_subparsers(dest="escalation_command", required=True)
    escalation_add = escalation.add_parser("add")
    escalation_add.add_argument("--id", required=True)
    escalation_add.add_argument("--raised-by", required=True)
    escalation_add.add_argument("--owner", required=True)
    escalation_add.add_argument("--related-tasks", default="")
    escalation_add.add_argument("--needed-by")
    escalation_add.add_argument("--issue", required=True)
    escalation_add.add_argument("--requested-decision", required=True)
    escalation_add.set_defaults(func=command_escalation_add)
    escalation_list = escalation.add_parser("list")
    escalation_list.add_argument("--status", choices=("open", "in_review", "resolved", "closed_no_action"))
    escalation_list.set_defaults(func=command_escalation_list)
    escalation_resolve = escalation.add_parser("resolve")
    escalation_resolve.add_argument("id")
    escalation_resolve.add_argument("--status", choices=("resolved", "closed_no_action"), default="resolved")
    escalation_resolve.add_argument("--resolution", required=True)
    escalation_resolve.add_argument("--follow-up-tasks", default="")
    escalation_resolve.add_argument("--actor")
    escalation_resolve.set_defaults(func=command_escalation_resolve)

    health = commands.add_parser("health", help="Report coordination health")
    health.add_argument("--stale-days", type=int, default=7)
    health.set_defaults(func=command_health)
    export = commands.add_parser("export", help="Export a Markdown report")
    export.add_argument("--output")
    export.add_argument("--force", action="store_true")
    export.set_defaults(func=command_export)
    backup = commands.add_parser("backup", help="Create a consistent SQLite backup")
    backup.add_argument("--output", required=True)
    backup.add_argument("--force", action="store_true")
    backup.set_defaults(func=command_backup)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except sqlite3.IntegrityError as error:
        print(f"Coordination constraint failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
