#!/usr/bin/env python3
"""Qualify the opt-in enforcement policies: closure and dependency gates.

Both policies default to off, which must be byte-for-byte the permissive
1.4.0 behavior. With `closure_policy: strict`, `done` requires resolved
blocking dependencies and an accepted latest review from a non-assignee;
with `dependency_policy: strict`, a claim is refused while an active
`blocks` dependency points at unfinished work.
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


BASE_CONFIG = "version: 1\nbackend: sqlite\ndatabase: coordination.sqlite3\n"


def project(root: Path, policies: str = "") -> Path:
    coordination = root / ".coordination"
    coordination.mkdir(parents=True)
    (coordination / "config.yml").write_text(BASE_CONFIG + policies)
    return coordination / "coordination.sqlite3"


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


def to_review(service: CoordinationService, task_id: str, revision: int = 1) -> int:
    """Claim and move a task to review; returns the next expected revision."""
    session = CoordinationService(db=service.db, session="run-1")
    session.invoke(
        "task_claim", {"id": task_id, "agent": "alice", "if_revision": revision}
    )
    session.invoke(
        "task_status",
        {
            "id": task_id,
            "status": "review",
            "actor": "alice",
            "if_revision": revision + 1,
        },
    )
    service.invoke(
        "evidence_add", {"task": task_id, "uri": "evidence://done", "actor": "alice"}
    )
    return revision + 2


def close(service: CoordinationService, task_id: str, revision: int) -> None:
    service.invoke(
        "task_status",
        {"id": task_id, "status": "done", "actor": "alice", "if_revision": revision},
    )


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def test_defaults_preserve_permissive_behavior(root: Path) -> None:
    database = project(root)
    service = seed(database)
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    service.invoke("task_create", {"id": "T-2", "title": "t", "actor": "alice"})
    service.invoke(
        "dependency_add",
        {"task": "T-2", "depends_on": "T-1", "actor": "alice", "type": "blocks"},
    )
    # A blocked task claims fine, and done needs no review: 1.4.0 behavior.
    revision = to_review(service, "T-2")
    close(service, "T-2", revision)
    assert service.invoke("task_show", {"id": "T-2"})["status"] == "done"


def test_dependency_policy_blocks_claims(root: Path) -> None:
    database = project(root, "dependency_policy: strict\n")
    service = seed(database)
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    service.invoke("task_create", {"id": "T-2", "title": "t", "actor": "alice"})
    service.invoke(
        "dependency_add",
        {"task": "T-2", "depends_on": "T-1", "actor": "alice", "type": "blocks"},
    )
    session = CoordinationService(db=str(database), session="run-1")
    error = expect(
        "task_blocked",
        lambda: session.invoke(
            "task_claim", {"id": "T-2", "agent": "alice", "if_revision": 1}
        ),
    )
    assert error.details == {"task": "T-2", "blocked_by": ["T-1"]}
    assert service.invoke("task_show", {"id": "T-2"})["status"] == "todo"
    # Finishing the blocker unblocks the claim (closure policy is off here).
    revision = to_review(service, "T-1")
    close(service, "T-1", revision)
    session.invoke("task_claim", {"id": "T-2", "agent": "alice", "if_revision": 1})
    assert service.invoke("task_show", {"id": "T-2"})["status"] == "in_progress"


def test_closure_policy_gates_done(root: Path) -> None:
    database = project(root, "closure_policy: strict\n")
    service = seed(database)
    service.invoke(
        "task_create",
        {"id": "T-1", "title": "t", "actor": "alice", "assignee": ["alice"]},
    )
    revision = to_review(service, "T-1")

    error = expect("closure_requires_review", lambda: close(service, "T-1", revision))
    assert (error.details or {})["reason"] == "no_review"

    service.invoke(
        "review_add",
        {
            "id": "R-1",
            "reviewer": "bob",
            "artifact": "a",
            "scope": "s",
            "decision": "changes_requested",
            "task": "T-1",
        },
    )
    error = expect("closure_requires_review", lambda: close(service, "T-1", revision))
    assert (error.details or {})["reason"] == "latest_review_not_accepted"

    service.invoke(
        "review_add",
        {
            "id": "R-2",
            "reviewer": "alice",
            "artifact": "a",
            "scope": "s",
            "decision": "accepted",
            "task": "T-1",
        },
    )
    error = expect("closure_requires_review", lambda: close(service, "T-1", revision))
    assert (error.details or {})["reason"] == "self_review"

    service.invoke(
        "review_add",
        {
            "id": "R-3",
            "reviewer": "bob",
            "artifact": "a",
            "scope": "s",
            "decision": "accepted",
            "task": "T-1",
        },
    )
    service.invoke("task_create", {"id": "T-GATE", "title": "t", "actor": "alice"})
    service.invoke(
        "dependency_add",
        {
            "task": "T-1",
            "depends_on": "T-GATE",
            "actor": "alice",
            "type": "review_required",
        },
    )
    error = expect(
        "closure_blocked_by_dependencies", lambda: close(service, "T-1", revision)
    )
    assert (error.details or {})["dependencies"] == [
        {"depends_on": "T-GATE", "type": "review_required"}
    ]

    service.invoke(
        "dependency_resolve",
        {
            "task": "T-1",
            "depends_on": "T-GATE",
            "actor": "alice",
            "type": "review_required",
        },
    )
    close(service, "T-1", revision)
    assert service.invoke("task_show", {"id": "T-1"})["status"] == "done"
    # Nothing in the gate wrote extra audit rows for the refusals.
    refusals = service.invoke(
        "audit_list", {"object_type": "task", "object_id": "T-1", "action": "status"}
    )
    assert len(refusals) == 2  # review entry and the final done


def test_misspelled_policy_is_a_configuration_error(root: Path) -> None:
    database = project(root, "closure_policy: strcit\n")
    service = seed(database)
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    error = expect(
        "configuration_error",
        lambda: CoordinationService(db=str(database), session="run-1").invoke(
            "task_claim", {"id": "T-1", "agent": "alice", "if_revision": 1}
        ),
    )
    assert (error.details or {})["key"] == "closure_policy"


def test_cli_parity(root: Path) -> None:
    database = project(root, "closure_policy: strict\n")
    service = seed(database)
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    revision = to_review(service, "T-1")
    completed = subprocess.run(
        [
            str(ROOT / "scripts" / "coordination.py"),
            "--db",
            str(database),
            "task",
            "status",
            "T-1",
            "done",
            "--actor",
            "alice",
            "--if-revision",
            str(revision),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 4, completed.stderr
    envelope = json.loads(completed.stderr)
    assert envelope["error"]["code"] == "closure_requires_review"


def main() -> int:
    for test in (
        test_defaults_preserve_permissive_behavior,
        test_dependency_policy_blocks_claims,
        test_closure_policy_gates_done,
        test_misspelled_policy_is_a_configuration_error,
        test_cli_parity,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-policy-") as name:
            test(Path(name))
    print("Enforcement policy qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
