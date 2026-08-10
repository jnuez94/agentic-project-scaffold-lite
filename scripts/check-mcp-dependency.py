#!/usr/bin/env python3
"""Validate the optional MCP SDK against the supported release range."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import re
import sys


MCP_REQUIREMENT = "mcp>=1.28.1,<2"
MINIMUM_RELEASE = (1, 28, 1)
STABLE_VERSION = re.compile(
    r"^(?:v|0!)?"
    r"(?P<release>[0-9]+(?:\.[0-9]+)*)"
    r"(?:(?:[._-]?post|-)?[0-9]+)?"
    r"(?:\+[a-z0-9]+(?:[._-][a-z0-9]+)*)?$",
    re.IGNORECASE,
)


def is_supported_mcp_version(raw_version: str) -> bool:
    """Return whether a distribution version satisfies the public MCP contract."""

    match = STABLE_VERSION.fullmatch(raw_version.strip())
    if match is None:
        return False
    release = tuple(int(part) for part in match.group("release").split("."))
    width = max(len(release), len(MINIMUM_RELEASE))
    normalized = release + (0,) * (width - len(release))
    minimum = MINIMUM_RELEASE + (0,) * (width - len(MINIMUM_RELEASE))
    return normalized[0] == 1 and normalized >= minimum


def main() -> int:
    if importlib.util.find_spec("mcp") is None:
        print(f"Missing optional dependency: {MCP_REQUIREMENT}", file=sys.stderr)
        return 1
    try:
        raw_version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        print(
            f"Missing optional dependency metadata: {MCP_REQUIREMENT}",
            file=sys.stderr,
        )
        return 1
    if not is_supported_mcp_version(raw_version):
        print(
            f"Unsupported mcp version {raw_version!r}; required {MCP_REQUIREMENT}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
