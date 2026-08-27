#!/usr/bin/env python3
"""Qualify audited ledger redaction: append-then-tombstone, and its doctor checks.

`audit redact` appends a redaction event and rewrites the target audit row's
detail and change rows to the sentinel naming that event, in one transaction.
The schema's triggers admit no other ledger rewrite; `doctor` flags sentinels
whose named redaction event does not exist.
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


def cli(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "scripts" / "coordination.py"), "--db", str(database), *arguments],
        cwd=ROOT,
        check=True,
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


def seed(database: Path) -> CoordinationService:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    service.invoke("agent_add", {"id": "alice", "name": "alice", "role": "r"})
    service.invoke(
        "task_create", {"id": "T-1", "title": "leaked-token-abc123", "actor": "alice"}
    )
    service.invoke(
        "task_update",
        {"id": "T-1", "actor": "alice", "if_revision": 1, "title": "clean title"},
    )
    return service


def update_audit_id(service: CoordinationService) -> int:
    rows = service.invoke(
        "audit_list", {"action": "update", "object_type": "task", "object_id": "T-1"}
    )
    return int(rows[-1]["id"])


def ledger_mentions(database: Path, needle: str) -> int:
    with sqlite3.connect(database) as raw:
        return int(
            raw.execute(
                """SELECT (SELECT COUNT(*) FROM audit_log
                            WHERE detail LIKE '%' || ? || '%')
                        + (SELECT COUNT(*) FROM change_log
                            WHERE old_value LIKE '%' || ? || '%'
                               OR new_value LIKE '%' || ? || '%')""",
                (needle, needle, needle),
            ).fetchone()[0]
        )


def test_redaction_tombstones_the_ledger(database: Path) -> None:
    service = seed(database)
    target = update_audit_id(service)
    assert ledger_mentions(database, "leaked-token-abc123") > 0

    result = service.invoke(
        "audit_redact", {"id": target, "actor": "alice", "reason": "leaked a token"}
    )
    redaction_id = int(result["redaction_id"])
    assert result["id"] == target
    assert result["change_rows_redacted"] == 1

    sentinel = f"[redacted:{redaction_id}]"
    with sqlite3.connect(database) as raw:
        detail = raw.execute(
            "SELECT detail FROM audit_log WHERE id = ?", (target,)
        ).fetchone()[0]
        change = raw.execute(
            "SELECT old_value, new_value FROM change_log WHERE audit_id = ?",
            (target,),
        ).fetchone()
        redaction = raw.execute(
            "SELECT action, object_type, object_id FROM audit_log WHERE id = ?",
            (redaction_id,),
        ).fetchone()
    assert detail == sentinel
    assert tuple(change) == (sentinel, sentinel)
    assert tuple(redaction) == ("redact", "audit", str(target))
    assert ledger_mentions(database, "leaked-token-abc123") == 0

    doctor = service.invoke("doctor", {})
    assert doctor["audit_redaction_dangling_count"] == 0
    assert doctor["record_consistency"] == "ok"

    expect(
        "already_redacted",
        lambda: service.invoke(
            "audit_redact", {"id": target, "actor": "alice", "reason": "again"}
        ),
    )
    expect(
        "not_found",
        lambda: service.invoke(
            "audit_redact", {"id": 999999, "actor": "alice", "reason": "missing"}
        ),
    )


def test_redacting_the_redaction_reason(database: Path) -> None:
    service = seed(database)
    target = update_audit_id(service)
    first = int(
        service.invoke(
            "audit_redact",
            {"id": target, "actor": "alice", "reason": "reason-with-secret-xyz"},
        )["redaction_id"]
    )
    assert ledger_mentions(database, "secret-xyz") == 1
    second = service.invoke(
        "audit_redact", {"id": first, "actor": "alice", "reason": "reason leaked too"}
    )
    assert ledger_mentions(database, "secret-xyz") == 0
    with sqlite3.connect(database) as raw:
        detail = raw.execute(
            "SELECT detail FROM audit_log WHERE id = ?", (first,)
        ).fetchone()[0]
    assert detail == f"[redacted:{second['redaction_id']}]"
    doctor = service.invoke("doctor", {})
    assert doctor["audit_redaction_dangling_count"] == 0


def test_cli_parity(database: Path) -> None:
    service = seed(database)
    target = update_audit_id(service)
    envelope = json.loads(
        cli(
            database,
            "audit",
            "redact",
            "--id",
            str(target),
            "--actor",
            "alice",
            "--reason",
            "cli redaction",
        ).stdout
    )
    assert envelope["ok"] is True
    assert envelope["data"]["id"] == target
    assert "audit_range" in envelope
    via_changes = json.loads(
        cli(database, "audit", "changes", "--id", str(target)).stdout
    )["data"]
    assert all(row["old_value"].startswith("[redacted:") for row in via_changes)


def test_doctor_flags_forged_sentinels(database: Path) -> None:
    service = seed(database)
    target = update_audit_id(service)
    # The trigger admits any well-formed sentinel; only doctor can tell a
    # forged tombstone (naming no redaction event) from a real one.
    with sqlite3.connect(database) as raw:
        raw.execute(
            "UPDATE audit_log SET detail = '[redacted:999999]' WHERE id = ?",
            (target,),
        )
    doctor = service.invoke("doctor", {})
    assert doctor["audit_redaction_dangling_count"] == 1
    assert doctor["record_consistency"] == "findings"


def main() -> int:
    for test in (
        test_redaction_tombstones_the_ledger,
        test_redacting_the_redaction_reason,
        test_cli_parity,
        test_doctor_flags_forged_sentinels,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-redaction-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Audit redaction qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
