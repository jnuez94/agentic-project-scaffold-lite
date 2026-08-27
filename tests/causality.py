#!/usr/bin/env python3
"""Qualify causality references and time-in-state.

A status change may name the review, decision, or message that caused it
(`--because TYPE:ID`); the reference is checked at write time and recorded in
the audit detail as `because=TYPE:ID`, so the ledger answers "why did this
move" without carrying free text. `summary --section time_in_state` reports
how long open work has sat in its current status, derived from the ledger.
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


def cli(
    database: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "scripts" / "coordination.py"), "--db", str(database), *arguments],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def last_detail(database: Path, object_type: str, object_id: str) -> str:
    with sqlite3.connect(database) as raw:
        row = raw.execute(
            "SELECT detail FROM audit_log WHERE object_type = ? AND object_id = ?"
            " ORDER BY id DESC LIMIT 1",
            (object_type, object_id),
        ).fetchone()
    return str(row[0])


def seed(database: Path) -> CoordinationService:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    service.invoke("agent_add", {"id": "alice", "name": "a", "role": "r"})
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    service.invoke(
        "review_add",
        {
            "id": "R-1",
            "reviewer": "alice",
            "artifact": "a",
            "scope": "s",
            "decision": "changes_requested",
            "task": "T-1",
        },
    )
    service.invoke(
        "decision_add",
        {"id": "D-1", "title": "t", "owner": "alice", "context": "c", "decision": "d"},
    )
    service.invoke(
        "message_send",
        {"id": "M-1", "sender": "alice", "recipient": "team", "body": "b"},
    )
    service.invoke(
        "artifact_add", {"id": "A-1", "uri": "u", "owner": "alice", "type": "t"}
    )
    service.invoke(
        "escalation_add",
        {
            "id": "E-1",
            "raised_by": "alice",
            "owner": "o",
            "issue": "i",
            "requested_decision": "r",
        },
    )
    return service


def test_because_references(database: Path) -> None:
    service = seed(database)
    # Malformed and dangling references are refused before anything changes.
    for bad in ("R-1", "review:", "sprint:R-1", "review:has space"):
        expect(
            "invalid_arguments",
            lambda bad=bad: service.invoke(
                "task_status",
                {
                    "id": "T-1",
                    "status": "blocked",
                    "actor": "alice",
                    "if_revision": 1,
                    "because": bad,
                },
            ),
        )
    missing = expect(
        "not_found",
        lambda: service.invoke(
            "task_status",
            {
                "id": "T-1",
                "status": "blocked",
                "actor": "alice",
                "if_revision": 1,
                "because": "review:R-9",
            },
        ),
    )
    assert missing.details == {"resource": "review R-9"}
    assert service.invoke("task_show", {"id": "T-1"})["status"] == "todo", (
        "nothing changed"
    )

    # A valid reference lands in the audit detail, after the facts.
    service.invoke(
        "task_status",
        {
            "id": "T-1",
            "status": "blocked",
            "actor": "alice",
            "if_revision": 1,
            "because": "review:R-1",
        },
    )
    assert (
        last_detail(database, "task", "T-1")
        == "todo -> blocked; revision 1 -> 2; because=review:R-1"
    )
    service.invoke(
        "decision_status",
        {
            "id": "D-1",
            "status": "accepted",
            "actor": "alice",
            "because": "message:M-1",
            "note": "ok",
        },
    )
    assert (
        last_detail(database, "decision", "D-1")
        == "proposed -> accepted; because=message:M-1; ok"
    )
    service.invoke(
        "artifact_status",
        {"id": "A-1", "status": "review", "actor": "alice", "because": "task:T-1"},
    )
    assert (
        last_detail(database, "artifact", "A-1") == "draft -> review; because=task:T-1"
    )
    service.invoke(
        "escalation_resolve",
        {
            "id": "E-1",
            "resolution": "done",
            "actor": "alice",
            "because": "decision:D-1",
        },
    )
    assert (
        last_detail(database, "escalation", "E-1")
        == "open -> resolved; because=decision:D-1"
    )
    # Without --because the detail is unchanged from before.
    service.invoke(
        "task_status",
        {"id": "T-1", "status": "todo", "actor": "alice", "if_revision": 2},
    )
    assert last_detail(database, "task", "T-1") == "blocked -> todo; revision 2 -> 3"
    # Through the CLI, on release as well as status.
    service.invoke("session_start", {"id": "s-a", "agent": "alice", "harness": "h"})
    alice = CoordinationService(db=str(database), session="s-a")
    alice.invoke("task_claim", {"id": "T-1", "agent": "alice", "if_revision": 3})
    released = cli(
        database,
        "--session",
        "s-a",
        "task",
        "release",
        "T-1",
        "--to",
        "review",
        "--actor",
        "alice",
        "--if-revision",
        "4",
        "--because",
        "review:R-1",
    )
    assert json.loads(released.stdout)["data"]["status"] == "review"
    assert last_detail(database, "task", "T-1").endswith("; because=review:R-1")
    rejected = cli(
        database,
        "task",
        "status",
        "T-1",
        "blocked",
        "--actor",
        "alice",
        "--if-revision",
        "5",
        "--because",
        "nonsense",
        check=False,
    )
    assert (
        rejected.returncode == 2
        and json.loads(rejected.stderr)["error"]["code"] == "invalid_arguments"
    )


def test_time_in_state(database: Path) -> None:
    service = seed(database)
    service.invoke("task_create", {"id": "T-2", "title": "t", "actor": "alice"})
    service.invoke(
        "task_status",
        {"id": "T-2", "status": "blocked", "actor": "alice", "if_revision": 1},
    )
    fresh = service.invoke("summary", {"section": "time_in_state"})
    ages = fresh["time_in_state"]
    assert set(ages) == {"todo", "in_progress", "review", "blocked"}, ages
    assert ages["todo"]["count"] == 1 and ages["blocked"]["count"] == 1
    assert ages["in_progress"] == {
        "count": 0,
        "oldest_seconds": 0,
        "average_seconds": 0,
    }
    assert (
        ages["todo"]["oldest_seconds"] < 60 and ages["blocked"]["oldest_seconds"] < 60
    )
    assert fresh["sections"] == ["time_in_state"]

    # Age is measured from the LAST status-changing audit row. Push T-1's
    # creation back months; for T-2 push its creation back two hours and its
    # block back one hour, so the block -- the latest change -- sets its age.
    # Timestamps are written in the runtime's ISO `T` form so they compare
    # correctly with the rows the runtime wrote.
    with sqlite3.connect(database) as raw:
        # Schema v2 forbids in-band audit_log updates. This fixture ages
        # ledger rows for the test, so it removes the guard trigger and
        # restores it from its canonical definition afterwards.
        guard = raw.execute(
            "SELECT sql FROM sqlite_master"
            " WHERE name = 'audit_log_redaction_only_update'"
        ).fetchone()[0]
        raw.execute("DROP TRIGGER audit_log_redaction_only_update")
        raw.execute(
            "UPDATE audit_log SET created_at = '2026-01-01T00:00:00+00:00'"
            " WHERE object_type = 'task' AND object_id = 'T-1' AND action = 'create'"
        )
        raw.execute(
            "UPDATE audit_log SET created_at ="
            " strftime('%Y-%m-%dT%H:%M:%S', 'now', '-2 hours') || '+00:00'"
            " WHERE object_type = 'task' AND object_id = 'T-2' AND action = 'create'"
        )
        raw.execute(
            "UPDATE audit_log SET created_at ="
            " strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 hour') || '+00:00'"
            " WHERE object_type = 'task' AND object_id = 'T-2' AND action = 'status'"
        )
        raw.execute(guard)
    aged = service.invoke("summary", {"section": ["time_in_state"]})["time_in_state"]
    assert aged["todo"]["oldest_seconds"] > 86400 * 100, aged["todo"]
    assert 3500 <= aged["blocked"]["oldest_seconds"] <= 3700, aged["blocked"]
    assert aged["blocked"]["average_seconds"] == aged["blocked"]["oldest_seconds"]
    # Done tasks are excluded.
    assert "done" not in aged
    full = service.invoke("summary", {})
    assert full["sections"][-1] == "time_in_state" and "time_in_state" in full
    via_cli = json.loads(cli(database, "summary", "--section", "time_in_state").stdout)[
        "data"
    ]
    assert via_cli["time_in_state"]["todo"]["count"] == 1


def main() -> int:
    for test in (test_because_references, test_time_in_state):
        with tempfile.TemporaryDirectory(prefix="coordination-causality-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Causality qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
