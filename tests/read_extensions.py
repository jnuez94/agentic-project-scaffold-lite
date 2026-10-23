#!/usr/bin/env python3
"""Qualify the 1.4.1 cheap reads: counts, activity, dependency list, paging.

`inbox count` and `audit activity` answer "anything new?" without a model
run; `dependency list` joins the uniform read surface; review rows carry
`sequence` so same-second reviews order correctly; and every full list page
carries `next_offset` in its envelope.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.service import CoordinationService  # noqa: E402


def cli(database: Path, *arguments: str) -> dict:
    completed = subprocess.run(
        [str(ROOT / "scripts" / "coordination.py"), "--db", str(database), *arguments],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def seed(database: Path) -> CoordinationService:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    for actor in ("alice", "bob"):
        service.invoke("agent_add", {"id": actor, "name": actor, "role": "r"})
    return service


def test_inbox_count(database: Path) -> None:
    service = seed(database)
    assert service.invoke("inbox_count", {"agent": "alice"})["unread"] == 0
    for message_id in ("M-1", "M-2"):
        service.invoke(
            "message_send",
            {"id": message_id, "sender": "bob", "recipient": "team", "body": "b"},
        )
    counted = service.invoke("inbox_count", {"agent": "alice"})
    assert counted["unread"] == 2
    assert counted["head"] > counted["cursor"]
    service.invoke("inbox_mark_read", {"agent": "alice", "cursor": counted["head"]})
    assert service.invoke("inbox_count", {"agent": "alice"})["unread"] == 0
    via_cli = cli(database, "inbox", "count", "--agent", "bob")["data"]
    assert via_cli["unread"] == 2  # bob has not marked anything read


def test_audit_activity(database: Path) -> None:
    service = seed(database)
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    everything = service.invoke("audit_activity", {})
    assert everything["total"] == everything["head"] > 0
    assert everything["actions"].get("create", 0) >= 3  # two agents and a task
    marker = everything["head"]
    quiet = service.invoke("audit_activity", {"since": marker})
    assert quiet["total"] == 0 and quiet["actions"] == {} and quiet["objects"] == {}
    service.invoke(
        "message_send",
        {"id": "M-1", "sender": "bob", "recipient": "team", "body": "b"},
    )
    fresh = service.invoke("audit_activity", {"since": marker})
    assert fresh["total"] == 1 and fresh["actions"] == {"send": 1}
    assert fresh["objects"] == {"message": 1}
    nothing_from_alice = service.invoke(
        "audit_activity", {"since": marker, "agent": "alice"}
    )
    assert nothing_from_alice["total"] == 0
    via_cli = cli(database, "audit", "activity", "--since", str(marker))["data"]
    assert via_cli == fresh


def test_dependency_list(database: Path) -> None:
    service = seed(database)
    for task_id in ("T-1", "T-2", "T-3"):
        service.invoke("task_create", {"id": task_id, "title": "t", "actor": "alice"})
    service.invoke(
        "dependency_add",
        {"task": "T-2", "depends_on": "T-1", "actor": "alice", "type": "blocks"},
    )
    service.invoke(
        "dependency_add",
        {"task": "T-3", "depends_on": "T-1", "actor": "alice", "type": "informs"},
    )
    service.invoke(
        "dependency_add",
        {"task": "T-3", "depends_on": "T-2", "actor": "alice", "type": "blocks"},
    )
    everything = service.invoke("dependency_list", {})
    assert [(d["task_id"], d["depends_on_task_id"]) for d in everything] == [
        ("T-2", "T-1"),
        ("T-3", "T-1"),
        ("T-3", "T-2"),
    ]
    blocks = service.invoke("dependency_list", {"where": ["dependency_type:eq=blocks"]})
    assert len(blocks) == 2
    service.invoke(
        "dependency_resolve",
        {"task": "T-2", "depends_on": "T-1", "actor": "alice", "type": "blocks"},
    )
    active = service.invoke("dependency_list", {"where": ["status:eq=active"]})
    assert len(active) == 2
    via_cli = cli(database, "dependency", "list", "--where", "task_id:eq=T-3")["data"]
    assert len(via_cli) == 2


def test_review_sequence_orders_same_second_reviews(database: Path) -> None:
    service = seed(database)
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    # Written in one process tick: created_at collides to the second, and the
    # textual tie-breaker would put REV-10 before REV-9.
    for review_id in ("REV-9", "REV-10"):
        service.invoke(
            "review_add",
            {
                "id": review_id,
                "reviewer": "bob",
                "artifact": "a",
                "scope": "s",
                "decision": "accepted",
                "task": "T-1",
            },
        )
    listed = service.invoke("review_list", {"task": "T-1"})
    assert [row["id"] for row in listed] == ["REV-9", "REV-10"]
    assert listed[0]["sequence"] < listed[1]["sequence"]
    shown = service.invoke("review_show", {"id": "REV-10"})
    assert shown["sequence"] == listed[1]["sequence"]


def test_health_reports_finished_but_open_tasks(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "session_start",
        {"id": "run-1", "agent": "alice", "harness": "h", "model": "m"},
    )
    session = CoordinationService(db=str(database), session="run-1")
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    session.invoke("task_claim", {"id": "T-1", "agent": "alice", "if_revision": 1})
    session.invoke(
        "task_status",
        {"id": "T-1", "status": "review", "actor": "alice", "if_revision": 2},
    )
    service.invoke(
        "review_add",
        {
            "id": "R-1",
            "reviewer": "bob",
            "artifact": "a",
            "scope": "s",
            "decision": "accepted",
            "task": "T-1",
        },
    )
    report = service.invoke("health", {})
    finished = report["tasks_with_accepting_reviews"]
    assert [task["id"] for task in finished] == ["T-1"]
    assert report["healthy"] in (True, False)  # informational, never anomalous
    service.invoke(
        "evidence_add", {"task": "T-1", "uri": "evidence://x", "actor": "alice"}
    )
    service.invoke(
        "task_status",
        {"id": "T-1", "status": "done", "actor": "alice", "if_revision": 3},
    )
    report = service.invoke("health", {})
    assert report["tasks_with_accepting_reviews"] == []


def test_next_offset_paging(database: Path) -> None:
    service = seed(database)
    for task_id in ("T-1", "T-2", "T-3"):
        service.invoke("task_create", {"id": task_id, "title": "t", "actor": "alice"})
    service.invoke("task_list", {"limit": 2, "offset": 0})
    assert service.last_receipt["next_offset"] == 2
    service.invoke("task_list", {"limit": 2, "offset": 2})
    assert service.last_receipt["next_offset"] is None
    service.invoke("task_show", {"id": "T-1"})
    assert service.last_receipt["next_offset"] is None

    envelope = cli(database, "task", "list", "--limit", "2")
    assert envelope["next_offset"] == 2
    full = cli(database, "task", "list")
    assert "next_offset" not in full


def main() -> int:
    for test in (
        test_inbox_count,
        test_audit_activity,
        test_dependency_list,
        test_review_sequence_orders_same_second_reviews,
        test_health_reports_finished_but_open_tasks,
        test_next_offset_paging,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-reads-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Read extension qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
