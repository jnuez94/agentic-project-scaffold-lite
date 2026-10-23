#!/usr/bin/env python3
"""Qualify the 1.4.1 write additions: profile edits, tag AND, claim, recorder.

Each addition is opt-in; the default invocation of every touched command
must behave exactly as in 1.4.0.
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


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def test_agent_profile_fields(database: Path) -> None:
    service = seed(database)
    updated = service.invoke(
        "agent_update",
        {
            "id": "bob",
            "responsibilities": "Review backend changes",
            "decision_authority": "Schema changes",
        },
    )
    assert updated["responsibilities"] == "Review backend changes"
    assert updated["decision_authority"] == "Schema changes"
    assert updated["name"] == "bob"  # untouched
    cleared = service.invoke("agent_update", {"id": "bob", "responsibilities": ""})
    assert cleared["responsibilities"] == ""
    via_cli = cli(database, "agent", "update", "bob", "--goal", "Ship safely")["data"]
    assert via_cli["goal"] == "Ship safely"
    expect("invalid_arguments", lambda: service.invoke("agent_update", {"id": "bob"}))


def test_tag_filters_combine_with_and(database: Path) -> None:
    service = seed(database)
    for task_id, tags in (
        ("T-1", "unit:task, lane:frontend"),
        ("T-2", "unit:task,lane:backend"),
        ("T-3", "unit:story,lane:frontend"),
    ):
        service.invoke(
            "task_create",
            {"id": task_id, "title": "t", "actor": "alice", "tags": tags},
        )
    single = service.invoke("task_list", {"tag": "lane:frontend"})
    assert [task["id"] for task in single] == ["T-1", "T-3"]
    both = service.invoke("task_list", {"tag": ["unit:task", "lane:frontend"]})
    assert [task["id"] for task in both] == ["T-1"]
    via_cli = cli(
        database, "task", "list", "--tag", "unit:task", "--tag", "lane:backend"
    )["data"]
    assert [task["id"] for task in via_cli] == ["T-2"]


def test_claim_without_assignment(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "session_start",
        {"id": "run-a", "agent": "alice", "harness": "h", "model": "m"},
    )
    session = CoordinationService(db=str(database), session="run-a")
    for task_id in ("T-1", "T-2"):
        service.invoke("task_create", {"id": task_id, "title": "t", "actor": "alice"})
    session.invoke("task_claim", {"id": "T-1", "agent": "alice", "if_revision": 1})
    assert service.invoke("task_show", {"id": "T-1"})["assignees"] == ["alice"]
    session.invoke(
        "task_claim",
        {"id": "T-2", "agent": "alice", "if_revision": 1, "assign": False},
    )
    claimed = service.invoke("task_show", {"id": "T-2"})
    assert claimed["status"] == "in_progress"
    assert claimed["assignees"] == []


def test_recording_another_owners_decision(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "session_start",
        {"id": "run-b", "agent": "bob", "harness": "h", "model": "m"},
    )
    recorder = CoordinationService(db=str(database), session="run-b")
    base = {"title": "t", "owner": "alice", "context": "c", "decision": "d"}
    expect(
        "session_actor_mismatch",
        lambda: recorder.invoke("decision_add", {"id": "D-1", **base}),
    )
    recorder.invoke("decision_add", {"id": "D-1", **base, "recorded_by": "bob"})
    assert service.invoke("decision_show", {"id": "D-1"})["owner_id"] == "alice"
    with sqlite3.connect(database) as raw:
        actor, session, detail = raw.execute(
            "SELECT actor, session_id, detail FROM audit_log"
            " WHERE object_type = 'decision' AND object_id = 'D-1'"
        ).fetchone()
    assert (actor, session, detail) == ("bob", "run-b", "proposed; owner=alice")
    # Without --recorded-by, attribution is unchanged from 1.4.0.
    service.invoke("decision_add", {"id": "D-2", **base})
    with sqlite3.connect(database) as raw:
        actor, detail = raw.execute(
            "SELECT actor, detail FROM audit_log"
            " WHERE object_type = 'decision' AND object_id = 'D-2'"
        ).fetchone()
    assert (actor, detail) == ("alice", "proposed")


def main() -> int:
    for test in (
        test_agent_profile_fields,
        test_tag_filters_combine_with_and,
        test_claim_without_assignment,
        test_recording_another_owners_decision,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-writes-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Write extension qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
