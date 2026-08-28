"""Cutoff-based archival of closed records into a verified archive database.

Archival never touches the ledger: audit and change rows for archived records
stay in the live database. Each run publishes one immutable archive file
carrying the canonical schema, readable with the ordinary tooling.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile

from coordination.core import (
    advisory_file_lock,
    audit,
    canonical_schema_sql,
    check_database_integrity,
    database_lock_path,
    discover_db,
    ensure_supported_schema,
    expected_schema_definitions,
    fsync_directory,
    fsync_file,
    require_active_actor,
    transaction,
    validate_database_operational_files,
)
from coordination.entities._maintenance_archive_select import (
    _archive_directory,
    _eligible_messages,
    _eligible_tasks,
)
from coordination.entities._maintenance_backup import _raw_connection
from coordination.errors import EXIT_NOT_FOUND, EXIT_USAGE, fail


GUARD_TRIGGER = "task_insert_done_requires_evidence"


def _published_archive(
    connection: sqlite3.Connection,
    target: Path,
    directory: Path,
    stamp: str,
) -> str:
    """Copy the archived sets into a fresh canonical-schema file and verify it."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".archive-{stamp}.",
        suffix=".tmp",
        dir=directory,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        schema_connection = sqlite3.connect(temporary)
        try:
            schema_connection.executescript(canonical_schema_sql())
            # Archived tasks are done by definition; the creation guard is
            # removed for the copy and recreated from its canonical text.
            schema_connection.execute(f"DROP TRIGGER {GUARD_TRIGGER}")
        finally:
            schema_connection.close()
        connection.execute("ATTACH DATABASE ? AS archive", (str(temporary),))
        try:
            with transaction(connection):
                connection.execute("INSERT INTO archive.agents SELECT * FROM agents")
                connection.execute(
                    "INSERT INTO archive.tasks SELECT * FROM tasks"
                    " WHERE id IN (SELECT id FROM temp.archived_tasks)"
                )
                for satellite, column in (
                    ("task_assignees", "task_id"),
                    ("task_evidence", "task_id"),
                ):
                    connection.execute(
                        f"INSERT INTO archive.{satellite} SELECT * FROM {satellite}"
                        f" WHERE {column} IN (SELECT id FROM temp.archived_tasks)"
                    )
                connection.execute(
                    "INSERT INTO archive.task_dependencies"
                    " SELECT * FROM task_dependencies"
                    " WHERE task_id IN (SELECT id FROM temp.archived_tasks)"
                    " AND depends_on_task_id IN (SELECT id FROM temp.archived_tasks)"
                )
                connection.execute(
                    """INSERT INTO archive.messages
                       SELECT m.id, m.sender_id, m.recipient,
                              CASE WHEN m.task_id IN
                                     (SELECT id FROM temp.archived_tasks)
                                   THEN m.task_id ELSE NULL END,
                              m.body, m.tags, m.created_at
                       FROM messages m
                       WHERE m.id IN (SELECT id FROM temp.archived_messages)"""
                )
        finally:
            connection.execute("DETACH DATABASE archive")
        finish = _raw_connection(temporary)
        try:
            finish.execute(expected_schema_definitions()[("trigger", GUARD_TRIGGER)][1])
            ensure_supported_schema(finish)
            check_database_integrity(finish)
        finally:
            finish.close()
        os.chmod(temporary, 0o600)
        fsync_file(temporary)
        destination = directory / f"archive-{stamp}.sqlite3"
        os.replace(temporary, destination)
        fsync_directory(directory)
    finally:
        temporary.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{temporary}{suffix}").unlink(missing_ok=True)
    return str(destination)


def archive(args: argparse.Namespace) -> dict[str, object]:
    if not args.force:
        fail(
            "confirmation_required",
            "Archive deletes archived records from the live database;"
            " pass --force to confirm",
            EXIT_USAGE,
        )
    target = discover_db(args.db)
    if not target.is_file():
        fail(
            "not_found",
            f"Not found: database {target}",
            EXIT_NOT_FOUND,
            {"database": str(target)},
        )
    validate_database_operational_files(target)
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=args.older_than_days)
    ).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    # The exclusive lock freezes every canonical client across eligibility,
    # the copy, and the deletion, so the archive and the live database can
    # never disagree about which records moved.
    with advisory_file_lock(database_lock_path(target), exclusive=True):
        connection = _raw_connection(target)
        try:
            ensure_supported_schema(connection)
            check_database_integrity(connection)
            require_active_actor(connection, args.actor)
            tasks = _eligible_tasks(connection, cutoff)
            messages = _eligible_messages(connection, cutoff)
            if not tasks and not messages:
                return {
                    "database": str(target),
                    "archive": None,
                    "tasks": 0,
                    "messages": 0,
                    "cutoff": cutoff,
                    "audit_recorded": False,
                }
            connection.execute("CREATE TEMP TABLE archived_tasks(id TEXT PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO temp.archived_tasks VALUES (?)",
                [(task,) for task in tasks],
            )
            connection.execute(
                "CREATE TEMP TABLE archived_messages(id TEXT PRIMARY KEY)"
            )
            connection.executemany(
                "INSERT INTO temp.archived_messages VALUES (?)",
                [(message,) for message in messages],
            )
            # The temp-table loads above opened sqlite3's implicit
            # transaction; close it so the archive build owns its own.
            connection.commit()
            directory = _archive_directory(target)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            archive_path = _published_archive(connection, target, directory, stamp)
            with transaction(connection):
                connection.execute(
                    "DELETE FROM messages"
                    " WHERE id IN (SELECT id FROM temp.archived_messages)"
                )
                connection.execute(
                    "DELETE FROM tasks WHERE id IN (SELECT id FROM temp.archived_tasks)"
                )
                audit(
                    connection,
                    args.actor,
                    "archive",
                    "database",
                    str(target),
                    (
                        f"tasks={len(tasks)}; messages={len(messages)};"
                        f" archive {archive_path}"
                    ),
                    session_id=args.session,
                )
        finally:
            connection.close()
    return {
        "database": str(target),
        "archive": archive_path,
        "tasks": len(tasks),
        "messages": len(messages),
        "cutoff": cutoff,
        "audit_recorded": True,
    }
