#!/usr/bin/env python3
"""Security regression coverage for MCP launchers and aggregate inputs."""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Iterator


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coordination.core import MAX_IDENTIFIER_ARRAY_ITEMS, require_unique
from coordination.errors import CoordinationError
from coordination.service import CoordinationService, _identifiers
from coordination_mcp_launcher import _discover_launcher


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
            "from coordination import service\n"
            "def main():\n"
            "    return 0\n",
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
        "def main():\n"
        "    return 0\n",
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
    oversized = maximum + ["actor-overflow"]
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="coordination-mcp-security-") as name:
        temporary = Path(name)
        test_generic_bootstrap_paths(temporary)
        test_installed_runtime_alias(temporary)
        test_identifier_array_limits()
    print("MCP security regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
