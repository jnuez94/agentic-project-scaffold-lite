#!/usr/bin/env python3
"""Focused contract tests for the optional MCP dependency range."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "scripts" / "check-mcp-dependency.py"
SPEC = importlib.util.spec_from_file_location("check_mcp_dependency", HELPER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

assert MODULE.MCP_REQUIREMENT == "mcp>=1.28.1,<2"
for version in (
    "1.28.1",
    "1.28.1.post1",
    "1.28.1+vendor.1",
    "1.29",
    "1.99.0",
):
    assert MODULE.is_supported_mcp_version(version), version

for version in (
    "0.1.0",
    "1.28.0",
    "1.28.1rc1",
    "1.29.0.dev1",
    "2.0.0",
    "invalid",
    "",
):
    assert not MODULE.is_supported_mcp_version(version), version

pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
assert f'"{MODULE.MCP_REQUIREMENT}"' in pyproject
print("MCP dependency version contract tests passed")
