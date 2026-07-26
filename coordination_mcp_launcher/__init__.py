"""Console-script bootstrap for a project-installed coordination MCP server."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import NoReturn


LAUNCHER_PARTS = (
    ".agents",
    "agentic-project-scaffold-lite",
    "bin",
    "coordination-mcp",
)


def _fail(message: str) -> NoReturn:
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


def _trusted_launcher(directory: Path) -> Path | None:
    candidate = directory
    for part in LAUNCHER_PARTS:
        candidate = candidate / part
        if candidate.is_symlink():
            _fail(
                "The installed coordination MCP launcher path must not contain "
                "symbolic links"
            )
    if not candidate.is_file():
        return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(directory)
    except (OSError, ValueError):
        _fail(
            "The installed coordination MCP launcher resolves outside its project"
        )
    if candidate.stat().st_nlink != 1:
        _fail("The installed coordination MCP launcher must not have hard-link aliases")
    return resolved


def _discover_launcher() -> Path:
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        launcher = _trusted_launcher(directory)
        if launcher is not None:
            return launcher
    _fail(
        "No project-installed coordination MCP launcher was found; "
        "run the installer with --adapter sqlite --with-mcp"
    )


def main() -> int:
    launcher = _discover_launcher()
    os.execv(
        sys.executable,
        [sys.executable, "-I", str(launcher), *sys.argv[1:]],
    )
    return 1
