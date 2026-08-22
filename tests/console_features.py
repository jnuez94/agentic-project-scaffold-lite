#!/usr/bin/env python3
"""Qualify the 1.3.0 console features requested by the downstream operator UI.

Every item here was filed because the only alternative was a second read path
over the SQLite file: repeatable and tag filters on `task list` (#9, #14, #18),
`message list --task` (#9), `audit list --since` (#10, #15), `summary` at one
coherent snapshot (#11), and a `health` that separates anomalies from normal
workflow (#16).
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
from coordination.entities.reports import (  # noqa: E402
    HEALTH_ANOMALY_SECTIONS,
    HEALTH_INFORMATIONAL_SECTIONS,
    HEALTH_SECTIONS,
    SUMMARY_SECTIONS,
)
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
    for actor in ("alice", "bob"):
        service.invoke("agent_add", {"id": actor, "name": actor, "role": "r"})
    service.invoke("session_start", {"id": "s-alice", "agent": "alice", "harness": "h"})
    alice = CoordinationService(db=str(database), session="s-alice")
    for index, (status_tags) in enumerate(
        (
            ("todo", "frontend, urgent"),
            ("todo", "backend"),
            ("review", "frontend"),
            ("blocked", ""),
            ("done", "frontend,docs"),
        )
    ):
        status, tags = status_tags
        task_id = f"T-{index}"
        alice.invoke(
            "task_create",
            {
                "id": task_id,
                "title": f"t{index}",
                "actor": "alice",
                "tags": tags,
                "assignee": ["alice"] if index % 2 == 0 else [],
            },
        )
        if status == "review":
            alice.invoke(
                "task_claim", {"id": task_id, "agent": "alice", "if_revision": 1}
            )
            alice.invoke(
                "task_release",
                {"id": task_id, "status": "review", "actor": "alice", "if_revision": 2},
            )
        elif status == "blocked":
            alice.invoke(
                "task_status",
                {
                    "id": task_id,
                    "status": "blocked",
                    "actor": "alice",
                    "if_revision": 1,
                },
            )
        elif status == "done":
            alice.invoke(
                "task_claim", {"id": task_id, "agent": "alice", "if_revision": 1}
            )
            alice.invoke(
                "task_release",
                {"id": task_id, "status": "review", "actor": "alice", "if_revision": 2},
            )
            alice.invoke(
                "evidence_add", {"task": task_id, "uri": "e://x", "actor": "alice"}
            )
            alice.invoke(
                "task_status",
                {"id": task_id, "status": "done", "actor": "alice", "if_revision": 3},
            )
    alice.invoke(
        "message_send",
        {
            "id": "M-1",
            "sender": "alice",
            "recipient": "bob",
            "body": "about T-0",
            "task": "T-0",
        },
    )
    alice.invoke(
        "message_send",
        {"id": "M-2", "sender": "alice", "recipient": "team", "body": "general"},
    )
    return service


def ids(values: object) -> list[str]:
    assert isinstance(values, list), values
    return [str(row["id"]) for row in values]


def test_task_list_filters(database: Path) -> None:
    service = seed(database)
    # Single value keeps working, repeatable means IN.
    assert ids(service.invoke("task_list", {"status": "todo"})) == ["T-0", "T-1"]
    open_tasks = service.invoke("task_list", {"status": ["todo", "review", "blocked"]})
    assert ids(open_tasks) == ["T-0", "T-1", "T-2", "T-3"]
    # Duplicates collapse; invalid values fail before the database is read.
    assert ids(service.invoke("task_list", {"status": ["todo", "todo"]})) == [
        "T-0",
        "T-1",
    ]
    expect(
        "invalid_arguments",
        lambda: service.invoke("task_list", {"status": ["todo", "nope"]}),
    )
    expect("invalid_arguments", lambda: service.invoke("task_list", {"status": 7}))
    # Tag filter matches a comma-separated token, ignoring surrounding whitespace.
    assert ids(service.invoke("task_list", {"tag": "frontend"})) == [
        "T-0",
        "T-2",
        "T-4",
    ]
    assert ids(service.invoke("task_list", {"tag": "urgent"})) == ["T-0"]
    assert (
        ids(service.invoke("task_list", {"tag": "front"})) == []
    )  # token, not substring
    assert ids(service.invoke("task_list", {"tag": "docs", "status": "done"})) == [
        "T-4"
    ]
    expect(
        "invalid_arguments", lambda: service.invoke("task_list", {"tag": "front end"})
    )
    expect("invalid_arguments", lambda: service.invoke("task_list", {"tag": "a,b"}))
    # LIKE wildcards in a tag are literal.
    assert ids(service.invoke("task_list", {"tag": "%"})) == []
    # The CLI spells repeatable status by repeating the flag.
    via_cli = cli(database, "task", "list", "--status", "todo", "--status", "review")
    assert ids(via_cli["data"]) == ["T-0", "T-1", "T-2"]
    assert ids(cli(database, "task", "list", "--tag", "backend")["data"]) == ["T-1"]


def test_message_list_by_task(database: Path) -> None:
    service = seed(database)
    assert ids(service.invoke("message_list", {"task": "T-0"})) == ["M-1"]
    assert ids(service.invoke("message_list", {"task": "T-1"})) == []
    assert ids(service.invoke("message_list", {"recipient": "bob", "task": "T-0"})) == [
        "M-1"
    ]
    assert ids(service.invoke("message_list", {"recipient": "bob"})) == ["M-1", "M-2"]


def test_audit_list_and_cursor(database: Path) -> None:
    service = seed(database)
    everything = service.invoke("audit_list", {"limit": 500})
    assert isinstance(everything, list) and len(everything) > 10
    assert [row["id"] for row in everything] == sorted(row["id"] for row in everything)
    first = everything[0]
    assert set(first) == {
        "id",
        "actor",
        "session_id",
        "action",
        "object_type",
        "object_id",
        "detail",
        "created_at",
    }, sorted(first)
    # Filters match the indexed and free-text columns.
    creates = service.invoke("audit_list", {"action": "create", "object_type": "task"})
    assert [row["object_id"] for row in creates] == [f"T-{index}" for index in range(5)]
    by_session = service.invoke("audit_list", {"session_id": "s-alice", "limit": 500})
    assert all(row["session_id"] == "s-alice" for row in by_session) and by_session
    # `agent add` without --actor attributes the create to the new agent, so
    # bob's only row is his own creation.
    by_actor = service.invoke("audit_list", {"actor": "bob"})
    assert [
        (row["action"], row["object_type"], row["object_id"]) for row in by_actor
    ] == [("create", "agent", "bob")], by_actor
    # The cursor: rows after `since`, and summary reports the head.
    cursor = service.invoke("summary", {"section": "totals"})["audit_cursor"]
    assert cursor == everything[-1]["id"]
    assert service.invoke("audit_list", {"since": cursor}) == []
    service.invoke("agent_add", {"id": "carol", "name": "c", "role": "r"})
    new_rows = service.invoke("audit_list", {"since": cursor})
    assert [(row["action"], row["object_id"]) for row in new_rows] == [
        ("create", "carol")
    ]
    expect("invalid_arguments", lambda: service.invoke("audit_list", {"since": -1}))
    # Through the CLI, with the session filter spelled distinctly from --session.
    rows = cli(database, "audit", "list", "--session-id", "s-alice", "--limit", "3")[
        "data"
    ]
    assert len(rows) == 3 and all(row["session_id"] == "s-alice" for row in rows)


def test_summary_snapshot(database: Path) -> None:
    service = seed(database)
    report = service.invoke("summary", {})
    assert isinstance(report, dict)
    assert report["sections"] == list(SUMMARY_SECTIONS)
    assert report["totals"]["tasks"] == 5 and report["totals"]["messages"] == 2
    assert report["totals"]["agents"] == 2 and report["totals"]["sessions"] == 1
    assert report["task_status"] == {
        "todo": 2,
        "in_progress": 0,
        "review": 1,
        "blocked": 1,
        "done": 1,
    }
    assert report["task_priority"] == {"1": 0, "2": 0, "3": 5, "4": 0, "5": 0}
    workload = {row["agent_id"]: row for row in report["workload"]}
    assert workload["alice"]["assigned_open_tasks"] == 2  # T-0, T-2 (T-4 is done)
    assert (
        workload["alice"]["active_sessions"] == 1
        and workload["bob"]["active_sessions"] == 0
    )
    assert report["workload_truncated"] is False
    only = service.invoke("summary", {"section": ["task_status"]})
    assert only["sections"] == ["task_status"] and "totals" not in only
    assert "audit_cursor" in only
    expect("invalid_arguments", lambda: service.invoke("summary", {"section": "nope"}))
    assert (
        cli(database, "summary", "--section", "totals")["data"]["totals"]["tasks"] == 5
    )


def test_health_splits_anomalies_from_informational(database: Path) -> None:
    service = seed(database)
    report = service.invoke("health", {})
    assert isinstance(report, dict)
    assert set(report["anomalies"]) == set(HEALTH_ANOMALY_SECTIONS)
    assert set(report["informational"]) == set(HEALTH_INFORMATIONAL_SECTIONS)
    # Existing top-level keys survive for current clients.
    for name in HEALTH_SECTIONS:
        assert name in report, name
    assert ids(report["tasks_awaiting_review"]) == ["T-2"]
    assert (
        report["informational"]["tasks_awaiting_review"]
        == report["tasks_awaiting_review"]
    )
    # A task in review is normal workflow, not decay: healthy follows anomalies.
    assert report["active_blockers"] and report["unowned_tasks"]
    assert report["healthy"] is False
    for task_id, revision in (("T-1", 1), ("T-3", 2)):
        # resolve the anomalies: assign T-1 and T-3 (unowned), unblock T-3
        service.invoke(
            "task_assign",
            {
                "id": task_id,
                "actor": "alice",
                "if_revision": revision,
                "add": ["alice"],
            },
        )
    service.invoke(
        "task_status",
        {"id": "T-3", "status": "todo", "actor": "alice", "if_revision": 3},
    )
    report = service.invoke("health", {})
    assert report["healthy"] is True, {
        k: v for k, v in report["anomalies"].items() if v
    }
    assert report["tasks_awaiting_review"], "informational section still populated"
    # Sections restrict what is computed; healthy reflects only computed anomalies.
    partial = service.invoke(
        "health", {"section": ["tasks_awaiting_review", "open_escalations"]}
    )
    assert set(partial["anomalies"]) == {"open_escalations"}
    assert set(partial["informational"]) == {"tasks_awaiting_review"}
    assert "unowned_tasks" not in partial
    assert partial["healthy"] is True
    expect("invalid_arguments", lambda: service.invoke("health", {"section": "nope"}))
    via_cli = cli(database, "health", "--section", "active_blockers")["data"]
    assert (
        set(via_cli["anomalies"]) == {"active_blockers"}
        and via_cli["informational"] == {}
    )


def main() -> int:
    for test in (
        test_task_list_filters,
        test_message_list_by_task,
        test_audit_list_and_cursor,
        test_summary_snapshot,
        test_health_splits_anomalies_from_informational,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-console-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Console feature qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
