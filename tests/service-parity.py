#!/usr/bin/env python3
"""Prove CLI and transport-neutral services share state and audit semantics."""

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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="coordination-service-") as temporary:
        database = Path(temporary) / "coordination.sqlite3"
        service = CoordinationService(db=str(database))
        assert service.invoke("init", {})["status"] == "initialized"
        service.invoke(
            "agent_add",
            {
                "id": "engineering",
                "name": "Engineering",
                "role": "engineering",
                "actor_type": "ai",
                "responsibilities": "",
                "goal": "",
                "operating_style": "",
                "decision_authority": "",
                "review_authority": "",
                "escalation_rules": "",
                "unavailable_for": "",
                "actor": None,
            },
        )
        service.invoke(
            "session_start",
            {
                "id": "service-run",
                "agent": "engineering",
                "harness": "service-test",
                "model": "test",
            },
        )
        service.invoke(
            "agent_add",
            {
                "id": "reviewer",
                "name": "Reviewer",
                "role": "review",
                "actor_type": "human",
                "responsibilities": "",
                "goal": "",
                "operating_style": "",
                "decision_authority": "",
                "review_authority": "",
                "escalation_rules": "",
                "unavailable_for": "",
                "actor": "engineering",
            },
        )
        CoordinationService(
            db=str(database),
            session="service-run",
        ).invoke(
            "task_create",
            {
                "id": "SERVICE-1",
                "title": "Created by service",
                "actor": "engineering",
                "description": "",
                "priority": 3,
                "tags": "",
                "acceptance": "",
                "next_steps": "",
                "blocked_claims": "",
                "assignee": ["engineering"],
            },
        )

        cli = subprocess.run(
            [
                str(ROOT / "scripts" / "coordination.py"),
                "--db",
                str(database),
                "task",
                "show",
                "SERVICE-1",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        cli_task = json.loads(cli.stdout)["data"]
        service_task = service.invoke("task_show", {"id": "SERVICE-1"})
        assert cli_task == service_task

        assigned = subprocess.run(
            [
                str(ROOT / "scripts" / "coordination.py"),
                "--db",
                str(database),
                "--session",
                "service-run",
                "task",
                "assign",
                "SERVICE-1",
                "--actor",
                "engineering",
                "--add",
                "reviewer",
                "--if-revision",
                "1",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        assignment = json.loads(assigned.stdout)["data"]
        assert assignment == {
            "id": "SERVICE-1",
            "revision": 2,
            "assignees": ["engineering", "reviewer"],
        }
        assert service.invoke("task_show", {"id": "SERVICE-1"})["assignees"] == [
            "engineering",
            "reviewer",
        ]

        updated = subprocess.run(
            [
                str(ROOT / "scripts" / "coordination.py"),
                "--db",
                str(database),
                "--session",
                "service-run",
                "task",
                "update",
                "SERVICE-1",
                "--actor",
                "engineering",
                "--if-revision",
                "2",
                "--description",
                "Updated by CLI",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        assert json.loads(updated.stdout)["data"]["revision"] == 3
        assert service.invoke("task_show", {"id": "SERVICE-1"})["description"] == (
            "Updated by CLI"
        )

        try:
            service.invoke(
                "task_update",
                {
                    "id": "SERVICE-1",
                    "actor": "engineering",
                    "if_revision": 2,
                    "title": "stale",
                    "description": None,
                    "priority": None,
                    "tags": None,
                    "acceptance": None,
                    "next_steps": None,
                    "blocked_claims": None,
                },
            )
        except CoordinationError as error:
            assert error.code == "stale_task_revision"
            assert error.exit_code == 4
        else:
            raise AssertionError("stale service revision unexpectedly succeeded")

        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                "SELECT actor, session_id, action FROM audit_log "
                "WHERE object_type = 'task' AND object_id = 'SERVICE-1' "
                "ORDER BY id"
            ).fetchall()
        assert rows == [
            ("engineering", "service-run", "create"),
            ("engineering", "service-run", "assign"),
            ("engineering", "service-run", "update"),
        ]

    print("Service/CLI parity tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
