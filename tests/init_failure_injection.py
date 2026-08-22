#!/usr/bin/env python3
"""Inject a mid-script init failure after canonical schema preflight."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import coordination
from coordination import cli, core


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-package", required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()

    package = Path(coordination.__file__).resolve().parent
    if package != Path(args.tool_package).resolve():
        raise AssertionError(f"unexpected coordination package: {package}")

    # Prime the independent canonical compile check, then make only the
    # project-database execution fail after its transaction has started.
    core.expected_schema_definitions()
    schema_sql = core.canonical_schema_sql()
    needle = "\nCOMMIT;"
    if schema_sql.count(needle) != 1:
        raise AssertionError("canonical schema has an unexpected transaction shape")
    injected_sql = schema_sql.replace(
        needle,
        "\nTHIS IS NOT SQL;\nCOMMIT;",
    )
    cli.canonical_schema_sql = lambda: injected_sql
    sys.argv = [
        "coordination",
        "--db",
        args.database,
        "init",
    ]
    return cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
