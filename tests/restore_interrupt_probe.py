#!/usr/bin/env python3
"""Run restore with a deterministic pre-publication interruption window."""

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
    parser.add_argument("--target", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--marker", required=True)
    args = parser.parse_args()

    package = Path(coordination.__file__).resolve().parent
    if package != Path(args.tool_package).resolve():
        raise AssertionError(f"unexpected coordination package: {package}")

    original_prepare = maintenance._prepare_restore

    def delayed_prepare(*prepare_args: object, **prepare_kwargs: object):
        Path(args.marker).touch()
        time.sleep(10)
        return original_prepare(*prepare_args, **prepare_kwargs)

    maintenance._prepare_restore = delayed_prepare
    sys.argv = [
        "coordination",
        "--db",
        args.target,
        "restore",
        "--input",
        args.source,
        "--actor",
        args.actor,
        "--force",
    ]
    return cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
