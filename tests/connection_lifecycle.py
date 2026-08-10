#!/usr/bin/env python3
"""Resource-lifecycle qualification for long-lived coordination processes.

A one-shot CLI process releases everything at exit, so nothing before 1.2.1
noticed that entity functions never close the connections they open. A
long-lived transport does notice: every call leaked a shared advisory lock on
the database lock file until `restore`, the one operation needing the exclusive
lock, could no longer take it -- and neither could any other process.

These probes fail if that regresses.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.core import _CONNECTION_LOCKS  # noqa: E402
from coordination.errors import CoordinationError  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


CALLS = 200


def _open_lock_files() -> int:
    """Count this process's open descriptors against coordination lock files."""
    descriptors = Path("/dev/fd")
    if not descriptors.is_dir():  # pragma: no cover - non-POSIX fallback
        return len(_CONNECTION_LOCKS)
    total = 0
    for entry in descriptors.iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.endswith(".lock"):
            total += 1
    return total


def _project(root: Path) -> tuple[Path, Path]:
    subprocess.run(
        [
            str(ROOT / "scripts" / "install.sh"),
            "--target",
            str(root),
            "--adapter",
            "sqlite",
        ],
        check=True,
        capture_output=True,
    )
    return root / ".coordination" / "coordination.sqlite3", root


def test_repeated_calls_do_not_accumulate_locks(database: Path) -> None:
    service = CoordinationService(db=str(database))
    service.agent_add(id="alice", name="Alice", role="engineering")

    baseline_locks = _open_lock_files()
    baseline_tracked = len(_CONNECTION_LOCKS)
    for _ in range(CALLS):
        service.agent_list()
        service.task_list()

    assert _open_lock_files() == baseline_locks, (
        f"leaked lock descriptors over {CALLS} calls: "
        f"{baseline_locks} -> {_open_lock_files()}"
    )
    assert len(_CONNECTION_LOCKS) == baseline_tracked, (
        f"leaked tracked connections over {CALLS} calls: "
        f"{baseline_tracked} -> {len(_CONNECTION_LOCKS)}"
    )


def test_restore_succeeds_after_prior_calls(database: Path, project: Path) -> None:
    """The exact shape of the shipped MCP tool: reads, then a restore."""
    service = CoordinationService(db=str(database))
    backup = project / ".coordination" / "backups" / "lifecycle.sqlite3"
    service.backup(output=str(backup), force=True)

    for _ in range(5):
        service.agent_list()
        service.project_status()

    result = service.restore(input=str(backup), actor="alice", force=True)
    assert isinstance(result, dict), result
    assert result.get("verified") is True, result


def test_restore_over_the_service_dispatcher(database: Path, project: Path) -> None:
    """Same guarantee through `invoke`, which is what every transport calls."""
    service = CoordinationService(db=str(database))
    backup = project / ".coordination" / "backups" / "dispatch.sqlite3"
    service.invoke("backup", {"output": str(backup), "force": True})
    for _ in range(5):
        service.invoke("agent_list", {})
    result = service.invoke(
        "restore",
        {"input": str(backup), "actor": "alice", "force": True},
    )
    assert isinstance(result, dict), result
    assert result.get("verified") is True, result


def test_live_process_does_not_block_cli_restore(database: Path, project: Path) -> None:
    """A separate process holding the runtime must not block a CLI restore."""
    service = CoordinationService(db=str(database))
    backup = project / ".coordination" / "backups" / "crossproc.sqlite3"
    service.backup(output=str(backup), force=True)

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys, time;"
                f"sys.path.insert(0, {str(ROOT)!r});"
                "from coordination.service import CoordinationService;"
                f"s = CoordinationService(db={str(database)!r});"
                "s.agent_list();"
                "print('ready', flush=True);"
                "time.sleep(120)"
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        completed = subprocess.run(
            [
                str(
                    project
                    / ".agents"
                    / "agentic-project-scaffold-lite"
                    / "bin"
                    / "coordination"
                ),
                "restore",
                "--input",
                str(backup),
                "--actor",
                "alice",
                "--force",
            ],
            cwd=project,
            capture_output=True,
            text=True,
        )
    finally:
        holder.kill()
        holder.wait()

    assert completed.returncode == 0, (
        f"a live coordination process blocked CLI restore: "
        f"exit={completed.returncode} stderr={completed.stderr}"
    )


def test_failed_operations_still_release_their_locks(database: Path) -> None:
    """The scope must unwind on the error path too."""
    service = CoordinationService(db=str(database))
    baseline = _open_lock_files()
    for _ in range(50):
        try:
            service.task_show(id="definitely-missing")
        except CoordinationError as error:
            assert error.code == "not_found", error.code
        else:  # pragma: no cover - the task must not exist
            raise AssertionError("expected a not_found failure")
    assert _open_lock_files() == baseline, (
        f"failed operations leaked descriptors: {baseline} -> {_open_lock_files()}"
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "project"
        root.mkdir()
        database, project = _project(root)
        test_repeated_calls_do_not_accumulate_locks(database)
        test_failed_operations_still_release_their_locks(database)
        test_restore_succeeds_after_prior_calls(database, project)
        test_restore_over_the_service_dispatcher(database, project)
        test_live_process_does_not_block_cli_restore(database, project)
    print("Connection lifecycle qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
