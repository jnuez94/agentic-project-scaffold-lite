#!/usr/bin/env python3
"""Qualify the change_log surface: field diffs recorded with their audit row.

Change rows are written in the same transaction as the mutation and its audit
row, only for fields whose value actually changed. Creates record nothing,
revision bookkeeping is not a field, and `message redact` writes no change
rows because the old value would preserve what redaction removes.
"""

from __future__ import annotations

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
from coordination.service import CoordinationService  # noqa: E402


def cli(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "scripts" / "coordination.py"), "--db", str(database), *arguments],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def seed(database: Path) -> CoordinationService:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    for actor in ("alice", "bob"):
        service.invoke("agent_add", {"id": actor, "name": actor, "role": "r"})
    return service


def audit_id_of(
    service: CoordinationService, action: str, object_type: str, object_id: str
) -> int:
    rows = service.invoke(
        "audit_list",
        {"action": action, "object_type": object_type, "object_id": object_id},
    )
    assert rows, (action, object_type, object_id)
    return int(rows[-1]["id"])


def change_rows(
    service: CoordinationService, audit_id: int
) -> list[tuple[str, object, object]]:
    rows = service.invoke("audit_changes", {"audit_id": audit_id})
    assert all(row["audit_id"] == audit_id for row in rows)
    return [(row["field"], row["old_value"], row["new_value"]) for row in rows]


def test_task_mutations(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "task_create",
        {"id": "T-1", "title": "t", "actor": "alice", "assignee": ["alice"]},
    )
    create_id = audit_id_of(service, "create", "task", "T-1")
    assert change_rows(service, create_id) == []

    # `tags` is provided but unchanged, so it records no row.
    service.invoke(
        "task_update",
        {
            "id": "T-1",
            "actor": "alice",
            "if_revision": 1,
            "title": "renamed",
            "priority": 5,
            "tags": "",
        },
    )
    update_id = audit_id_of(service, "update", "task", "T-1")
    assert change_rows(service, update_id) == [
        ("priority", "3", "5"),
        ("title", "t", "renamed"),
    ]

    service.invoke(
        "task_status",
        {
            "id": "T-1",
            "status": "blocked",
            "actor": "alice",
            "if_revision": 2,
            "note": "waiting",
        },
    )
    status_id = audit_id_of(service, "status", "task", "T-1")
    assert change_rows(service, status_id) == [
        ("notes", "", "waiting"),
        ("status", "todo", "blocked"),
    ]

    service.invoke(
        "task_assign",
        {"id": "T-1", "actor": "alice", "if_revision": 3, "add": ["bob"]},
    )
    assign_id = audit_id_of(service, "assign", "task", "T-1")
    assert change_rows(service, assign_id) == [
        ("assignees", "alice", "alice,bob"),
    ]


def test_record_mutations(database: Path) -> None:
    service = seed(database)

    service.invoke("agent_update", {"id": "bob", "role": "review", "actor": "alice"})
    agent_id = audit_id_of(service, "update", "agent", "bob")
    assert change_rows(service, agent_id) == [("role", "r", "review")]

    service.invoke(
        "artifact_add",
        {"id": "ART-1", "uri": "docs/a.md", "owner": "alice", "type": "doc"},
    )
    service.invoke(
        "artifact_update", {"id": "ART-1", "uri": "docs/b.md", "actor": "alice"}
    )
    artifact_update = audit_id_of(service, "update", "artifact", "ART-1")
    assert change_rows(service, artifact_update) == [
        ("uri", "docs/a.md", "docs/b.md"),
    ]
    service.invoke(
        "artifact_status", {"id": "ART-1", "status": "review", "actor": "alice"}
    )
    artifact_status = audit_id_of(service, "status", "artifact", "ART-1")
    assert change_rows(service, artifact_status) == [
        ("status", "draft", "review"),
    ]

    service.invoke(
        "decision_add",
        {
            "id": "DEC-1",
            "title": "d",
            "owner": "alice",
            "context": "c",
            "decision": "x",
        },
    )
    service.invoke(
        "decision_status", {"id": "DEC-1", "status": "accepted", "actor": "alice"}
    )
    decision_status = audit_id_of(service, "status", "decision", "DEC-1")
    assert change_rows(service, decision_status) == [
        ("status", "proposed", "accepted"),
    ]

    service.invoke(
        "escalation_add",
        {
            "id": "ESC-1",
            "raised_by": "alice",
            "owner": "bob",
            "issue": "i",
            "requested_decision": "q",
        },
    )
    service.invoke(
        "escalation_resolve",
        {
            "id": "ESC-1",
            "status": "resolved",
            "resolution": "done",
            "actor": "bob",
        },
    )
    escalation_resolve = audit_id_of(service, "resolve", "escalation", "ESC-1")
    assert change_rows(service, escalation_resolve) == [
        ("resolution", "", "done"),
        ("status", "open", "resolved"),
    ]


def test_redaction_writes_no_change_rows(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "message_send",
        {
            "id": "MSG-1",
            "sender": "alice",
            "recipient": "team",
            "body": "accidental-secret-token",
        },
    )
    service.invoke(
        "message_redact",
        {"id": "MSG-1", "actor": "alice", "reason": "contained a secret"},
    )
    redact_id = audit_id_of(service, "redact", "message", "MSG-1")
    assert change_rows(service, redact_id) == []
    with sqlite3.connect(database) as raw:
        leaked = raw.execute(
            "SELECT COUNT(*) FROM change_log WHERE old_value LIKE '%secret%'"
            " OR new_value LIKE '%secret%'"
        ).fetchone()[0]
    assert leaked == 0


def test_read_surface(database: Path) -> None:
    service = seed(database)
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    service.invoke(
        "task_update",
        {"id": "T-1", "actor": "alice", "if_revision": 1, "title": "one"},
    )
    service.invoke(
        "task_update",
        {"id": "T-1", "actor": "alice", "if_revision": 2, "title": "two"},
    )

    by_object = service.invoke(
        "audit_changes", {"object_type": "task", "object_id": "T-1"}
    )
    assert [
        (row["field"], row["old_value"], row["new_value"]) for row in by_object
    ] == [
        ("title", "t", "one"),
        ("title", "one", "two"),
    ]
    first_change_id = int(by_object[0]["id"])
    after = service.invoke("audit_changes", {"since": first_change_id})
    assert [row["id"] for row in after] == [row["id"] for row in by_object[1:]]
    limited = service.invoke(
        "audit_changes",
        {"object_type": "task", "object_id": "T-1", "limit": 1, "offset": 1},
    )
    assert [(row["old_value"], row["new_value"]) for row in limited] == [("one", "two")]

    via_cli = json.loads(
        cli(
            database,
            "audit",
            "changes",
            "--object-type",
            "task",
            "--object-id",
            "T-1",
        ).stdout
    )["data"]
    assert via_cli == by_object

    via_id = json.loads(
        cli(database, "audit", "changes", "--id", str(by_object[0]["audit_id"])).stdout
    )["data"]
    assert via_id == by_object[:1]

    doctor = service.invoke("doctor", {})
    assert doctor["change_log_orphan_count"] == 0
    assert doctor["record_consistency"] == "ok"


def main() -> int:
    for test in (
        test_task_mutations,
        test_record_mutations,
        test_redaction_writes_no_change_rows,
        test_read_surface,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-changes-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Change log qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
