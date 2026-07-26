#!/usr/bin/env python3
"""Release qualification for the optional local stdio MCP transport."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from typing import AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent.parent


def run(
    *arguments: str,
    cwd: Path = ROOT,
    check: bool = True,
    environment_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = (
        f"{Path(sys.executable).parent}{os.pathsep}{environment.get('PATH', '')}"
    )
    environment.update(environment_overrides or {})
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        check=check,
        text=True,
        capture_output=True,
    )


def envelope(result: object) -> dict[str, object]:
    value = getattr(result, "structuredContent", None)
    assert isinstance(value, dict), result
    return value


@asynccontextmanager
async def client(
    launcher: Path,
    project: Path,
    environment_overrides: dict[str, str] | None = None,
) -> AsyncIterator[ClientSession]:
    environment = os.environ.copy()
    environment["PATH"] = (
        f"{Path(sys.executable).parent}{os.pathsep}{environment.get('PATH', '')}"
    )
    environment.update(environment_overrides or {})
    parameters = StdioServerParameters(
        command=str(launcher),
        cwd=project,
        env=environment,
    )
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session


async def qualify(project: Path) -> None:
    bundle = project / ".agents" / "agentic-project-scaffold-lite"
    launcher = bundle / "bin" / "coordination-mcp"
    cli = bundle / "bin" / "coordination"
    database = project / ".coordination" / "coordination.sqlite3"

    async with client(launcher, project) as codex:
        tools = await codex.list_tools()
        names = {tool.name for tool in tools.tools}
        required = {
            "coordination_project_status",
            "coordination_agent_register",
            "coordination_session_start",
            "coordination_task_create",
            "coordination_task_claim",
            "coordination_task_release",
            "coordination_message_send",
            "coordination_backup",
            "coordination_restore",
        }
        assert required <= names
        tools_by_name = {tool.name: tool for tool in tools.tools}
        for tool_name, fields in (
            ("coordination_task_create", ("assignees",)),
            ("coordination_task_assign", ("add", "remove")),
            ("coordination_artifact_add", ("tasks", "reviewers")),
        ):
            properties = tools_by_name[tool_name].inputSchema["properties"]
            for field in fields:
                schema = properties[field]
                if "anyOf" in schema:
                    schema = next(
                        option
                        for option in schema["anyOf"]
                        if option.get("type") == "array"
                    )
                assert schema["maxItems"] == 500, (tool_name, field, schema)

        result = await codex.call_tool("coordination_project_status", {})
        assert not result.isError
        assert envelope(result)["data"]["healthy"] is True

        for actor, name in (
            ("engineering", "Engineering"),
            ("reviewer", "Reviewer"),
        ):
            result = await codex.call_tool(
                "coordination_agent_register",
                {
                    "id": actor,
                    "name": name,
                    "role": actor,
                    "actor_type": "ai",
                },
            )
            assert not result.isError, envelope(result)

        for session_id, actor, harness in (
            ("codex-run", "engineering", "codex"),
            ("claude-run", "reviewer", "claude"),
        ):
            result = await codex.call_tool(
                "coordination_session_start",
                {
                    "id": session_id,
                    "agent": actor,
                    "harness": harness,
                    "model": "test-model",
                },
            )
            assert not result.isError, envelope(result)

        created = await codex.call_tool(
            "coordination_task_create",
            {
                "id": "MCP-1",
                "title": "Shared transport state",
                "actor": "engineering",
                "assignees": ["engineering", "reviewer"],
                "session": "codex-run",
            },
        )
        assert not created.isError, envelope(created)

        cli_state = json.loads(
            run(str(cli), "task", "show", "MCP-1", cwd=project).stdout
        )
        assert cli_state["data"]["id"] == "MCP-1"
        assert cli_state["data"]["assignees"] == ["engineering", "reviewer"]

        stale = await codex.call_tool(
            "coordination_task_update",
            {
                "id": "MCP-1",
                "actor": "engineering",
                "if_revision": 999,
                "title": "must not publish",
                "session": "codex-run",
            },
        )
        assert stale.isError
        stale_error = envelope(stale)["error"]
        assert stale_error["code"] == "stale_task_revision", stale_error
        assert stale_error["exit_code"] == 4

        confirmation = await codex.call_tool(
            "coordination_backup",
            {
                "output": str(project / "backup.sqlite3"),
                "confirmation": "wrong",
            },
        )
        assert confirmation.isError
        assert envelope(confirmation)["error"]["code"] == "confirmation_required"

        malformed = await codex.call_tool(
            "coordination_task_list",
            {"limit": "not-an-integer"},
        )
        assert malformed.isError
        assert malformed.structuredContent is None

    async with (
        client(launcher, project) as codex,
        client(launcher, project) as claude,
    ):
        first, second = await asyncio.gather(
            codex.call_tool(
                "coordination_task_claim",
                {
                    "id": "MCP-1",
                    "agent": "engineering",
                    "if_revision": 1,
                    "session": "codex-run",
                },
            ),
            claude.call_tool(
                "coordination_task_claim",
                {
                    "id": "MCP-1",
                    "agent": "reviewer",
                    "if_revision": 1,
                    "session": "claude-run",
                },
            ),
        )
        results = [first, second]
        assert sum(not result.isError for result in results) == 1
        failure = next(result for result in results if result.isError)
        failure_error = envelope(failure)["error"]
        assert failure_error["code"] in {
            "task_already_claimed",
            "stale_task_revision",
        }, failure_error

    state = json.loads(run(str(cli), "task", "show", "MCP-1", cwd=project).stdout)
    task = state["data"]
    assert task["revision"] == 2
    assert task["status"] == "in_progress"
    assert task["claimed_by"] in {"engineering", "reviewer"}
    expected_session = (
        "codex-run" if task["claimed_by"] == "engineering" else "claude-run"
    )
    assert task["claim_session_id"] == expected_session

    blocked_end = json.loads(
        run(
            str(cli),
            "session",
            "end",
            expected_session,
            cwd=project,
            check=False,
        ).stderr
    )
    assert blocked_end["error"]["code"] == "session_has_active_claims"

    with sqlite3.connect(database) as connection:
        sessions = connection.execute(
            "SELECT id, agent_id, harness, model FROM agent_sessions ORDER BY id"
        ).fetchall()
        assert sessions == [
            ("claude-run", "reviewer", "claude", "test-model"),
            ("codex-run", "engineering", "codex", "test-model"),
        ]
        events = connection.execute(
            "SELECT actor, session_id, action FROM audit_log "
            "WHERE object_type = 'task' AND object_id = 'MCP-1' "
            "ORDER BY id"
        ).fetchall()
        assert events[0] == ("engineering", "codex-run", "create")
        assert events[-1][1] == expected_session
        assert events[-1][2] == "claim"

    # A fresh server process sees the same durable state after restart.
    async with client(launcher, project) as restarted:
        inspected = await restarted.call_tool(
            "coordination_task_inspect",
            {"id": "MCP-1"},
        )
        assert not inspected.isError
        assert envelope(inspected)["data"]["claim_session_id"] == expected_session

        released = await restarted.call_tool(
            "coordination_task_release",
            {
                "id": "MCP-1",
                "status": "todo",
                "actor": task["claimed_by"],
                "if_revision": 2,
                "session": expected_session,
            },
        )
        assert not released.isError, envelope(released)

        created = await restarted.call_tool(
            "coordination_task_create",
            {
                "id": "MCP-2",
                "title": "Concurrent CLI and MCP",
                "actor": "engineering",
                "assignees": ["engineering", "reviewer"],
                "session": "codex-run",
            },
        )
        assert not created.isError, envelope(created)

        cli_process = await asyncio.create_subprocess_exec(
            str(cli),
            "--session",
            "codex-run",
            "task",
            "claim",
            "MCP-2",
            "--agent",
            "engineering",
            "--if-revision",
            "1",
            cwd=project,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        mcp_claim, cli_streams = await asyncio.gather(
            restarted.call_tool(
                "coordination_task_claim",
                {
                    "id": "MCP-2",
                    "agent": "reviewer",
                    "if_revision": 1,
                    "session": "claude-run",
                },
            ),
            cli_process.communicate(),
        )
        cli_stdout, cli_stderr = cli_streams
        assert sum((not mcp_claim.isError, cli_process.returncode == 0)) == 1
        if cli_process.returncode == 0:
            assert json.loads(cli_stdout)["ok"] is True
        else:
            assert json.loads(cli_stderr)["error"]["code"] in {
                "task_already_claimed",
                "stale_task_revision",
            }

    with sqlite3.connect(database, isolation_level=None) as lock:
        lock.execute("BEGIN IMMEDIATE")
        async with client(
            launcher,
            project,
            {"COORDINATION_BUSY_TIMEOUT_MS": "0"},
        ) as locked_client:
            busy = await locked_client.call_tool(
                "coordination_task_update",
                {
                    "id": "MCP-2",
                    "actor": "engineering",
                    "if_revision": 2,
                    "description": "must not commit",
                },
            )
            assert busy.isError
            assert envelope(busy)["error"]["code"] == "database_busy"
        lock.rollback()

    final_task = json.loads(
        run(str(cli), "task", "show", "MCP-2", cwd=project).stdout
    )["data"]
    assert final_task["description"] == ""
    release_session = final_task["claim_session_id"]
    release_actor = final_task["claimed_by"]
    async with client(launcher, project) as final_client:
        released = await final_client.call_tool(
            "coordination_task_release",
            {
                "id": "MCP-2",
                "status": "todo",
                "actor": release_actor,
                "if_revision": 2,
                "session": release_session,
            },
        )
        assert not released.isError, envelope(released)
        for session_id in ("codex-run", "claude-run"):
            ended = await final_client.call_tool(
                "coordination_session_end",
                {"id": session_id},
            )
            assert not ended.isError, envelope(ended)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="coordination-mcp-") as temporary:
        project = Path(temporary)
        installer = ROOT / "scripts" / "install.sh"
        verifier = ROOT / "scripts" / "verify-install.sh"

        # A 1.1-compatible CLI-only SQLite installation upgrades in place:
        # managed files change, while configuration and schema-v1 state survive.
        run(
            str(installer),
            "--target",
            str(project),
            "--adapter",
            "sqlite",
        )
        cli = (
            project
            / ".agents"
            / "agentic-project-scaffold-lite"
            / "bin"
            / "coordination"
        )
        run(
            str(cli),
            "agent",
            "add",
            "--id",
            "upgrade-preserved",
            "--name",
            "Upgrade Preserved",
            "--role",
            "qualification",
            cwd=project,
        )
        run(
            str(installer),
            "--target",
            str(project),
            "--adapter",
            "sqlite",
            "--with-mcp",
        )
        run(
            str(verifier),
            "--with-mcp",
            str(project),
        )
        preserved = json.loads(
            run(str(cli), "agent", "list", cwd=project).stdout
        )["data"]
        assert any(row["id"] == "upgrade-preserved" for row in preserved)

        # The verifier must not execute target-controlled bytes after detecting
        # that the installed launcher is not canonical.
        launcher = (
            project
            / ".agents"
            / "agentic-project-scaffold-lite"
            / "bin"
            / "coordination-mcp"
        )
        execution_marker = project / "noncanonical-launcher-executed"
        launcher.write_text(
            "#!/bin/sh\n"
            f": > {shlex.quote(str(execution_marker))}\n"
            "exit 0\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        rejected = run(
            str(verifier),
            "--with-mcp",
            str(project),
            check=False,
        )
        assert rejected.returncode == 1, rejected
        assert "differs from the canonical source" in rejected.stderr
        assert not execution_marker.exists()

        # Reinstall repairs the managed launcher without replacing database
        # state, and a supported dependency still verifies normally.
        run(
            str(installer),
            "--target",
            str(project),
            "--adapter",
            "sqlite",
            "--with-mcp",
        )
        run(str(verifier), "--with-mcp", str(project))
        preserved = json.loads(
            run(str(cli), "agent", "list", cwd=project).stdout
        )["data"]
        assert any(row["id"] == "upgrade-preserved" for row in preserved)

        # A dependency check failure is a verifier failure; it cannot be
        # mistaken for a healthy MCP installation.
        fake_bin = project / "unsupported-mcp-bin"
        fake_bin.mkdir()
        fake_python = fake_bin / "python3"
        fake_python.write_text(
            "#!/bin/sh\n"
            'for argument in "$@"; do\n'
            '  case "$argument" in\n'
            "    */check-mcp-dependency.py) exit 1 ;;\n"
            "  esac\n"
            "done\n"
            f"exec {shlex.quote(sys.executable)} \"$@\"\n",
            encoding="utf-8",
        )
        fake_python.chmod(0o755)
        unsupported = run(
            str(verifier),
            "--with-mcp",
            str(project),
            check=False,
            environment_overrides={
                "PATH": f"{fake_bin}{os.pathsep}/usr/bin{os.pathsep}/bin"
            },
        )
        assert unsupported.returncode == 1, unsupported
        assert "requires mcp>=1.28.1,<2" in unsupported.stderr

        asyncio.run(qualify(project))
    print("MCP stdio integration qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
