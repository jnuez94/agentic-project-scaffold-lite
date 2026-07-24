#!/usr/bin/env python3
"""Executable entry point for the canonical coordination package."""

from __future__ import annotations

import os
import sys

# Apply Python's isolated-mode path rules even when callers explicitly invoke
# ``python3 coordination`` instead of using the shebang. This removes
# PYTHONPATH, the current directory, and user site-packages before any runtime
# dependencies are imported.
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
    """Emit the public installation failure shape without importing the package."""
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


if sys.version_info < (3, 10):
    installation_error("The coordination CLI requires Python 3.10 or newer")

# Do not leave interpreter caches in the canonical source tree or managed
# installed bundle. More importantly, resolve exactly one permitted package
# root instead of falling through to PYTHONPATH or a globally installed module.
sys.dont_write_bytecode = True
launcher = Path(__file__).resolve()
launcher_directory = launcher.parent

if launcher.name == "coordination.py" and launcher_directory.name == "scripts":
    runtime_root = launcher_directory.parent
    import_root = runtime_root
elif launcher.name == "coordination" and launcher_directory.name == "bin":
    runtime_root = launcher_directory.parent
    import_root = runtime_root / "lib"
else:
    installation_error(
        "The coordination launcher is not in the canonical source or installed layout"
    )

package_directory = import_root / "coordination"
required_runtime_files = (
    package_directory / "__init__.py",
    package_directory / "cli.py",
    runtime_root / "sqlite" / "schema.sql",
    runtime_root / "VERSION",
)
if package_directory.is_symlink() or any(
    path.is_symlink() or not path.is_file() for path in required_runtime_files
):
    installation_error("The canonical coordination runtime is incomplete")

resolved_import_root = import_root.resolve()
resolved_package = package_directory.resolve()
try:
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

    import coordination  # noqa: E402

    package_paths = [Path(value).resolve() for value in coordination.__path__]
    if package_paths != [resolved_package]:
        raise ImportError("unexpected package path")

    from coordination import cli as coordination_cli  # noqa: E402

    if Path(coordination_cli.__file__).resolve() != (
        package_directory / "cli.py"
    ).resolve():
        raise ImportError("unexpected CLI origin")
except BaseException:
    installation_error("The canonical coordination runtime cannot be imported")


if __name__ == "__main__":
    raise SystemExit(coordination_cli.main())
