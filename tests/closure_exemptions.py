#!/usr/bin/env python3
"""Qualify the 1.4.2 refinements of `closure_policy: strict`.

`closure_review_waiver: decision` lets a `done` transition that cites an
existing decision (`--because decision:ID`) stand in for the accepted review,
for work closed by a ruling rather than built. `closure_exempt_tags` lists
tag tokens whose tasks carry no review of their own, such as review records.
Neither relaxes the dependency check, the schema still requires evidence for
`done`, and with neither key set strict closure is exactly the 1.4.1 gate.
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
    service.invoke(
        "decision_add",
        {
            "id": "DEC-1",
            "title": "Drop it",
            "owner": "alice",
            "context": "Nobody will build this",
            "decision": "Close without building",
        },
    )
    return service


def to_review(
    service: CoordinationService,
    task_id: str,
    *,
    tags: str = "",
    evidence: bool = True,
) -> int:
    """Create a task, claim it, move it to review; returns the next revision."""
    service.invoke(
        "task_create",
        {
            "id": task_id,
            "title": task_id,
            "actor": "alice",
            "tags": tags,
            "assignee": ["alice"],
        },
    )
    session = CoordinationService(db=service.db, session="run-1")
    session.invoke("task_claim", {"id": task_id, "agent": "alice", "if_revision": 1})
    session.invoke(
        "task_status",
        {"id": task_id, "status": "review", "actor": "alice", "if_revision": 2},
    )
    if evidence:
        service.invoke(
            "evidence_add",
            {"task": task_id, "uri": "evidence://record", "actor": "alice"},
        )
    return 3


def close(
    service: CoordinationService,
    task_id: str,
    revision: int,
    because: str | None = None,
) -> dict:
    parameters: dict[str, object] = {
        "id": task_id,
        "status": "done",
        "actor": "alice",
        "if_revision": revision,
    }
    if because is not None:
        parameters["because"] = because
    return service.invoke("task_status", parameters)


def last_status_detail(database: Path, task_id: str) -> str:
    with sqlite3.connect(database) as raw:
        return str(
            raw.execute(
                "SELECT detail FROM audit_log WHERE object_type = 'task'"
                " AND object_id = ? AND action = 'status' ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()[0]
        )


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def test_strict_alone_is_the_141_gate(root: Path) -> None:
    database = project(root, "closure_policy: strict\n")
    service = seed(database)
    revision = to_review(service, "T-1", tags="unit:review")
    # Neither a cited decision nor a tag relaxes strict closure on its own.
    error = expect(
        "closure_requires_review",
        lambda: close(service, "T-1", revision, because="decision:DEC-1"),
    )
    assert (error.details or {})["reason"] == "no_review"
    assert service.invoke("task_show", {"id": "T-1"})["status"] == "review"


def test_decision_waiver(root: Path) -> None:
    database = project(
        root, "closure_policy: strict\nclosure_review_waiver: decision\n"
    )
    service = seed(database)

    revision = to_review(service, "T-DROP")
    # An outstanding request for changes does not hold back a ruled drop.
    service.invoke(
        "review_add",
        {
            "id": "R-1",
            "reviewer": "bob",
            "artifact": "a",
            "scope": "s",
            "decision": "changes_requested",
            "task": "T-DROP",
        },
    )
    close(service, "T-DROP", revision, because="decision:DEC-1")
    assert service.invoke("task_show", {"id": "T-DROP"})["status"] == "done"
    assert last_status_detail(database, "T-DROP") == (
        "review -> done; revision 3 -> 4; because=decision:DEC-1;"
        " review_waived=decision:DEC-1"
    )

    # Only a decision waives the review; another cited record does not.
    revision = to_review(service, "T-OTHER")
    service.invoke(
        "message_send",
        {"id": "M-1", "sender": "alice", "recipient": "team", "body": "b"},
    )
    expect(
        "closure_requires_review",
        lambda: close(service, "T-OTHER", revision, because="message:M-1"),
    )
    # A dangling decision is refused before anything changes.
    expect(
        "not_found",
        lambda: close(service, "T-OTHER", revision, because="decision:DEC-404"),
    )
    # Without a citation the review requirement stands.
    expect("closure_requires_review", lambda: close(service, "T-OTHER", revision))

    # The waiver never relaxes the dependency check.
    revision = to_review(service, "T-BLOCKED")
    service.invoke("task_create", {"id": "T-PREREQ", "title": "p", "actor": "alice"})
    service.invoke(
        "dependency_add",
        {
            "task": "T-BLOCKED",
            "depends_on": "T-PREREQ",
            "actor": "alice",
            "type": "blocks",
        },
    )
    expect(
        "closure_blocked_by_dependencies",
        lambda: close(service, "T-BLOCKED", revision, because="decision:DEC-1"),
    )


def test_exempt_tags(root: Path) -> None:
    database = project(
        root,
        "closure_policy: strict\nclosure_exempt_tags: unit:review, unit:record\n",
    )
    service = seed(database)

    revision = to_review(service, "REV-RUN", tags="unit:review,lane:security")
    close(service, "REV-RUN", revision)
    assert service.invoke("task_show", {"id": "REV-RUN"})["status"] == "done"
    assert last_status_detail(database, "REV-RUN") == (
        "review -> done; revision 3 -> 4; review_exempt=unit:review"
    )

    # Whitespace in the task's tags follows the `task list --tag` rule.
    revision = to_review(service, "REC-1", tags="lane:docs, unit:record")
    close(service, "REC-1", revision)
    assert last_status_detail(database, "REC-1").endswith("review_exempt=unit:record")

    # A tag is matched as a whole token, never as a substring.
    revision = to_review(service, "T-NEAR", tags="unit:reviewer")
    expect("closure_requires_review", lambda: close(service, "T-NEAR", revision))

    # Exempt tasks still need their blocking dependencies resolved...
    revision = to_review(service, "REV-BLOCKED", tags="unit:review")
    service.invoke("task_create", {"id": "T-PREREQ", "title": "p", "actor": "alice"})
    service.invoke(
        "dependency_add",
        {
            "task": "REV-BLOCKED",
            "depends_on": "T-PREREQ",
            "actor": "alice",
            "type": "review_required",
        },
    )
    expect(
        "closure_blocked_by_dependencies",
        lambda: close(service, "REV-BLOCKED", revision),
    )

    # ...and evidence: the schema refuses `done` without it.
    revision = to_review(service, "REV-BARE", tags="unit:review", evidence=False)
    expect("constraint_violation", lambda: close(service, "REV-BARE", revision))
    assert service.invoke("task_show", {"id": "REV-BARE"})["status"] == "review"


def test_refinements_need_strict_closure(root: Path) -> None:
    # Under `closure_policy: off` the refinements change nothing: closure is
    # already permissive, and the audit detail stays the 1.4.1 detail.
    database = project(
        root, "closure_review_waiver: decision\nclosure_exempt_tags: unit:review\n"
    )
    service = seed(database)
    revision = to_review(service, "T-1", tags="unit:review")
    close(service, "T-1", revision, because="decision:DEC-1")
    assert last_status_detail(database, "T-1") == (
        "review -> done; revision 3 -> 4; because=decision:DEC-1"
    )


def test_invalid_refinements_are_configuration_errors(root: Path) -> None:
    for name, line in (
        ("waiver", "closure_review_waiver: review\n"),
        ("blank-token", "closure_exempt_tags: unit:review,,unit:record\n"),
        ("spaced-token", "closure_exempt_tags: unit review\n"),
    ):
        database = project(root / name, "closure_policy: strict\n")
        service = seed(database)
        revision = to_review(service, "T-1", tags="unit:review")
        config = database.parent / "config.yml"
        config.write_text(config.read_text() + line)
        # Every policy read validates the whole file, so a misspelled
        # refinement can never silently loosen or skip the gate.
        error = expect(
            "configuration_error",
            lambda service=service, revision=revision: close(service, "T-1", revision),
        )
        assert (error.details or {})["key"] in (
            "closure_review_waiver",
            "closure_exempt_tags",
        ), error.details
        assert service.invoke("task_show", {"id": "T-1"})["status"] == "review"


def test_cli_parity(root: Path) -> None:
    database = project(
        root, "closure_policy: strict\nclosure_review_waiver: decision\n"
    )
    service = seed(database)
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
            "--because",
            "decision:DEC-1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["data"]["status"] == "done"


def main() -> int:
    for test in (
        test_strict_alone_is_the_141_gate,
        test_decision_waiver,
        test_exempt_tags,
        test_refinements_need_strict_closure,
        test_invalid_refinements_are_configuration_errors,
        test_cli_parity,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-exemptions-") as name:
            test(Path(name))
    print("Closure exemption qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
