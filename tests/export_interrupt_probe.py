#!/usr/bin/env python3
"""Run export with a deterministic pre-publication interruption window."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import coordination
from coordination import cli
from coordination.entities import reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-package", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--marker", required=True)
    args = parser.parse_args()

    package = Path(coordination.__file__).resolve().parent
    if package != Path(args.tool_package).resolve():
        raise AssertionError(f"unexpected coordination package: {package}")

    original_publish = reports.publish_temporary_file

    def delayed_publish(*publish_args: object, **publish_kwargs: object) -> None:
        Path(args.marker).touch()
        time.sleep(10)
        original_publish(*publish_args, **publish_kwargs)

    reports.publish_temporary_file = delayed_publish
    sys.argv = [
        "coordination",
        "--db",
        args.database,
        "export",
        "--output",
        args.output,
    ]
    return cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
