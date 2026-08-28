"""Archive selection: the destination directory and the eligible sets."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from coordination.core import coordination_root_for_database, fail
from coordination.entities.inbox import load_cursors
from coordination.errors import EXIT_ENVIRONMENT


def _archive_directory(target: Path) -> Path:
    root = coordination_root_for_database(target)
    directory = root / "archive"
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        fail(
            "environment_error",
            "Archive destination must be a real directory",
            EXIT_ENVIRONMENT,
            {"database": str(target), "archive_directory": str(directory)},
        )
    directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    if directory.resolve().parent != root.resolve():
        fail(
            "environment_error",
            "Archive destination escaped the coordination directory",
            EXIT_ENVIRONMENT,
            {"database": str(target), "archive_directory": str(directory)},
        )
    return directory


def _eligible_tasks(connection: sqlite3.Connection, cutoff: str) -> list[str]:
    """Done tasks past the cutoff that no record outside the set depends on."""
    return [
        str(row[0])
        for row in connection.execute(
            """SELECT t.id FROM tasks t
               WHERE t.status = 'done' AND t.updated_at <= ?
                 AND NOT EXISTS (
                   SELECT 1 FROM task_dependencies d
                   JOIN tasks o ON o.id = d.task_id
                   WHERE d.depends_on_task_id = t.id
                     AND NOT (o.status = 'done' AND o.updated_at <= ?)
                 )
               ORDER BY t.id""",
            (cutoff, cutoff),
        )
    ]


def _eligible_messages(connection: sqlite3.Connection, cutoff: str) -> list[str]:
    """Messages past the cutoff whose send event every active agent has read."""
    active = [
        str(row[0])
        for row in connection.execute(
            "SELECT id FROM agents WHERE status = 'active' ORDER BY id"
        )
    ]
    if not active:
        return []
    cursors = load_cursors(connection)
    floor = min(int(cursors.get(agent, 0)) for agent in active)
    if floor <= 0:
        return []
    return [
        str(row[0])
        for row in connection.execute(
            """SELECT m.id FROM messages m
               WHERE m.created_at <= ?
                 AND COALESCE(
                       (SELECT MAX(a.id) FROM audit_log a
                         WHERE a.action = 'send' AND a.object_type = 'message'
                           AND a.object_id = m.id),
                       0
                     ) BETWEEN 1 AND ?
               ORDER BY m.id""",
            (cutoff, floor),
        )
    ]
