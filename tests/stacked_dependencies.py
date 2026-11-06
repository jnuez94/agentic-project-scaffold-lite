#!/usr/bin/env python3
"""Qualify `informs` as the non-blocking "built on" dependency.

Under both strict policies an `informs` dependency on unfinished work never
blocks a claim or a close, and it is still recorded and listed. `blocks`
keeps its strict meaning alongside it.
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
from coordination.errors import CoordinationError  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


STRICT = (
    "version: 1\nbackend: sqlite\ndatabase: coordination.sqlite3\n"
    "closure_policy: strict\ndependency_policy: strict\n"
)


def strict_project(root: Path) -> CoordinationService:
    coordination = root / ".coordination"
    coordination.mkdir(parents=True)
    (coordination / "config.yml").write_text(STRICT)
    service = CoordinationService(db=str(coordination / "coordination.sqlite3"))
    service.invoke("init", {})
    for actor in ("alice", "bob"):
        service.invoke("agent_add", {"id": actor, "name": actor, "role": "r"})
    service.invoke(
        "session_start",
        {"id": "run-1", "agent": "alice", "harness": "h", "model": "m"},
    )
    for task_id in ("T-BASE", "T-STACKED", "T-WAITING"):
        service.invoke(
            "task_create",
            {"id": task_id, "title": task_id, "actor": "alice", "assignee": ["alice"]},
        )
    return service


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def test_informs_never_blocks_a_claim_or_a_close(root: Path) -> None:
    service = strict_project(root)
    session = CoordinationService(db=service.db, session="run-1")
    service.invoke(
        "dependency_add",
        {
            "task": "T-STACKED",
            "depends_on": "T-BASE",
            "actor": "alice",
            "type": "informs",
            "rationale": "built on T-BASE's unmerged branch",
        },
    )
    service.invoke(
        "dependency_add",
        {
            "task": "T-WAITING",
            "depends_on": "T-BASE",
            "actor": "alice",
            "type": "blocks",
        },
    )
    assert service.invoke("task_show", {"id": "T-BASE"})["status"] == "todo"

    # blocks keeps its strict meaning...
    error = expect(
        "task_blocked",
        lambda: session.invoke(
            "task_claim", {"id": "T-WAITING", "agent": "alice", "if_revision": 1}
        ),
    )
    assert error.details == {"task": "T-WAITING", "blocked_by": ["T-BASE"]}

    # ...while informs lets the stacked task be claimed and closed with its
    # base still unfinished.
    session.invoke(
        "task_claim", {"id": "T-STACKED", "agent": "alice", "if_revision": 1}
    )
    session.invoke(
        "task_status",
        {"id": "T-STACKED", "status": "review", "actor": "alice", "if_revision": 2},
    )
    service.invoke(
        "evidence_add", {"task": "T-STACKED", "uri": "evidence://pr", "actor": "alice"}
    )
    service.invoke(
        "review_add",
        {
            "id": "R-1",
            "reviewer": "bob",
            "artifact": "a",
            "scope": "s",
            "decision": "accepted",
            "task": "T-STACKED",
        },
    )
    service.invoke(
        "task_status",
        {"id": "T-STACKED", "status": "done", "actor": "alice", "if_revision": 3},
    )
    assert service.invoke("task_show", {"id": "T-STACKED"})["status"] == "done"
    assert service.invoke("task_show", {"id": "T-BASE"})["status"] == "todo"


def test_informs_is_recorded_and_listed(root: Path) -> None:
    service = strict_project(root)
    service.invoke(
        "dependency_add",
        {
            "task": "T-STACKED",
            "depends_on": "T-BASE",
            "actor": "alice",
            "type": "informs",
            "rationale": "built on",
        },
    )
    shown = service.invoke("task_show", {"id": "T-STACKED"})
    assert [
        (d["depends_on_task_id"], d["dependency_type"], d["status"], d["rationale"])
        for d in shown["dependencies"]
    ] == [("T-BASE", "informs", "active", "built on")]
    listed = service.invoke(
        "dependency_list", {"where": ["dependency_type:eq=informs"]}
    )
    assert [(d["task_id"], d["depends_on_task_id"]) for d in listed] == [
        ("T-STACKED", "T-BASE")
    ]
    via_cli = subprocess.run(
        [
            str(ROOT / "scripts" / "coordination.py"),
            "--db",
            service.db,
            "task",
            "show",
            "T-STACKED",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    dependency = json.loads(via_cli.stdout)["data"]["dependencies"][0]
    assert dependency["dependency_type"] == "informs"


def main() -> int:
    for test in (
        test_informs_never_blocks_a_claim_or_a_close,
        test_informs_is_recorded_and_listed,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-stacked-") as name:
            test(Path(name))
    print("Stacked dependency qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
