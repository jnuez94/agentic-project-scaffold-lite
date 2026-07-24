#!/usr/bin/env python3
"""Run the public CLI with a deterministic interruption window for backup."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import coordination
from coordination import cli
from coordination.entities import maintenance


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

    original_write = maintenance._write_verified_copy

    def delayed_write(*write_args: object, **write_kwargs: object):
        Path(args.marker).touch()
        time.sleep(10)
        return original_write(*write_args, **write_kwargs)

    maintenance._write_verified_copy = delayed_write
    sys.argv = [
        "coordination",
        "--db",
        args.database,
        "backup",
        "--output",
        args.output,
    ]
    return cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
