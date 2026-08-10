#!/usr/bin/env python3
"""Strict launcher for the optional canonical stdio MCP transport."""

from __future__ import annotations

import os
import sys


if not sys.flags.isolated:
    os.execv(
        sys.executable,
        [sys.executable, "-I", os.path.abspath(__file__), *sys.argv[1:]],
    )

import importlib.util
import json
from pathlib import Path
from typing import NoReturn


def installation_error(message: str) -> NoReturn:
    print(
        json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "installation_error",
                    "message": message,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(5)


# This launcher must still parse and run on an unsupported interpreter so it can
# report a usable error instead of a syntax or import traceback. The guard is
# therefore live code, not a block made dead by requires-python.
if sys.version_info < (3, 10):  # noqa: UP036
    installation_error("The coordination MCP transport requires Python 3.10 or newer")

sys.dont_write_bytecode = True
launcher = Path(__file__).resolve()
launcher_directory = launcher.parent

if launcher.name == "coordination-mcp.py" and launcher_directory.name == "scripts":
    runtime_root = launcher_directory.parent
    import_root = runtime_root
elif launcher.name == "coordination-mcp" and launcher_directory.name == "bin":
    runtime_root = launcher_directory.parent
    import_root = runtime_root / "lib"
else:
    installation_error(
        "The coordination MCP launcher is not in the canonical source"
        " or installed layout"
    )

package_directory = import_root / "coordination"
required_runtime_files = (
    package_directory / "__init__.py",
    package_directory / "service.py",
    package_directory / "transports" / "__init__.py",
    package_directory / "transports" / "mcp.py",
    runtime_root / "sqlite" / "schema.sql",
    runtime_root / "VERSION",
)


def has_aliased_component(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return True
    current = path
    while True:
        if current.is_symlink():
            return True
        if current == root:
            return False
        current = current.parent


def tree_contains_alias(root: Path) -> bool:
    for directory_name, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        directory = Path(directory_name)
        for name in directory_names:
            path = directory / name
            if path.is_symlink() or not path.is_dir():
                return True
        for name in file_names:
            path = directory / name
            if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                return True
    return False


required_runtime_directories = (
    import_root,
    package_directory,
    package_directory / "transports",
    runtime_root / "sqlite",
)
if (
    any(
        has_aliased_component(runtime_root, path) or not path.is_dir()
        for path in required_runtime_directories
    )
    or any(
        has_aliased_component(runtime_root, path)
        or not path.is_file()
        or path.stat().st_nlink != 1
        for path in required_runtime_files
    )
    or tree_contains_alias(package_directory)
):
    installation_error("The canonical coordination MCP runtime is incomplete")

resolved_runtime_root = runtime_root.resolve(strict=True)
resolved_import_root = import_root.resolve(strict=True)
resolved_package = package_directory.resolve(strict=True)
try:
    resolved_import_root.relative_to(resolved_runtime_root)
    resolved_package.relative_to(resolved_import_root)
except ValueError:
    installation_error("The coordination package resolves outside its runtime root")

sys.path.insert(0, str(resolved_import_root))
expected_origin = (package_directory / "__init__.py").resolve()
try:
    spec = importlib.util.find_spec("coordination")
    if (
        spec is None
        or spec.origin is None
        or Path(spec.origin).resolve() != expected_origin
    ):
        raise ImportError("unexpected package origin")

    import coordination

    package_paths = [Path(value).resolve() for value in coordination.__path__]
    if package_paths != [resolved_package]:
        raise ImportError("unexpected package path")

    if importlib.util.find_spec("mcp") is None:
        installation_error(
            "The optional MCP dependency is not installed; install the 'mcp' extra"
        )

    from coordination.transports import mcp as coordination_mcp

    if (
        Path(coordination_mcp.__file__).resolve()
        != (package_directory / "transports" / "mcp.py").resolve()
    ):
        raise ImportError("unexpected MCP transport origin")
except SystemExit:
    raise
except BaseException:  # noqa: BLE001 - any import failure is an installation error
    installation_error("The canonical coordination MCP runtime cannot be imported")


if __name__ == "__main__":
    raise SystemExit(coordination_mcp.main())
