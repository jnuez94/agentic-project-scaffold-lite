#!/usr/bin/env python3
"""Qualify archive: cutoff selection, the verified archive file, live deletion.

The ledger is never archived: audit and change rows for archived records stay
in the live database, and the deletion itself is one audited operation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.entities import maintenance  # noqa: E402
from coordination.errors import CoordinationError  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


OLD = "2026-01-01T00:00:00+00:00"


def namespace(database: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "db": str(database),
        "actor": "alice",
        "older_than_days": 30,
        "force": True,
        "session": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def seed(database: Path) -> CoordinationService:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    for actor in ("alice", "bob"):
        service.invoke("agent_add", {"id": actor, "name": actor, "role": "r"})
    service.invoke(
        "session_start",
        {"id": "run-1", "agent": "alice", "harness": "h", "model": "m"},
    )
    return service


def make_done_task(service: CoordinationService, task_id: str) -> None:
    session = CoordinationService(db=service.db, session="run-1")
    revision = 1
    service.invoke("task_create", {"id": task_id, "title": task_id, "actor": "alice"})
    session.invoke("task_claim", {"id": task_id, "agent": "alice", "if_revision": 1})
    revision = 2
    session.invoke(
        "task_status",
        {"id": task_id, "status": "review", "actor": "alice", "if_revision": revision},
    )
    service.invoke(
        "evidence_add", {"task": task_id, "uri": "evidence://done", "actor": "alice"}
    )
    service.invoke(
        "task_status",
        {"id": task_id, "status": "done", "actor": "alice", "if_revision": 3},
    )


def age_task(database: Path, task_id: str) -> None:
    with sqlite3.connect(database) as raw:
        raw.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (OLD, task_id))


def age_messages(database: Path) -> None:
    with sqlite3.connect(database) as raw:
        raw.execute("UPDATE messages SET created_at = ?", (OLD,))


def mark_all_read(service: CoordinationService, database: Path) -> None:
    with sqlite3.connect(database) as raw:
        head = int(raw.execute("SELECT MAX(id) FROM audit_log").fetchone()[0])
    for agent in ("alice", "bob"):
        service.invoke("inbox_mark_read", {"agent": agent, "cursor": head})


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def test_archive_moves_closed_records(database: Path) -> None:
    service = seed(database)
    make_done_task(service, "T-OLD")
    make_done_task(service, "T-NEW")
    make_done_task(service, "T-DEP")
    service.invoke("task_create", {"id": "T-LIVE", "title": "live", "actor": "alice"})
    service.invoke(
        "dependency_add",
        {"task": "T-LIVE", "depends_on": "T-DEP", "actor": "alice", "type": "informs"},
    )
    for message_id, task in (
        ("M-READ", None),
        ("M-TASK", "T-OLD"),
        ("M-LIVE-TASK", "T-NEW"),
    ):
        service.invoke(
            "message_send",
            {
                "id": message_id,
                "sender": "alice",
                "recipient": "team",
                "body": "b",
                "task": task,
            },
        )
    mark_all_read(service, database)
    service.invoke(
        "message_send",
        {"id": "M-UNREAD", "sender": "alice", "recipient": "team", "body": "b"},
    )
    age_task(database, "T-OLD")
    age_task(database, "T-DEP")
    age_messages(database)

    result = maintenance.archive(namespace(database))
    assert result["tasks"] == 1 and result["messages"] == 3, result
    archive_path = Path(str(result["archive"]))
    assert archive_path.is_file()
    assert archive_path.parent.name == "archive"

    # Live database: archived records gone, everything else intact.
    live = {
        str(row[0]) for row in sqlite3.connect(database).execute("SELECT id FROM tasks")
    }
    assert live == {"T-NEW", "T-DEP", "T-LIVE"}
    with sqlite3.connect(database) as raw:
        remaining = {str(row[0]) for row in raw.execute("SELECT id FROM messages")}
        ledger = int(
            raw.execute(
                "SELECT COUNT(*) FROM audit_log WHERE object_type = 'task'"
                " AND object_id = 'T-OLD'"
            ).fetchone()[0]
        )
        archived_events = int(
            raw.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'archive'"
            ).fetchone()[0]
        )
    assert remaining == {"M-UNREAD"}
    assert ledger > 0, "the ledger must keep archived records' audit rows"
    assert archived_events == 1

    # Archive file: canonical schema, readable with ordinary tooling.
    reader = CoordinationService(db=str(archive_path))
    archived_task = reader.invoke("task_show", {"id": "T-OLD"})
    assert archived_task["status"] == "done"
    with sqlite3.connect(archive_path) as raw:
        agents = int(raw.execute("SELECT COUNT(*) FROM agents").fetchone()[0])
        task_links = {
            str(row[0]): row[1]
            for row in raw.execute("SELECT id, task_id FROM messages")
        }
        archive_ledger = int(
            raw.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        )
    assert agents == 2
    assert task_links == {"M-READ": None, "M-TASK": "T-OLD", "M-LIVE-TASK": None}
    assert archive_ledger == 0, "the archive carries records, never the ledger"

    doctor = service.invoke("doctor", {})
    assert doctor["healthy"] is True

    # A second run finds nothing and writes no file.
    again = maintenance.archive(namespace(database))
    assert again["tasks"] == 0 and again["messages"] == 0
    assert again["archive"] is None
    assert len(list(archive_path.parent.glob("archive-*.sqlite3"))) == 1


def test_unread_and_recent_records_are_kept(database: Path) -> None:
    service = seed(database)
    make_done_task(service, "T-RECENT")
    service.invoke(
        "message_send",
        {"id": "M-OLD-UNREAD", "sender": "alice", "recipient": "bob", "body": "b"},
    )
    age_messages(database)
    result = maintenance.archive(namespace(database))
    assert result["tasks"] == 0 and result["messages"] == 0
    assert result["archive"] is None


def test_confirmation_required(database: Path) -> None:
    service = seed(database)
    make_done_task(service, "T-1")
    age_task(database, "T-1")
    expect(
        "confirmation_required",
        lambda: maintenance.archive(namespace(database, force=False)),
    )
    assert service.invoke("task_show", {"id": "T-1"})["id"] == "T-1"


def test_cli_parity(database: Path) -> None:
    service = seed(database)
    make_done_task(service, "T-1")
    age_task(database, "T-1")
    completed = subprocess.run(
        [
            str(ROOT / "scripts" / "coordination.py"),
            "--db",
            str(database),
            "archive",
            "--older-than-days",
            "30",
            "--actor",
            "alice",
            "--force",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    envelope = json.loads(completed.stdout)
    assert envelope["ok"] is True
    assert envelope["data"]["tasks"] == 1
    assert "audit_range" in envelope


def main() -> int:
    for test in (
        test_archive_moves_closed_records,
        test_unread_and_recent_records_are_kept,
        test_confirmation_required,
        test_cli_parity,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-archive-") as name:
            test(Path(name) / ".coordination" / "coordination.sqlite3")
    print("Archive qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
