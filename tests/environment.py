#!/usr/bin/env python3
"""Qualify the 1.4.1 environment additions.

COORDINATION_DB and the main-worktree fallback reach a project from outside
its directory tree; doctor reports filesystems that break SQLite WAL; and
the installer and verifier can keep the managed ignore block out of the
tracked .gitignore.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.entities import diagnostics  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


TOOL = ROOT / "scripts" / "coordination.py"


def run(
    *arguments: str, cwd: Path, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "COORDINATION_DB"}
    env.update(environment or {})
    return subprocess.run(
        list(arguments), cwd=cwd, env=env, text=True, capture_output=True
    )


def make_project(root: Path) -> Path:
    coordination = root / ".coordination"
    coordination.mkdir(parents=True)
    (coordination / "config.yml").write_text(
        "version: 1\nbackend: sqlite\ndatabase: coordination.sqlite3\n"
    )
    database = coordination / "coordination.sqlite3"
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    service.invoke("agent_add", {"id": "alice", "name": "a", "role": "r"})
    return database


def test_coordination_db_environment(root: Path) -> None:
    database = make_project(root / "project")
    elsewhere = root / "elsewhere"
    elsewhere.mkdir()
    found = run(
        str(TOOL),
        "agent",
        "list",
        cwd=elsewhere,
        environment={"COORDINATION_DB": str(database)},
    )
    assert found.returncode == 0, found.stderr
    assert [agent["id"] for agent in json.loads(found.stdout)["data"]] == ["alice"]

    missing = run(str(TOOL), "agent", "list", cwd=elsewhere)
    assert missing.returncode == 5
    assert "COORDINATION_DB" in json.loads(missing.stderr)["error"]["message"]

    ignored_empty = run(
        str(TOOL), "agent", "list", cwd=elsewhere, environment={"COORDINATION_DB": " "}
    )
    assert ignored_empty.returncode == 5  # empty means unset, not "here"

    rejected = run(
        str(TOOL),
        "agent",
        "list",
        cwd=elsewhere,
        environment={"COORDINATION_DB": str(elsewhere)},
    )
    assert rejected.returncode == 2
    assert json.loads(rejected.stderr)["error"]["code"] == "invalid_arguments"

    other = make_project(root / "other")
    flag_wins = run(
        str(TOOL),
        "--db",
        str(other),
        "doctor",
        cwd=elsewhere,
        environment={"COORDINATION_DB": str(database)},
    )
    assert json.loads(flag_wins.stdout)["data"]["database"] == str(other.resolve())


def test_main_worktree_fallback(root: Path) -> None:
    if shutil.which("git") is None:
        print("  (git unavailable; worktree fallback not exercised)")
        return
    main = root / "main"
    main.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    for command in (
        [*git, "init", "-q"],
        [*git, "commit", "-q", "--allow-empty", "-m", "seed"],
        [*git, "worktree", "add", "-q", str(root / "linked")],
    ):
        completed = run(*command, cwd=main)
        assert completed.returncode == 0, completed.stderr
    database = make_project(main)
    found = run(str(TOOL), "doctor", cwd=root / "linked")
    assert found.returncode == 0, found.stderr
    assert json.loads(found.stdout)["data"]["database"] == str(database.resolve())


def test_filesystem_report(root: Path) -> None:
    linux = diagnostics.mount_entries_linux(
        "/dev/sda1 / ext4 rw 0 0\n"
        "host:/export /mnt/shared nfs4 rw 0 0\n"
        "vmshare /media/my\\040share fuse.vmhgfs-fuse rw 0 0\n"
    )
    assert diagnostics.filesystem_type_for(Path("/mnt/shared/x"), linux) == "nfs4"
    assert diagnostics.filesystem_type_for(Path("/home/x"), linux) == "ext4"
    assert (
        diagnostics.filesystem_type_for(Path("/media/my share/db"), linux)
        == "fuse.vmhgfs-fuse"
    )
    darwin = diagnostics.mount_entries_darwin(
        "/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\n"
        "//user@server/share on /Volumes/share (smbfs, nodev, nosuid)\n"
    )
    assert diagnostics.filesystem_type_for(Path("/Volumes/share/p"), darwin) == "smbfs"
    for shared in ("nfs4", "smbfs", "fuse.sshfs", "virtiofs", "9p", "macfuse"):
        assert diagnostics.is_shared_filesystem(shared), shared
    for local in ("ext4", "apfs", "xfs", "btrfs", None):
        assert not diagnostics.is_shared_filesystem(local), local

    database = make_project(root / "project")
    service = CoordinationService(db=str(database))
    report = service.invoke("doctor", {})
    assert {
        "filesystem_type",
        "filesystem_warning",
        "filesystem_fuse_leftovers",
    } <= set(report)
    assert report["healthy"] is True
    (database.parent / ".fuse_hidden000001").write_text("")
    flagged = service.invoke("doctor", {})
    assert flagged["filesystem_fuse_leftovers"] == [".fuse_hidden000001"]
    assert flagged["filesystem_warning"] is not None
    assert flagged["healthy"] is True  # a report, never a failure


def test_installer_ignore_options(root: Path) -> None:
    if shutil.which("git") is None:
        print("  (git unavailable; installer ignore options not exercised)")
        return
    installer = str(ROOT / "scripts" / "install.sh")
    verifier = str(ROOT / "scripts" / "verify-install.sh")

    plain = root / "plain"
    plain.mkdir()
    (plain / ".gitignore").write_text("node_modules/\n")
    installed = run(
        installer,
        "--target",
        str(plain),
        "--adapter",
        "sqlite",
        "--no-gitignore",
        cwd=ROOT,
    )
    assert installed.returncode == 0, installed.stderr
    assert (plain / ".gitignore").read_text() == "node_modules/\n"
    verified = run(verifier, "--no-gitignore", str(plain), cwd=ROOT)
    assert verified.returncode == 0, verified.stderr
    unverified = run(verifier, str(plain), cwd=ROOT)
    assert unverified.returncode != 0

    excluded = root / "excluded"
    excluded.mkdir()
    assert run("git", "init", "-q", cwd=excluded).returncode == 0
    (excluded / ".gitignore").write_text("dist/\n")
    installed = run(
        installer,
        "--target",
        str(excluded),
        "--adapter",
        "sqlite",
        "--ignore-file",
        ".git/info/exclude",
        cwd=ROOT,
    )
    assert installed.returncode == 0, installed.stderr
    assert (excluded / ".gitignore").read_text() == "dist/\n"
    exclude = (excluded / ".git" / "info" / "exclude").read_text()
    assert "# agentic-project-scaffold-lite sqlite state" in exclude
    verified = run(
        verifier, "--ignore-file", ".git/info/exclude", str(excluded), cwd=ROOT
    )
    assert verified.returncode == 0, verified.stderr

    for bad in ("/etc/passwd", "../outside", "a/../../b"):
        refused = run(
            installer,
            "--target",
            str(excluded),
            "--adapter",
            "sqlite",
            "--ignore-file",
            bad,
            cwd=ROOT,
        )
        assert refused.returncode == 2, (bad, refused.stderr)


def main() -> int:
    for test in (
        test_coordination_db_environment,
        test_main_worktree_fallback,
        test_filesystem_report,
        test_installer_ignore_options,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-environment-") as name:
            test(Path(name).resolve())
    print("Environment qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
