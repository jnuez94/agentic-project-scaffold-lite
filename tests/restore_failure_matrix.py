#!/usr/bin/env python3
"""Inject restore publication and rollback failures deterministically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

import coordination
from coordination.entities import maintenance
from coordination.errors import EXIT_ENVIRONMENT, CoordinationError


def state(path: Path) -> tuple[list[tuple[object, ...]], int]:
    with sqlite3.connect(path) as connection:
        agents = connection.execute(
            "SELECT id, name, role FROM agents ORDER BY id"
        ).fetchall()
        restore_audits = int(
            connection.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'restore'"
            ).fetchone()[0]
        )
    return agents, restore_audits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("publication", "postrename", "rollback"),
        required=True,
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--expected-package", required=True)
    args = parser.parse_args()

    package = Path(coordination.__file__).resolve().parent
    if package != Path(args.expected_package).resolve():
        raise AssertionError(f"unexpected coordination package: {package}")

    target = Path(args.target).resolve()
    before = state(target)

    if args.mode == "publication":
        original_replace = maintenance.os.replace

        def failed_replace(source: object, destination: object) -> None:
            source_path = Path(source)
            destination_path = Path(destination).resolve()
            if (
                destination_path == target
                and ".restore." in source_path.name
            ):
                raise OSError("injected atomic publication failure")
            original_replace(source, destination)

        maintenance.os.replace = failed_replace
        expected_code = "restore_publication_failed"
    elif args.mode == "rollback":
        original_fsync_file = maintenance.fsync_file
        injected = False

        def failed_verification(path: Path) -> None:
            nonlocal injected
            if Path(path).resolve() == target and not injected:
                injected = True
                raise OSError("injected post-publication verification failure")
            original_fsync_file(path)

        def failed_rollback(*_args: object, **_kwargs: object) -> bool:
            raise OSError("injected rollback failure")

        maintenance.fsync_file = failed_verification
        maintenance._rollback_published_restore = failed_rollback
        expected_code = "restore_verification_failed"
    else:
        original_replace = maintenance.os.replace

        def interrupted_replace(source: object, destination: object) -> None:
            source_path = Path(source)
            destination_path = Path(destination).resolve()
            original_replace(source, destination)
            if (
                destination_path == target
                and ".restore." in source_path.name
            ):
                raise CoordinationError(
                    "operation_interrupted",
                    "injected interruption after atomic publication",
                    EXIT_ENVIRONMENT,
                )

        maintenance.os.replace = interrupted_replace
        expected_code = "restore_verification_failed"

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
        if error.code != expected_code:
            raise
        details = error.details or {}
        assert details["database"] == str(target), details
        if args.mode == "publication":
            assert details["target_unchanged"] is True, details
            assert state(target) == before
        elif args.mode == "rollback":
            assert details["rollback_performed"] is True, details
            assert details["rollback_succeeded"] is False, details
            assert details["rollback_verified"] is False, details
            with sqlite3.connect(target) as connection:
                assert connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0] == "ok"
                assert connection.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE action = 'restore'"
                ).fetchone()[0] >= 1
        else:
            assert details["rollback_performed"] is True, details
            assert details["rollback_succeeded"] is True, details
            assert details["rollback_verified"] is True, details
            assert state(target) == before
        print(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "error_code": error.code,
                        "target_unchanged": details.get("target_unchanged"),
                        "rollback_performed": details.get("rollback_performed"),
                        "rollback_succeeded": details.get("rollback_succeeded"),
                        "rollback_verified": details.get("rollback_verified"),
                    },
                }
            )
        )
        return 0
    raise AssertionError("restore unexpectedly succeeded")


if __name__ == "__main__":
    raise SystemExit(main())
