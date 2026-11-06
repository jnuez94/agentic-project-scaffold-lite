#!/usr/bin/env python3
"""Qualify `task activate`: long-lived tasks active without a claim.

An epic or story is active for days while its children run, which a claim
cannot express: a claim is a one-hour lease held by one execution session,
and the session sweep blocks claimed tasks whose session goes quiet. The
active marker is not a lease, so the sweep never touches it, and `done`
clears it.
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


def seed(database: Path) -> CoordinationService:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    for actor in ("greg", "jade"):
        service.invoke("agent_add", {"id": actor, "name": actor, "role": "r"})
    for task_id in ("EPIC-1", "TASK-1"):
        service.invoke(
            "task_create",
            {"id": task_id, "title": task_id, "actor": "greg", "assignee": ["greg"]},
        )
    return service


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def audit_actions(database: Path, task_id: str) -> list[str]:
    with sqlite3.connect(database) as raw:
        return [
            str(row[0])
            for row in raw.execute(
                "SELECT action FROM audit_log WHERE object_type = 'task'"
                " AND object_id = ? ORDER BY id",
                (task_id,),
            )
        ]


def test_activate_and_report(database: Path) -> None:
    service = seed(database)
    assert service.invoke("task_show", {"id": "EPIC-1"})["active"] is None

    result = service.invoke("task_activate", {"id": "EPIC-1", "actor": "greg"})
    assert result["changed"] is True
    assert result["active"]["actor"] == "greg"
    shown = service.invoke("task_show", {"id": "EPIC-1"})
    assert shown["active"] == result["active"]
    assert shown["status"] == "todo"  # not a status, not a claim
    assert shown["claimed_by"] is None

    listed = service.invoke("task_list", {"active": True})
    assert [task["id"] for task in listed] == ["EPIC-1"]
    everything = service.invoke("task_list", {})
    assert {task["id"]: task["active"] is not None for task in everything} == {
        "EPIC-1": True,
        "TASK-1": False,
    }

    # Idempotent in both directions; a repeat writes no audit row.
    again = service.invoke("task_activate", {"id": "EPIC-1", "actor": "jade"})
    assert again["changed"] is False and again["active"]["actor"] == "greg"
    assert audit_actions(database, "EPIC-1") == ["create", "activate"]

    off = service.invoke("task_deactivate", {"id": "EPIC-1", "actor": "greg"})
    assert off == {"id": "EPIC-1", "active": None, "changed": True}
    assert service.invoke("task_list", {"active": True}) == []
    repeat = service.invoke("task_deactivate", {"id": "EPIC-1", "actor": "greg"})
    assert repeat["changed"] is False
    assert audit_actions(database, "EPIC-1") == ["create", "activate", "deactivate"]

    # Activation is attributed and keeps the record consistent for doctor.
    doctor = service.invoke("doctor", {})
    assert doctor["record_consistency"] == "ok", doctor["out_of_band_edits"]

    expect(
        "not_found",
        lambda: service.invoke("task_activate", {"id": "NOPE", "actor": "greg"}),
    )


def test_sweep_never_blocks_an_active_parent(database: Path) -> None:
    service = seed(database)
    service.invoke("task_activate", {"id": "EPIC-1", "actor": "greg"})
    service.invoke(
        "session_start",
        {"id": "jade-run", "agent": "jade", "harness": "h", "model": "m"},
    )
    jade = CoordinationService(db=str(database), session="jade-run")
    jade.invoke("task_claim", {"id": "TASK-1", "agent": "jade", "if_revision": 1})
    # The child's session goes quiet for a day.
    with sqlite3.connect(database) as raw:
        raw.execute(
            "UPDATE agent_sessions SET last_seen_at = '2026-01-01T00:00:00+00:00'"
            " WHERE id = 'jade-run'"
        )
    swept = service.invoke(
        "session_sweep",
        {"actor": "greg", "reason": "quiet", "stale_after_seconds": 60},
    )
    assert [s["id"] for s in swept["recovered_sessions"]] == ["jade-run"], swept
    assert service.invoke("task_show", {"id": "TASK-1"})["status"] == "blocked"
    epic = service.invoke("task_show", {"id": "EPIC-1"})
    assert epic["status"] == "todo" and epic["active"] is not None


def test_done_clears_the_marker(database: Path) -> None:
    service = seed(database)
    service.invoke("task_activate", {"id": "EPIC-1", "actor": "greg"})
    service.invoke(
        "session_start",
        {"id": "greg-run", "agent": "greg", "harness": "h", "model": "m"},
    )
    greg = CoordinationService(db=str(database), session="greg-run")
    # The parent is claimed only briefly, to close it; it stays active.
    greg.invoke("task_claim", {"id": "EPIC-1", "agent": "greg", "if_revision": 1})
    greg.invoke(
        "task_status",
        {"id": "EPIC-1", "status": "review", "actor": "greg", "if_revision": 2},
    )
    assert service.invoke("task_show", {"id": "EPIC-1"})["active"] is not None
    service.invoke(
        "evidence_add", {"task": "EPIC-1", "uri": "evidence://epic", "actor": "greg"}
    )
    service.invoke(
        "task_status",
        {"id": "EPIC-1", "status": "done", "actor": "greg", "if_revision": 3},
    )
    closed = service.invoke("task_show", {"id": "EPIC-1"})
    assert closed["status"] == "done" and closed["active"] is None
    with sqlite3.connect(database) as raw:
        detail = raw.execute(
            "SELECT detail FROM audit_log WHERE object_id = 'EPIC-1'"
            " AND action = 'status' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        leftover = raw.execute(
            "SELECT COUNT(*) FROM metadata WHERE key = 'active_tasks'"
        ).fetchone()[0]
    assert detail.endswith("; active cleared"), detail
    assert leftover == 0  # the last marker removes the row
    expect(
        "invalid_task_state",
        lambda: service.invoke("task_activate", {"id": "EPIC-1", "actor": "greg"}),
    )


def test_cli_parity(database: Path) -> None:
    seed(database)
    tool = str(ROOT / "scripts" / "coordination.py")

    def cli(*arguments: str) -> dict:
        completed = subprocess.run(
            [tool, "--db", str(database), *arguments],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(completed.stdout)

    activated = cli("task", "activate", "EPIC-1", "--actor", "greg")
    assert activated["data"]["changed"] is True
    assert "audit_range" in activated
    listed = cli("task", "list", "--active")["data"]
    assert [task["id"] for task in listed] == ["EPIC-1"]
    cli("task", "deactivate", "EPIC-1", "--actor", "greg")
    assert cli("task", "list", "--active")["data"] == []


def main() -> int:
    for test in (
        test_activate_and_report,
        test_sweep_never_blocks_an_active_parent,
        test_done_clears_the_marker,
        test_cli_parity,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-active-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Active task qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
