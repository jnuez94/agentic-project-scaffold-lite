#!/usr/bin/env python3
"""Qualify the 1.3.0 write-path requests.

`artifact update` corrects a record whose URI moved (#18); `decision status`
records a ruling on a decision after it was proposed (#12, #18); `message
redact` is the remediation path for content that should never have been stored
(#17); and `--if-status` is compare-and-swap for the mutable entities that
carry no revision (#13, option 2).
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
from coordination.entities.messages import REDACTED_BODY  # noqa: E402
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


def audit_rows(
    database: Path, object_type: str, object_id: str
) -> list[tuple[str, str, str]]:
    with sqlite3.connect(database) as raw:
        return [
            (str(a), str(b), str(c))
            for a, b, c in raw.execute(
                "SELECT actor, action, detail FROM audit_log"
                " WHERE object_type = ? AND object_id = ? ORDER BY id",
                (object_type, object_id),
            )
        ]


def seed(database: Path) -> CoordinationService:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    for actor in ("alice", "bob"):
        service.invoke("agent_add", {"id": actor, "name": actor, "role": "r"})
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    return service


def test_artifact_update_and_status_cas(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "artifact_add",
        {
            "id": "ART-1",
            "uri": "docs/old/design.md",
            "owner": "alice",
            "type": "design",
            "task": ["T-1"],
        },
    )
    expect(
        "invalid_arguments",
        lambda: service.invoke("artifact_update", {"id": "ART-1", "actor": "alice"}),
    )
    updated = service.invoke(
        "artifact_update",
        {
            "id": "ART-1",
            "actor": "bob",
            "uri": "docs/new/design.md",
            "if_status": "draft",
        },
    )
    assert updated["uri"] == "docs/new/design.md" and updated["status"] == "draft", (
        updated
    )
    assert updated["updated_at"] >= updated["created_at"]
    listed = service.invoke("artifact_list", {})
    assert listed[0]["uri"] == "docs/new/design.md" and listed[0]["related_tasks"] == [
        "T-1"
    ]
    assert audit_rows(database, "artifact", "ART-1")[-1] == (
        "bob",
        "update",
        "fields=uri",
    )
    expect(
        "not_found",
        lambda: service.invoke(
            "artifact_update", {"id": "ART-9", "actor": "bob", "uri": "x"}
        ),
    )
    # Compare-and-swap: the status the caller saw must still hold.
    mismatch = expect(
        "status_mismatch",
        lambda: service.invoke(
            "artifact_status",
            {
                "id": "ART-1",
                "status": "review",
                "actor": "alice",
                "if_status": "accepted",
            },
        ),
    )
    assert mismatch.details == {
        "artifact": "ART-1",
        "expected_status": "accepted",
        "actual_status": "draft",
    }
    service.invoke(
        "artifact_status",
        {"id": "ART-1", "status": "review", "actor": "alice", "if_status": "draft"},
    )
    assert audit_rows(database, "artifact", "ART-1")[-1] == (
        "alice",
        "status",
        "draft -> review",
    )
    # Without --if-status the change is unconditional, as before.
    service.invoke(
        "artifact_status", {"id": "ART-1", "status": "accepted", "actor": "alice"}
    )
    expect(
        "status_mismatch",
        lambda: service.invoke(
            "artifact_update",
            {"id": "ART-1", "actor": "alice", "type": "spec", "if_status": "draft"},
        ),
    )
    via_cli = cli(
        database, "artifact", "update", "ART-1", "--type", "spec", "--actor", "alice"
    )
    assert json.loads(via_cli.stdout)["data"]["type"] == "spec"
    rejected = cli(
        database,
        "artifact",
        "status",
        "ART-1",
        "draft",
        "--actor",
        "alice",
        "--if-status",
        "review",
        check=False,
    )
    assert (
        rejected.returncode == 4
        and json.loads(rejected.stderr)["error"]["code"] == "status_mismatch"
    )


def test_decision_status(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "decision_add",
        {
            "id": "DEC-1",
            "title": "Use SQLite",
            "owner": "alice",
            "context": "c",
            "decision": "d",
        },
    )
    assert service.invoke("decision_list", {})[0]["status"] == "proposed"
    ruled = service.invoke(
        "decision_status",
        {
            "id": "DEC-1",
            "status": "accepted",
            "actor": "bob",
            "if_status": "proposed",
            "note": "ratified",
        },
    )
    assert ruled == {
        "id": "DEC-1",
        "previous_status": "proposed",
        "status": "accepted",
    }, ruled
    row = service.invoke("decision_list", {})[0]
    assert row["status"] == "accepted" and row["updated_at"] >= row["created_at"]
    assert audit_rows(database, "decision", "DEC-1")[-1] == (
        "bob",
        "status",
        "proposed -> accepted; ratified",
    )
    mismatch = expect(
        "status_mismatch",
        lambda: service.invoke(
            "decision_status",
            {
                "id": "DEC-1",
                "status": "superseded",
                "actor": "bob",
                "if_status": "proposed",
            },
        ),
    )
    assert mismatch.details["actual_status"] == "accepted"
    expect(
        "not_found",
        lambda: service.invoke(
            "decision_status", {"id": "DEC-9", "status": "accepted", "actor": "bob"}
        ),
    )
    expect(
        "invalid_arguments",
        lambda: service.invoke(
            "decision_status", {"id": "DEC-1", "status": "done", "actor": "bob"}
        ),
    )
    via_cli = cli(
        database,
        "decision",
        "status",
        "DEC-1",
        "superseded",
        "--actor",
        "alice",
        "--if-status",
        "accepted",
    )
    assert json.loads(via_cli.stdout)["data"]["status"] == "superseded"


def test_escalation_resolve_cas(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "escalation_add",
        {
            "id": "ESC-1",
            "raised_by": "alice",
            "owner": "bob",
            "issue": "i",
            "requested_decision": "r",
        },
    )
    expect(
        "status_mismatch",
        lambda: service.invoke(
            "escalation_resolve",
            {
                "id": "ESC-1",
                "resolution": "x",
                "actor": "bob",
                "if_status": "in_review",
            },
        ),
    )
    resolved = service.invoke(
        "escalation_resolve",
        {"id": "ESC-1", "resolution": "x", "actor": "bob", "if_status": "open"},
    )
    assert resolved == {"id": "ESC-1", "status": "resolved"}
    # A second resolver who still thinks it is open is refused: no lost update.
    expect(
        "status_mismatch",
        lambda: service.invoke(
            "escalation_resolve",
            {"id": "ESC-1", "resolution": "y", "actor": "alice", "if_status": "open"},
        ),
    )


def test_message_redact(database: Path) -> None:
    service = seed(database)
    service.invoke(
        "message_send",
        {
            "id": "M-1",
            "sender": "alice",
            "recipient": "bob",
            "body": "token=sk-live-oops",
            "task": "T-1",
            "tags": "creds",
        },
    )
    service.invoke(
        "message_send",
        {"id": "M-2", "sender": "alice", "recipient": "team", "body": "fine"},
    )
    redacted = service.invoke(
        "message_redact", {"id": "M-1", "actor": "bob", "reason": "pasted credential"}
    )
    assert redacted == {"id": "M-1", "status": "redacted"}
    rows = {row["id"]: row for row in service.invoke("message_list", {})}
    assert rows["M-1"]["body"] == REDACTED_BODY
    # Everything except the content survives.
    assert rows["M-1"]["sender_id"] == "alice" and rows["M-1"]["recipient"] == "bob"
    assert rows["M-1"]["task_id"] == "T-1" and rows["M-1"]["tags"] == "creds"
    assert rows["M-2"]["body"] == "fine"
    assert audit_rows(database, "message", "M-1")[-1] == (
        "bob",
        "redact",
        "pasted credential",
    )
    # The content is gone from the file, not merely hidden from the list.
    with sqlite3.connect(database) as raw:
        dump = "\n".join(raw.iterdump())
    assert "sk-live-oops" not in dump
    expect(
        "already_redacted",
        lambda: service.invoke(
            "message_redact", {"id": "M-1", "actor": "bob", "reason": "again"}
        ),
    )
    expect(
        "not_found",
        lambda: service.invoke(
            "message_redact", {"id": "M-9", "actor": "bob", "reason": "x"}
        ),
    )
    via_cli = cli(
        database, "message", "redact", "M-2", "--actor", "alice", "--reason", "cleanup"
    )
    assert json.loads(via_cli.stdout)["data"] == {"id": "M-2", "status": "redacted"}


def main() -> int:
    for test in (
        test_artifact_update_and_status_cas,
        test_decision_status,
        test_escalation_resolve_cas,
        test_message_redact,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-write-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Write feature qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
