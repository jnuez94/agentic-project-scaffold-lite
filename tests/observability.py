#!/usr/bin/env python3
"""Qualify the 1.4.0 observability core.

The service dispatch boundary is the observability boundary: every mutation's
envelope carries `audit_range`, the contiguous audit ids its transaction wrote;
`COORDINATION_LOG=stderr` makes every invocation -- success and failure --
write one JSON record to standard error with its outcome, duration, lock wait,
and receipt, and never any free text. Refusals, conflicts, and busy timeouts are
invisible to the audit table, so the log is the only place they can be seen.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.core import database_lock_path  # noqa: E402
from coordination.errors import CoordinationError  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


RECORD_KEYS = {
    "ts",
    "transport",
    "operation",
    "actor",
    "session",
    "object",
    "outcome",
    "audit_range",
    "duration_ms",
    "lock_wait_ms",
}


def cli(
    database: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, **(env or {})}
    return subprocess.run(
        [str(ROOT / "scripts" / "coordination.py"), "--db", str(database), *arguments],
        cwd=ROOT,
        env=environment,
        check=check,
        text=True,
        capture_output=True,
    )


def json_objects(text: str) -> list[dict[str, object]]:
    """Decode standard error as a stream of concatenated JSON values.

    Log records are single lines; an error envelope is a pretty-printed
    object spanning several lines. Both share the stream, so a per-line parse
    is wrong -- consumers must decode values, not lines.
    """
    decoder = json.JSONDecoder()
    objects: list[dict[str, object]] = []
    index = 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return objects
        value, index = decoder.raw_decode(text, index)
        objects.append(value)


def test_service_receipts(database: Path) -> None:
    records: list[dict[str, object]] = []
    service = CoordinationService(db=str(database), operation_log=records.append)
    service.invoke("init", {})
    assert service.last_receipt["audit_range"] is None  # init writes no audit
    service.invoke("agent_add", {"id": "alice", "name": "a", "role": "r"})
    created = service.last_receipt
    assert created["audit_range"] == [1, 1], created
    assert created["duration_ms"] >= 0 and created["lock_wait_ms"] >= 0
    service.invoke("agent_list", {})
    assert service.last_receipt["audit_range"] is None, "reads carry no receipt"

    # A multi-row intervention yields one contiguous range: recovery of a
    # session holding two claims writes recover_claim x2 + recover.
    service.invoke("agent_add", {"id": "bob", "name": "b", "role": "r"})
    service.invoke("session_start", {"id": "s-bob", "agent": "bob", "harness": "h"})
    bob = CoordinationService(db=str(database), session="s-bob")
    for task_id in ("T-1", "T-2"):
        bob.invoke("task_create", {"id": task_id, "title": "t", "actor": "bob"})
        bob.invoke("task_claim", {"id": task_id, "agent": "bob", "if_revision": 1})
    forced = service.invoke(
        "session_recover",
        {"id": "s-bob", "actor": "alice", "reason": "x", "force": True},
    )
    assert len(forced["recovered_tasks"]) == 2
    first, last = service.last_receipt["audit_range"]
    assert last - first == 2, service.last_receipt
    rows = service.invoke("audit_list", {"since": first - 1, "limit": 10})
    assert [row["action"] for row in rows[:3]] == [
        "recover_claim",
        "recover_claim",
        "recover",
    ]

    # The log saw every call, including the read, and never any free text.
    operations = [record["operation"] for record in records]
    assert operations[:3] == ["init", "agent_add", "agent_list"], operations
    for record in records:
        assert set(record) >= RECORD_KEYS, sorted(record)
        assert record["transport"] == "cli"
        assert "title" not in record and "reason" not in record
    recover_record = next(r for r in records if r["operation"] == "session_recover")
    assert recover_record["actor"] == "alice" and recover_record["object"] == "s-bob"
    assert recover_record["audit_range"] == [first, last]

    # A refused operation is logged with its code; the audit table has no row.
    try:
        service.invoke("task_claim", {"id": "T-1", "agent": "alice", "if_revision": 1})
    except CoordinationError as error:
        assert error.code == "session_required"
    refused = records[-1]
    assert refused["outcome"] == "error" and refused["code"] == "session_required"
    assert refused["exit_code"] == 2 and refused["audit_range"] is None

    # A broken sink never changes the operation's outcome.
    def explode(_: dict[str, object]) -> None:
        raise RuntimeError("sink failure")

    fragile = CoordinationService(db=str(database), operation_log=explode)
    assert fragile.invoke("agent_list", {}) is not None


def test_cli_envelope_and_stderr_log(database: Path) -> None:
    cli(database, "init")
    cli(database, "agent", "add", "--id", "alice", "--name", "a", "--role", "r")
    quiet = cli(
        database, "task", "create", "--id", "T-1", "--title", "t", "--actor", "alice"
    )
    envelope = json.loads(quiet.stdout)
    assert envelope["ok"] is True and envelope["audit_range"] == [2, 2], envelope
    assert quiet.stderr == "", "the log is off unless COORDINATION_LOG asks for it"

    logged = cli(
        database,
        "task",
        "update",
        "T-1",
        "--actor",
        "alice",
        "--if-revision",
        "1",
        "--description",
        "secret-looking free text must not be logged",
        env={"COORDINATION_LOG": "stderr"},
    )
    assert json.loads(logged.stdout)["audit_range"] == [3, 3]
    lines = json_objects(logged.stderr)
    assert len(lines) == 1, logged.stderr
    record = lines[0]
    assert record["operation"] == "task_update" and record["outcome"] == "ok"
    assert record["actor"] == "alice" and record["object"] == "T-1"
    assert record["audit_range"] == [3, 3] and record["transport"] == "cli"
    assert "secret-looking" not in logged.stderr

    # A read: envelope without audit_range, log line with audit_range null.
    listed = cli(database, "task", "list", env={"COORDINATION_LOG": "stderr"})
    assert "audit_range" not in json.loads(listed.stdout)
    assert json_objects(listed.stderr)[0]["audit_range"] is None

    # A refused write: the error envelope and one log record share stderr.
    stale = cli(
        database,
        "task",
        "update",
        "T-1",
        "--actor",
        "alice",
        "--if-revision",
        "1",
        "--title",
        "x",
        env={"COORDINATION_LOG": "stderr"},
        check=False,
    )
    assert stale.returncode == 4
    objects = json_objects(stale.stderr)
    error_envelopes = [o for o in objects if o.get("ok") is False]
    log_records = [o for o in objects if "operation" in o]
    assert len(error_envelopes) == 1 and len(log_records) == 1, stale.stderr
    assert error_envelopes[0]["error"]["code"] == "stale_task_revision"
    assert log_records[0]["outcome"] == "error"
    assert (
        log_records[0]["code"] == "stale_task_revision"
        and log_records[0]["exit_code"] == 4
    )

    # An unknown setting is a configuration error, like the other variables.
    bad = cli(database, "task", "list", env={"COORDINATION_LOG": "syslog"}, check=False)
    assert bad.returncode == 5
    assert json.loads(bad.stderr)["error"]["code"] == "configuration_error"


def test_lock_wait_is_measured(database: Path) -> None:
    cli(database, "init")
    cli(database, "agent", "add", "--id", "alice", "--name", "a", "--role", "r")
    lock_path = database_lock_path(database)
    with open(lock_path, "a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        busy = cli(
            database,
            "task",
            "create",
            "--id",
            "T-1",
            "--title",
            "t",
            "--actor",
            "alice",
            env={"COORDINATION_LOG": "stderr", "COORDINATION_BUSY_TIMEOUT_MS": "200"},
            check=False,
        )
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    assert busy.returncode == 6, busy.stderr
    record = next(o for o in json_objects(busy.stderr) if "operation" in o)
    assert record["code"] == "database_busy", record
    assert record["lock_wait_ms"] >= 150, record


def main() -> int:
    for test in (
        test_service_receipts,
        test_cli_envelope_and_stderr_log,
        test_lock_wait_is_measured,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-observability-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Observability qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
