#!/usr/bin/env python3
"""Deterministically exercise restore rollback after atomic publication."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

import coordination
from coordination.entities import maintenance
from coordination.errors import CoordinationError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--expected-package", required=True)
    args = parser.parse_args()

    package = Path(coordination.__file__).resolve().parent
    if package != Path(args.expected_package).resolve():
        raise AssertionError(f"unexpected coordination package: {package}")

    target = Path(args.target).resolve()
    original_fsync_file = maintenance.fsync_file
    injected = False

    def injected_fsync_file(path: Path) -> None:
        nonlocal injected
        if Path(path).resolve() == target and not injected:
            injected = True
            raise OSError("injected post-publication fsync failure")
        original_fsync_file(path)

    maintenance.fsync_file = injected_fsync_file
    namespace = argparse.Namespace(
        db=str(target),
        input=args.source,
        actor=args.actor,
        session=None,
        force=True,
    )
    try:
        maintenance.restore(namespace)
    except CoordinationError as error:
        if error.code != "restore_verification_failed":
            raise
        details = error.details or {}
        assert details["database"] == str(target)
        assert details["rollback_performed"] is True
        assert details["rollback_succeeded"] is True
        assert details["rollback_verified"] is True
        safety_backup = Path(str(details["safety_backup"]))
        assert safety_backup.is_file()
        with sqlite3.connect(target) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM agents WHERE id = 'target-only'"
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE action = 'restore'"
                ).fetchone()[0]
                == 0
            )
        print(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "error_code": error.code,
                        "rollback_performed": True,
                        "rollback_succeeded": True,
                        "rollback_verified": True,
                    },
                }
            )
        )
        return 0
    raise AssertionError("restore unexpectedly succeeded")


if __name__ == "__main__":
    raise SystemExit(main())
