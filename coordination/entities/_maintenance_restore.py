"""The locked restore engine: publication, verification, rollback orchestration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import NoReturn

from coordination.core import SCHEMA_VERSION, fsync_directory
from coordination.entities import _maintenance_restore_support as restore_support
from coordination.entities._maintenance_restore_phases import (
    _preserved_target_state,
    _staged_restore_from_source,
    _verified_published_restore,
)
from coordination.errors import EXIT_ENVIRONMENT, fail


def _fail_published_verification(
    error: BaseException,
    target_path: Path,
    target_existed: bool,
    safety_backup: str | None,
    safety_backup_verified: bool | None,
) -> NoReturn:
    """Roll back a published restore and report both outcomes to the caller."""
    rollback_succeeded = False
    rollback_verified = False
    rollback_error: BaseException | None = None
    try:
        rollback_verified = restore_support._rollback_published_restore(
            target_path,
            target_existed=target_existed,
            safety_backup=safety_backup,
            safety_backup_verified=safety_backup_verified,
        )
        rollback_succeeded = True
    # A failed rollback is reported to the caller, never raised over the
    # verification failure that triggered it.
    except BaseException as caught_rollback_error:  # noqa: BLE001
        rollback_error = caught_rollback_error
    fail(
        "restore_verification_failed",
        "Published restore failed verification; rollback outcome is reported",
        EXIT_ENVIRONMENT,
        {
            "database": str(target_path),
            "safety_backup": safety_backup,
            "rollback_performed": True,
            "rollback_succeeded": rollback_succeeded,
            "rollback_verified": rollback_verified,
            "reason": (
                type(error).__name__
                if rollback_error is None
                else (
                    f"{type(error).__name__}; rollback {type(rollback_error).__name__}"
                )
            ),
        },
    )


def _restore_while_locked(
    args: argparse.Namespace,
    target_path: Path,
    source_path: Path,
) -> dict[str, object]:
    staged: Path | None
    staged, audit_id, checks, invariant_checks = _staged_restore_from_source(
        args,
        target_path,
        source_path,
    )
    target_existed = target_path.is_file()
    safety_backup: str | None = None
    safety_backup_verified: bool | None = None
    published = False
    rollback_performed = False
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        safety_backup, safety_backup_verified = _preserved_target_state(
            target_path,
            target_existed,
            stamp,
        )
        try:
            os.replace(staged, target_path)
        except OSError as error:
            fail(
                "restore_publication_failed",
                "Restore database could not be published",
                EXIT_ENVIRONMENT,
                {
                    "database": str(target_path),
                    "safety_backup": safety_backup,
                    "target_unchanged": True,
                    "reason": str(error),
                },
            )
        published = True
        staged = None
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{target_path}{suffix}").unlink(missing_ok=True)
        os.chmod(target_path, 0o600)
        fsync_directory(target_path.parent)
        final_checks, final_invariants = _verified_published_restore(
            target_path,
            audit_id,
        )
    except BaseException as error:
        # A signal can run after the atomic rename returns but before the
        # following Python assignment. The staged name is then gone, which is
        # definitive evidence that publication completed and must be rolled
        # back rather than reported as a prepublication interruption.
        if not published and staged is not None and not staged.exists():
            published = True
            staged = None
        if published:
            rollback_performed = True
            _fail_published_verification(
                error,
                target_path,
                target_existed,
                safety_backup,
                safety_backup_verified,
            )
        raise
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm", "-journal"):
                Path(f"{staged}{suffix}").unlink(missing_ok=True)

    return {
        "database": str(target_path),
        "restored_from": str(source_path),
        "safety_backup": safety_backup,
        "safety_backup_verified": safety_backup_verified,
        "schema_version": SCHEMA_VERSION,
        "verified": (
            checks == {"integrity_check": "ok", "foreign_key_check": "ok"}
            and invariant_checks == {"coordination_invariants": "ok"}
            and final_checks == {"integrity_check": "ok", "foreign_key_check": "ok"}
            and final_invariants == {"coordination_invariants": "ok"}
        ),
        "publication": "atomic_replace",
        "audit_recorded": True,
        "rollback_performed": rollback_performed,
    }
