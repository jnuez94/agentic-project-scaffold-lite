#!/usr/bin/env python3
"""Qualify the uniform read surface: `--where`, `--order-by`,
`--updated-since` on every list, `show` for every entity, and batch read via
`id:in`. The descriptor whitelist is the capability boundary: nothing above
the service can name a column or operator the descriptor does not list.
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


def ids(values: object) -> list[str]:
    assert isinstance(values, list), values
    return [str(row["id"]) for row in values]


def seed(database: Path) -> CoordinationService:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    for actor, kind in (("alice", "ai"), ("bob", "human"), ("carol", "service")):
        service.invoke(
            "agent_add", {"id": actor, "name": actor, "role": "r", "actor_type": kind}
        )
    for index, (status, priority) in enumerate(
        (("todo", 1), ("todo", 3), ("blocked", 2), ("todo", 5), ("blocked", 4))
    ):
        task_id = f"T-{index}"
        service.invoke(
            "task_create",
            {
                "id": task_id,
                "title": f"t{index}",
                "actor": "alice",
                "priority": priority,
            },
        )
        if status == "blocked":
            service.invoke(
                "task_status",
                {
                    "id": task_id,
                    "status": "blocked",
                    "actor": "alice",
                    "if_revision": 1,
                },
            )
    for index in range(3):
        service.invoke(
            "decision_add",
            {
                "id": f"D-{index}",
                "title": f"d{index}",
                "owner": "bob" if index else "alice",
                "context": "c",
                "decision": "d",
            },
        )
    service.invoke(
        "decision_status", {"id": "D-1", "status": "accepted", "actor": "bob"}
    )
    service.invoke(
        "message_send",
        {
            "id": "M-1",
            "sender": "alice",
            "recipient": "bob",
            "body": "x",
            "task": "T-0",
        },
    )
    service.invoke(
        "message_send", {"id": "M-2", "sender": "bob", "recipient": "team", "body": "y"}
    )
    service.invoke(
        "artifact_add",
        {"id": "A-1", "uri": "u1", "owner": "alice", "type": "doc", "task": ["T-0"]},
    )
    service.invoke(
        "artifact_add", {"id": "A-2", "uri": "u2", "owner": "bob", "type": "code"}
    )
    service.invoke(
        "escalation_add",
        {
            "id": "E-1",
            "raised_by": "alice",
            "owner": "o",
            "issue": "i",
            "requested_decision": "r",
        },
    )
    service.invoke(
        "review_add",
        {
            "id": "R-1",
            "reviewer": "bob",
            "artifact": "a",
            "scope": "s",
            "decision": "accepted",
            "task": "T-0",
        },
    )
    service.invoke("evidence_add", {"task": "T-0", "uri": "e1", "actor": "alice"})
    service.invoke(
        "evidence_add", {"task": "T-0", "uri": "e2", "actor": "bob", "type": "log"}
    )
    service.invoke("session_start", {"id": "s-a", "agent": "alice", "harness": "codex"})
    service.invoke("session_start", {"id": "s-b", "agent": "bob", "harness": "claude"})
    return service


def test_where_order_and_batch_read(database: Path) -> None:
    service = seed(database)
    # where combines with the existing flags and with itself (AND).
    assert ids(service.invoke("task_list", {"where": ["priority:le=2"]})) == [
        "T-0",
        "T-2",
    ]
    assert ids(
        service.invoke("task_list", {"status": "blocked", "where": ["priority:ge=4"]})
    ) == ["T-4"]
    # batch read: id:in, result in the list's order, unknown ids simply absent
    batch = service.invoke("task_list", {"where": ["id:in=T-3,T-0,T-missing"]})
    assert ids(batch) == ["T-0", "T-3"] and batch[0]["assignees"] == []
    # order-by with direction and deterministic id tiebreak
    assert ids(service.invoke("task_list", {"order_by": ["priority:desc"]})) == [
        "T-3",
        "T-4",
        "T-1",
        "T-2",
        "T-0",
    ]
    assert ids(
        service.invoke("task_list", {"order_by": ["status", "priority:desc"]})
    ) == ["T-4", "T-2", "T-3", "T-1", "T-0"]
    # updated-since on a table with updated_at; a timestamp form is enforced
    assert (
        len(service.invoke("task_list", {"updated_since": "2000-01-01T00:00:00+00:00"}))
        == 5
    )
    assert (
        service.invoke("task_list", {"updated_since": "2999-01-01T00:00:00+00:00"})
        == []
    )
    expect(
        "invalid_arguments",
        lambda: service.invoke("task_list", {"updated_since": "yesterday"}),
    )
    # the whitelist is the boundary: unknown column, disallowed op, bad value, bad order
    expect(
        "invalid_arguments",
        lambda: service.invoke("task_list", {"where": ["description:eq=x"]}),
    )
    expect(
        "invalid_arguments",
        lambda: service.invoke("task_list", {"where": ["status:ge=todo"]}),
    )
    expect(
        "invalid_arguments",
        lambda: service.invoke("task_list", {"where": ["priority:eq=high"]}),
    )
    expect(
        "invalid_arguments", lambda: service.invoke("task_list", {"order_by": ["tags"]})
    )
    # A single string is accepted as a one-element list, over the service too.
    assert ids(service.invoke("task_list", {"where": "status:in=blocked"})) == [
        "T-2",
        "T-4",
    ]
    # Through the CLI: repeatable flags, and the same refusal with exit 2.
    via_cli = cli(
        database,
        "task",
        "list",
        "--where",
        "status:eq=todo",
        "--where",
        "priority:ge=3",
        "--order-by",
        "priority:desc",
    )
    assert ids(json.loads(via_cli.stdout)["data"]) == ["T-3", "T-1"]
    rejected = cli(database, "task", "list", "--where", "notes:eq=x", check=False)
    assert (
        rejected.returncode == 2
        and json.loads(rejected.stderr)["error"]["details"]["field"] == "where"
    )


def test_every_list_and_show(database: Path) -> None:
    service = seed(database)
    assert ids(
        service.invoke("agent_list", {"where": ["actor_type:in=human,service"]})
    ) == ["bob", "carol"]
    assert ids(service.invoke("agent_list", {"order_by": ["id:desc"]})) == [
        "carol",
        "bob",
        "alice",
    ]
    assert ids(service.invoke("session_list", {"where": ["harness:eq=claude"]})) == [
        "s-b"
    ]
    assert ids(
        service.invoke(
            "session_list",
            {"where": ["status:eq=active"], "order_by": ["started_at:desc", "id:desc"]},
        )
    ) == ["s-b", "s-a"]
    assert ids(service.invoke("decision_list", {"where": ["status:eq=accepted"]})) == [
        "D-1"
    ]
    assert ids(
        service.invoke(
            "decision_list", {"where": ["owner_id:eq=bob"], "order_by": ["id:desc"]}
        )
    ) == ["D-2", "D-1"]
    assert ids(service.invoke("message_list", {"where": ["sender_id:eq=bob"]})) == [
        "M-2"
    ]
    assert ids(
        service.invoke(
            "message_list", {"recipient": "bob", "where": ["task_id:eq=T-0"]}
        )
    ) == ["M-1"]
    assert ids(service.invoke("artifact_list", {"where": ["type:eq=code"]})) == ["A-2"]
    assert [
        row["id"] for row in service.invoke("artifact_list", {"order_by": ["uri:desc"]})
    ] == ["A-2", "A-1"]
    assert ids(
        service.invoke("escalation_list", {"where": ["status:in=open,in_review"]})
    ) == ["E-1"]
    assert ids(service.invoke("review_list", {"where": ["decision:eq=accepted"]})) == [
        "R-1"
    ]
    assert [
        row["uri"]
        for row in service.invoke(
            "evidence_list", {"task": "T-0", "where": ["evidence_type:eq=log"]}
        )
    ] == ["e2"]
    assert [
        row["uri"]
        for row in service.invoke(
            "evidence_list", {"task": "T-0", "order_by": ["id:desc"]}
        )
    ] == ["e2", "e1"]
    expect(
        "invalid_arguments",
        lambda: service.invoke("message_list", {"where": ["body:eq=x"]}),
    )
    # Sessions carry no updated_at: the descriptor refuses the column.
    expect(
        "invalid_arguments",
        lambda: service.invoke(
            "session_list", {"where": ["updated_at:ge=2026-01-01T00:00:00+00:00"]}
        ),
    )

    # show for every entity that has an id, and not_found for a missing one
    assert service.invoke("agent_show", {"id": "alice"})["actor_type"] == "ai"
    assert service.invoke("session_show", {"id": "s-a"})["harness"] == "codex"
    artifact = service.invoke("artifact_show", {"id": "A-1"})
    assert artifact["related_tasks"] == ["T-0"] and artifact["reviewers"] == []
    assert service.invoke("decision_show", {"id": "D-1"})["status"] == "accepted"
    assert service.invoke("message_show", {"id": "M-1"})["task_id"] == "T-0"
    assert service.invoke("review_show", {"id": "R-1"})["reviewer_id"] == "bob"
    assert service.invoke("escalation_show", {"id": "E-1"})["status"] == "open"
    missing = expect(
        "not_found", lambda: service.invoke("decision_show", {"id": "D-9"})
    )
    assert missing.details == {"resource": "decision D-9"}
    shown = cli(database, "artifact", "show", "A-1")
    assert json.loads(shown.stdout)["data"]["id"] == "A-1"
    assert "audit_range" not in json.loads(shown.stdout)


def main() -> int:
    for test in (test_where_order_and_batch_read, test_every_list_and_show):
        with tempfile.TemporaryDirectory(prefix="coordination-query-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Query surface qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
