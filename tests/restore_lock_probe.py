#!/usr/bin/env python3
"""Pause restore preparation so a separate CLI can probe its intent lock."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

import coordination
from coordination.entities import maintenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--expected-package", required=True)
    args = parser.parse_args()

    package = Path(coordination.__file__).resolve().parent
    if package != Path(args.expected_package).resolve():
        raise AssertionError(f"unexpected coordination package: {package}")

    original_prepare = maintenance._prepare_restore

    def delayed_prepare(*prepare_args: object, **prepare_kwargs: object):
        Path(args.marker).touch()
        time.sleep(0.75)
        return original_prepare(*prepare_args, **prepare_kwargs)

    maintenance._prepare_restore = delayed_prepare
    namespace = argparse.Namespace(
        db=args.target,
        input=args.source,
        actor=args.actor,
        session=None,
        force=True,
    )
    maintenance.restore(namespace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
