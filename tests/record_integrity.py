#!/usr/bin/env python3
"""Qualify the 1.4.0 record-integrity surface.

`doctor` reports rows written around the runtime (a row whose `updated_at`
postdates its last audit row, or that has no audit row at all); backup and
export are attributed and audited when an actor is named; and every entity has
a `history` timeline assembled from the audit rows that already exist.
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
from coordination.errors import CoordinationError  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


def cli(database: Path, *arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        [str(ROOT / "scripts" / "coordination.py"), "--db", str(database), *arguments],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def seed(database: Path) -> CoordinationService:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    service.invoke("agent_add", {"id": "alice", "name": "a", "role": "r"})
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    service.invoke(
        "decision_add",
        {"id": "D-1", "title": "t", "owner": "alice", "context": "c", "decision": "d"},
    )
    return service


def test_doctor_reports_out_of_band_edits(database: Path) -> None:
    service = seed(database)
    clean = service.invoke("doctor", {})
    assert clean["healthy"] is True
    assert clean["record_consistency"] == "ok", clean
    assert clean["out_of_band_edits"] == [] and clean["out_of_band_edit_count"] == 0
    assert clean["out_of_band_edits_truncated"] is False

    # A direct edit that bumps updated_at past the last audit row, and a row
    # inserted with no audit at all, are both found; the database stays
    # healthy -- this is a consistency finding, not a failure.
    with sqlite3.connect(database) as raw:
        raw.execute(
            "UPDATE tasks SET description = 'edited in sqlite3',"
            " updated_at = '2099-01-01T00:00:00+00:00' WHERE id = 'T-1'"
        )
        raw.execute(
            "INSERT INTO decisions(id, title, owner_id, status, context, decision,"
            " options_considered, implications, evidence, blocked_claims,"
            " review_required, created_at, updated_at) VALUES ('D-ghost', 't',"
            " 'alice', 'proposed', 'c', 'd', '', '', '', '', '',"
            " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    report = service.invoke("doctor", {})
    assert report["healthy"] is True
    assert report["record_consistency"] == "findings", report
    found = {(row["table"], row["id"]): row for row in report["out_of_band_edits"]}
    assert set(found) == {("tasks", "T-1"), ("decisions", "D-ghost")}, found
    assert found[("tasks", "T-1")]["updated_at"] == "2099-01-01T00:00:00+00:00"
    assert found[("tasks", "T-1")]["last_audit_at"] is not None
    assert found[("decisions", "D-ghost")]["last_audit_at"] is None
    assert report["out_of_band_edit_count"] == 2
    # A write through the runtime re-audits the row and clears its finding.
    service.invoke(
        "task_update",
        {
            "id": "T-1",
            "actor": "alice",
            "if_revision": 1,
            "description": "via the runtime",
        },
    )
    report = service.invoke("doctor", {})
    assert [row["id"] for row in report["out_of_band_edits"]] == ["D-ghost"], report
    via_cli = cli(database, "doctor")["data"]
    assert via_cli["record_consistency"] == "findings"


def test_backup_and_export_are_attributed(database: Path) -> None:
    service = seed(database)
    root = database.parent
    anonymous = service.invoke("backup", {"output": str(root / "anon.sqlite3")})
    assert anonymous["verified"] is True and anonymous["audit_recorded"] is False
    assert service.last_receipt["audit_range"] is None
    attributed = service.invoke(
        "backup", {"output": str(root / "named.sqlite3"), "actor": "alice"}
    )
    assert attributed["audit_recorded"] is True
    first, last = service.last_receipt["audit_range"]
    assert first == last
    rows = service.invoke("audit_list", {"since": first - 1, "limit": 1})
    assert rows[0]["action"] == "backup" and rows[0]["object_type"] == "database"
    assert rows[0]["actor"] == "alice" and rows[0]["detail"].startswith("output ")
    assert str(root / "named.sqlite3") in rows[0]["detail"]
    expect(
        "not_found",
        lambda: service.invoke(
            "backup", {"output": str(root / "x.sqlite3"), "actor": "nobody"}
        ),
    )
    # The copy itself carries the audit row, written before the copy? No: the
    # audit is recorded in the source after publication, so the copy does not
    # contain it and the source does.
    with sqlite3.connect(root / "named.sqlite3") as copy:
        assert (
            copy.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action='backup'"
            ).fetchone()[0]
            == 0
        )

    exported = service.invoke(
        "export", {"output": str(root / "report.md"), "actor": "alice"}
    )
    assert exported is not None and exported["tasks"] == 1
    first, last = service.last_receipt["audit_range"]
    rows = service.invoke("audit_list", {"since": first - 1, "limit": 1})
    assert (
        rows[0]["action"] == "export"
        and rows[0]["detail"] == f"output {root / 'report.md'}"
    )
    # Unattributed export still writes no audit row.
    service.invoke("export", {"output": str(root / "report2.md")})
    assert service.last_receipt["audit_range"] is None
    via_cli = cli(
        database, "backup", "--output", str(root / "cli.sqlite3"), "--actor", "alice"
    )
    assert via_cli["data"]["audit_recorded"] is True and "audit_range" in via_cli


def test_history_per_entity(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "task_update", {"id": "T-1", "actor": "alice", "if_revision": 1, "title": "t2"}
    )
    service.invoke(
        "task_status",
        {"id": "T-1", "status": "blocked", "actor": "alice", "if_revision": 2},
    )
    history = service.invoke("task_history", {"id": "T-1"})
    assert [row["action"] for row in history] == ["create", "update", "status"], history
    assert all(
        row["object_type"] == "task" and row["object_id"] == "T-1" for row in history
    )
    assert [row["id"] for row in history] == sorted(row["id"] for row in history)
    later = service.invoke("task_history", {"id": "T-1", "since": history[0]["id"]})
    assert [row["action"] for row in later] == ["update", "status"]
    page = service.invoke("task_history", {"id": "T-1", "limit": 1, "offset": 1})
    assert [row["action"] for row in page] == ["update"]
    assert service.invoke("task_history", {"id": "T-missing"}) == []
    service.invoke(
        "decision_status", {"id": "D-1", "status": "accepted", "actor": "alice"}
    )
    assert [
        row["action"] for row in service.invoke("decision_history", {"id": "D-1"})
    ] == ["create", "status"]
    assert [
        row["action"] for row in service.invoke("agent_history", {"id": "alice"})
    ] == ["create"]
    via_cli = cli(database, "task", "history", "T-1", "--limit", "2")["data"]
    assert [row["action"] for row in via_cli] == ["create", "update"]


def main() -> int:
    for test in (
        test_doctor_reports_out_of_band_edits,
        test_backup_and_export_are_attributed,
        test_history_per_entity,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-record-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Record integrity qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
