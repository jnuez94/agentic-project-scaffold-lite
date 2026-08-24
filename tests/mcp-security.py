#!/usr/bin/env python3
"""Security regression coverage for MCP launchers and aggregate inputs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.core import MAX_IDENTIFIER_ARRAY_ITEMS, require_unique  # noqa: E402
from coordination.errors import CoordinationError  # noqa: E402
from coordination.service import (  # noqa: E402
    SERVICE_OPERATIONS,
    CoordinationService,
    _identifiers,
)
from coordination_mcp_launcher import _discover_launcher  # noqa: E402


@contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def assert_installation_failure(function: object, message: str) -> None:
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        try:
            function()
        except SystemExit as error:
            assert error.code == 5, error.code
        else:
            raise AssertionError("unsafe MCP launcher path was accepted")
    assert message in stderr.getvalue(), stderr.getvalue()


def test_generic_bootstrap_paths(temporary: Path) -> None:
    project = temporary / "project"
    nested = project / "nested"
    launcher = (
        project
        / ".agents"
        / "agentic-project-scaffold-lite"
        / "bin"
        / "coordination-mcp"
    )
    launcher.parent.mkdir(parents=True)
    launcher.write_text("# legitimate launcher\n", encoding="utf-8")
    nested.mkdir()
    with working_directory(nested):
        assert _discover_launcher() == launcher.resolve()

    external = temporary / "external"
    external_launcher = (
        external / "agentic-project-scaffold-lite" / "bin" / "coordination-mcp"
    )
    external_launcher.parent.mkdir(parents=True)
    external_launcher.write_text("# external launcher\n", encoding="utf-8")
    alias_project = temporary / "alias-project"
    alias_nested = alias_project / "nested"
    alias_project.mkdir()
    (alias_project / ".agents").symlink_to(external, target_is_directory=True)
    alias_nested.mkdir()
    with working_directory(alias_nested):
        assert_installation_failure(
            _discover_launcher,
            "must not contain symbolic links",
        )

    hardlink_project = temporary / "hardlink-project"
    hardlink_nested = hardlink_project / "nested"
    hardlink_launcher = (
        hardlink_project
        / ".agents"
        / "agentic-project-scaffold-lite"
        / "bin"
        / "coordination-mcp"
    )
    hardlink_launcher.parent.mkdir(parents=True)
    os.link(launcher, hardlink_launcher)
    hardlink_nested.mkdir()
    with working_directory(hardlink_nested):
        assert_installation_failure(
            _discover_launcher,
            "must not have hard-link aliases",
        )


def assert_installed_runtime_alias_rejected(
    temporary: Path,
    alias_name: str,
) -> None:
    bundle = temporary / f"bundle-{alias_name}"
    launcher = bundle / "bin" / "coordination-mcp"
    package = bundle / "lib" / "coordination"
    external_package = temporary / f"external-{alias_name}"
    (bundle / "sqlite").mkdir(parents=True)
    package.mkdir(parents=True)
    external_package.mkdir()
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_bytes((ROOT / "scripts" / "coordination-mcp.py").read_bytes())
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "service.py").write_text(
        "from coordination import entities\n",
        encoding="utf-8",
    )
    if alias_name == "transports":
        (external_package / "__init__.py").write_text("", encoding="utf-8")
        (external_package / "mcp.py").write_text(
            "raise RuntimeError('external transport imported')\n",
            encoding="utf-8",
        )
        (package / "transports").symlink_to(
            external_package,
            target_is_directory=True,
        )
        (package / "entities").mkdir()
        (package / "entities" / "__init__.py").write_text("", encoding="utf-8")
    else:
        transports = package / "transports"
        transports.mkdir()
        (transports / "__init__.py").write_text("", encoding="utf-8")
        (transports / "mcp.py").write_text(
            "from coordination import service\ndef main():\n    return 0\n",
            encoding="utf-8",
        )
        (external_package / "__init__.py").write_text(
            "raise RuntimeError('external entities imported')\n",
            encoding="utf-8",
        )
        (package / "entities").symlink_to(
            external_package,
            target_is_directory=True,
        )
    (bundle / "sqlite" / "schema.sql").write_text(
        "PRAGMA user_version = 1;\n",
        encoding="utf-8",
    )
    (bundle / "VERSION").write_text("1.2.0\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(launcher), "--help"],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 5, result
    assert "canonical coordination MCP runtime is incomplete" in result.stderr
    assert "external transport imported" not in result.stderr
    assert "external entities imported" not in result.stderr


def test_installed_runtime_alias(temporary: Path) -> None:
    assert_installed_runtime_alias_rejected(temporary, "transports")
    assert_installed_runtime_alias_rejected(temporary, "entities")

    hardlink_bundle = temporary / "bundle-hardlink"
    hardlink_package = hardlink_bundle / "lib" / "coordination"
    hardlink_transport = hardlink_package / "transports"
    (hardlink_bundle / "bin").mkdir(parents=True)
    (hardlink_bundle / "sqlite").mkdir()
    hardlink_transport.mkdir(parents=True)
    (hardlink_bundle / "bin" / "coordination-mcp").write_bytes(
        (ROOT / "scripts" / "coordination-mcp.py").read_bytes()
    )
    (hardlink_package / "__init__.py").write_text("", encoding="utf-8")
    (hardlink_package / "service.py").write_text("", encoding="utf-8")
    (hardlink_transport / "__init__.py").write_text("", encoding="utf-8")
    (hardlink_transport / "mcp.py").write_text(
        "def main():\n    return 0\n",
        encoding="utf-8",
    )
    external_core = temporary / "external-core.py"
    external_core.write_text(
        "raise RuntimeError('external core imported')\n",
        encoding="utf-8",
    )
    os.link(external_core, hardlink_package / "core.py")
    (hardlink_bundle / "sqlite" / "schema.sql").write_text(
        "PRAGMA user_version = 1;\n",
        encoding="utf-8",
    )
    (hardlink_bundle / "VERSION").write_text("1.2.0\n", encoding="utf-8")
    hardlink_result = subprocess.run(
        [
            sys.executable,
            str(hardlink_bundle / "bin" / "coordination-mcp"),
            "--help",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert hardlink_result.returncode == 5, hardlink_result
    assert "canonical coordination MCP runtime is incomplete" in hardlink_result.stderr
    assert "external core imported" not in hardlink_result.stderr

    import_alias_bundle = temporary / "bundle-import-alias"
    external_import_root = temporary / "external-lib"
    (import_alias_bundle / "bin").mkdir(parents=True)
    (import_alias_bundle / "sqlite").mkdir()
    external_import_root.mkdir()
    shutil.copytree(ROOT / "coordination", external_import_root / "coordination")
    (import_alias_bundle / "lib").symlink_to(
        external_import_root,
        target_is_directory=True,
    )
    (import_alias_bundle / "bin" / "coordination-mcp").write_bytes(
        (ROOT / "scripts" / "coordination-mcp.py").read_bytes()
    )
    (import_alias_bundle / "sqlite" / "schema.sql").write_bytes(
        (ROOT / "sqlite" / "schema.sql").read_bytes()
    )
    (import_alias_bundle / "VERSION").write_text("1.2.0\n", encoding="utf-8")
    import_alias_result = subprocess.run(
        [
            sys.executable,
            str(import_alias_bundle / "bin" / "coordination-mcp"),
            "--help",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert import_alias_result.returncode == 5, import_alias_result
    assert "canonical coordination MCP runtime is incomplete" in (
        import_alias_result.stderr
    )


class NoQuadraticCountList(list[str]):
    def count(self, value: str) -> int:
        raise AssertionError("quadratic list.count duplicate detection was used")


def test_identifier_array_limits() -> None:
    maximum = [f"actor-{index}" for index in range(MAX_IDENTIFIER_ARRAY_ITEMS)]
    assert _identifiers("assignees", maximum) == maximum
    oversized = [*maximum, "actor-overflow"]
    for operation, field, parameters in (
        (
            "task_create",
            "assignee",
            {
                "id": "TASK-1",
                "title": "Bounded",
                "actor": "owner",
                "assignee": oversized,
            },
        ),
        (
            "task_assign",
            "add",
            {
                "id": "TASK-1",
                "actor": "owner",
                "if_revision": 1,
                "add": oversized,
                "remove": [],
            },
        ),
        (
            "task_assign",
            "remove",
            {
                "id": "TASK-1",
                "actor": "owner",
                "if_revision": 1,
                "add": [],
                "remove": oversized,
            },
        ),
        (
            "artifact_add",
            "task",
            {
                "id": "ART-1",
                "uri": "artifact://one",
                "owner": "owner",
                "type": "test",
                "task": oversized,
                "reviewer": [],
            },
        ),
        (
            "artifact_add",
            "reviewer",
            {
                "id": "ART-1",
                "uri": "artifact://one",
                "owner": "owner",
                "type": "test",
                "task": [],
                "reviewer": oversized,
            },
        ),
    ):
        try:
            CoordinationService(db="/does/not/exist").invoke(operation, parameters)
        except CoordinationError as error:
            assert error.code == "invalid_arguments", error.code
            assert error.details == {
                "field": field,
                "maximum": MAX_IDENTIFIER_ARRAY_ITEMS,
                "actual": MAX_IDENTIFIER_ARRAY_ITEMS + 1,
            }, error.details
        else:
            raise AssertionError(f"{operation} accepted an oversized array")

    require_unique(
        NoQuadraticCountList(["beta", "alpha", "gamma"]),
        "--assignee",
    )
    try:
        require_unique(
            NoQuadraticCountList(["beta", "alpha", "beta", "alpha"]),
            "--assignee",
        )
    except CoordinationError as error:
        assert error.details == {
            "option": "--assignee",
            "duplicates": ["alpha", "beta"],
        }
    else:
        raise AssertionError("duplicate identifiers were accepted")


def test_stdout_writing_operations_are_not_exposed() -> None:
    """No MCP tool may reach an operation that writes to stdout.

    The server owns stdout for JSON-RPC framing. `export` without an output
    path prints Markdown there, so exposing it would corrupt the stream for
    every client on the connection.
    """
    source = "".join(
        p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "coordination" / "transports").glob("*.py"))
    )
    exposed = set(re.findall(r'_tool_result\(\s*\n?\s*db,\s*\n?\s*"(\w+)"', source))
    assert len(exposed) > 20, (
        f"only {len(exposed)} MCP operations were found; the pattern needs updating"
    )
    forbidden = {"export"}
    leaked = exposed & forbidden
    assert not leaked, f"stdout-writing operations exposed over stdio MCP: {leaked}"
    assert "export" in SERVICE_OPERATIONS, (
        "export left the service layer; this guard needs revisiting"
    )


def test_transport_path_containment(temporary: Path) -> None:
    """The transport policy keeps agent-supplied file paths inside the root.

    The CLI may back up to, or restore from, wherever its operator points it.
    A service constructed with ``contain_paths=True`` -- which is how every
    MCP tool constructs it -- must refuse any path that resolves outside the
    coordination root, before touching the filesystem. Without this,
    ``coordination_backup(output="~/.zshrc", force=True)`` is a destructive
    arbitrary file write reachable by prompt injection.
    """
    project = temporary / "contained-project"
    root = project / ".coordination"
    root.mkdir(parents=True)
    database = root / "coordination.sqlite3"
    cli = CoordinationService(db=str(database))
    cli.invoke("init", {})
    cli.invoke("agent_add", {"id": "operator", "name": "Operator", "role": "ops"})

    transport = CoordinationService(db=str(database), contain_paths=True)
    outside = temporary / "outside.sqlite3"
    escape = root / "backups" / ".." / ".." / "escaped.sqlite3"
    for output in (outside, escape, Path("~/contained-probe.sqlite3")):
        try:
            transport.invoke("backup", {"output": str(output), "force": True})
        except CoordinationError as error:
            assert error.code == "path_outside_coordination_root", error.code
            assert error.details["root"] == str(root.resolve()), error.details
        else:
            raise AssertionError(f"transport wrote outside the root: {output}")
        assert not outside.exists()

    inside = root / "backups" / "inside.sqlite3"
    result = transport.invoke("backup", {"output": str(inside)})
    assert isinstance(result, dict) and result["verified"] is True, result
    assert inside.is_file()

    # The CLI policy is unchanged: an operator may still back up anywhere.
    external = cli.invoke("backup", {"output": str(outside)})
    assert isinstance(external, dict) and external["verified"] is True
    assert outside.is_file()

    # Restore input is contained the same way, before any database is opened.
    try:
        transport.invoke(
            "restore",
            {"input": str(outside), "actor": "operator", "force": True},
        )
    except CoordinationError as error:
        assert error.code == "path_outside_coordination_root", error.code
    else:
        raise AssertionError("transport restored from outside the root")
    restored = transport.invoke(
        "restore",
        {"input": str(inside), "actor": "operator", "force": True},
    )
    assert isinstance(restored, dict) and restored["verified"] is True, restored


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="coordination-mcp-security-") as name:
        temporary = Path(name)
        test_generic_bootstrap_paths(temporary)
        test_installed_runtime_alias(temporary)
        test_identifier_array_limits()
        test_stdout_writing_operations_are_not_exposed()
        test_transport_path_containment(temporary)
    print("MCP security regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
