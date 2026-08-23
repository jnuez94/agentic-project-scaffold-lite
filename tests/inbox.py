#!/usr/bin/env python3
"""Qualify the per-agent inbox (#19).

A newly registered agent starts at the audit head, so it inherits an empty
inbox rather than the project's history; `inbox list` returns messages to the
agent or to `team` sent after its cursor; the cursor advances only when asked,
and only forward; the owner may be named or derived from the global session.
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


def ids(messages: object) -> list[str]:
    assert isinstance(messages, list)
    return [str(row["id"]) for row in messages]


def test_inbox(database: Path) -> None:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    service.invoke("agent_add", {"id": "alice", "name": "a", "role": "r"})
    service.invoke(
        "message_send",
        {"id": "M-old-team", "sender": "alice", "recipient": "team", "body": "b"},
    )
    service.invoke(
        "message_send",
        {"id": "M-old-bob", "sender": "alice", "recipient": "bob", "body": "b"},
    )
    # Bob registers after those were sent: empty inbox, cursor at the head.
    service.invoke("agent_add", {"id": "bob", "name": "b", "role": "r"})
    bob_head = service.last_receipt["audit_range"][1]
    empty = service.invoke("inbox_list", {"agent": "bob"})
    assert empty["agent"] == "bob" and empty["cursor"] == bob_head, empty
    assert empty["messages"] == [] and empty["head"] == bob_head

    # After registration: direct, team, and someone else's direct message.
    service.invoke(
        "message_send",
        {"id": "M-1", "sender": "alice", "recipient": "bob", "body": "hi bob"},
    )
    service.invoke(
        "message_send",
        {"id": "M-2", "sender": "alice", "recipient": "team", "body": "all"},
    )
    service.invoke(
        "message_send",
        {"id": "M-3", "sender": "alice", "recipient": "carol-ish", "body": "x"},
    )
    inbox = service.invoke("inbox_list", {"agent": "bob"})
    assert ids(inbox["messages"]) == ["M-1", "M-2"], inbox
    assert inbox["messages"][0]["audit_id"] < inbox["messages"][1]["audit_id"]
    assert inbox["head"] >= inbox["messages"][1]["audit_id"]
    # Listing does not move the cursor.
    assert service.invoke("inbox_list", {"agent": "bob"})["cursor"] == bob_head
    # Paging is by limit/offset over the unread set.
    assert ids(
        service.invoke("inbox_list", {"agent": "bob", "limit": 1})["messages"]
    ) == ["M-1"]
    assert ids(
        service.invoke("inbox_list", {"agent": "bob", "limit": 1, "offset": 1})[
            "messages"
        ]
    ) == ["M-2"]

    # Mark-read: forward only, never past the head, audited as the agent.
    first_audit = inbox["messages"][0]["audit_id"]
    marked = service.invoke("inbox_mark_read", {"agent": "bob", "cursor": first_audit})
    assert marked == {
        "agent": "bob",
        "previous_cursor": bob_head,
        "cursor": first_audit,
        "head": marked["head"],
    }
    assert ids(service.invoke("inbox_list", {"agent": "bob"})["messages"]) == ["M-2"]
    expect(
        "cursor_not_monotonic",
        lambda: service.invoke(
            "inbox_mark_read", {"agent": "bob", "cursor": first_audit - 1}
        ),
    )
    expect(
        "invalid_arguments",
        lambda: service.invoke("inbox_mark_read", {"agent": "bob", "cursor": 10**9}),
    )
    with sqlite3.connect(database) as raw:
        row = raw.execute(
            "SELECT actor, action, detail FROM audit_log"
            " WHERE action = 'mark_read' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row == ("bob", "mark_read", f"inbox cursor {bob_head} -> {first_audit}"), row
    # The same cursor again is a no-op advance, not an error.
    service.invoke("inbox_mark_read", {"agent": "bob", "cursor": first_audit})
    # Catching up to the head empties the inbox.
    head = service.invoke("inbox_list", {"agent": "bob"})["head"]
    service.invoke("inbox_mark_read", {"agent": "bob", "cursor": head})
    assert service.invoke("inbox_list", {"agent": "bob"})["messages"] == []

    # The owner may be derived from the session; without either it is an error.
    service.invoke("session_start", {"id": "s-bob", "agent": "bob", "harness": "h"})
    via_session = CoordinationService(db=str(database), session="s-bob")
    service.invoke(
        "message_send",
        {"id": "M-4", "sender": "alice", "recipient": "bob", "body": "later"},
    )
    assert ids(via_session.invoke("inbox_list", {})["messages"]) == ["M-4"]
    expect("invalid_arguments", lambda: service.invoke("inbox_list", {}))
    expect("not_found", lambda: service.invoke("inbox_list", {"agent": "nobody"}))

    # An agent with no cursor (registered before 1.4.0) sees everything.
    with sqlite3.connect(database) as raw:
        cursors = json.loads(
            raw.execute(
                "SELECT value FROM metadata WHERE key='inbox_cursors'"
            ).fetchone()[0]
        )
        cursors.pop("alice")
        raw.execute(
            "UPDATE metadata SET value = ? WHERE key='inbox_cursors'",
            (json.dumps(cursors),),
        )
    legacy = service.invoke("inbox_list", {"agent": "alice"})
    assert legacy["cursor"] == 0 and ids(legacy["messages"]) == ["M-old-team", "M-2"], (
        legacy
    )

    # Cursors survive in one metadata row, so a 128-character agent id is fine.
    long_id = "a" * 128
    service.invoke("agent_add", {"id": long_id, "name": "l", "role": "r"})
    assert service.invoke("inbox_list", {"agent": long_id})["messages"] == []

    # Through the CLI and the global --session.
    out = cli(database, "--session", "s-bob", "inbox", "list")
    assert ids(json.loads(out.stdout)["data"]["messages"]) == ["M-4"]
    marked_cli = cli(
        database, "inbox", "mark-read", "--agent", "bob", "--cursor", str(head + 1)
    )
    assert json.loads(marked_cli.stdout)["data"]["cursor"] == head + 1
    assert "audit_range" in json.loads(marked_cli.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="coordination-inbox-") as name:
        test_inbox(Path(name) / "coordination.sqlite3")
    print("Inbox qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
