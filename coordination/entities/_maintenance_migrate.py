"""The locked migration engine: staged upgrade, atomic publish, verified rollback.

Migration reuses the restore engine's discipline: an automatic verified
version-1 backup, a staged copy carrying the canonical version-2 objects,
atomic publication under the exclusive database lock, post-publication
verification, and rollback to the backup when verification fails.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import tempfile
from typing import NoReturn

from coordination.core import (
    SCHEMA_VERSION,
    check_coordination_invariants,
    check_database_integrity,
    ensure_supported_schema,
    fsync_directory,
    fsync_file,
    require_row,
)
from coordination.entities import _maintenance_migrate_prepare as migrate_prepare
from coordination.entities._maintenance_backup import _raw_connection
from coordination.errors import EXIT_ENVIRONMENT, fail


def _verify_published_migration(target_path: Path, audit_id: int) -> None:
    """Verify the published database and its migration audit record."""
    verification = _raw_connection(target_path)
    try:
        ensure_supported_schema(verification)
        check_database_integrity(verification)
        check_coordination_invariants(verification)
        require_row(
            verification,
            """SELECT id FROM audit_log
               WHERE id = ? AND action = 'migrate'
                 AND object_type = 'database' AND object_id = ?""",
            (audit_id, str(target_path)),
            "published migration audit record",
        )
    finally:
        verification.close()
    fsync_file(target_path)
    fsync_directory(target_path.parent)


def _rollback_published_migration(target_path: Path, backup_path: str) -> bool:
    """Republish the pre-migration backup; True when the result verifies."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.rollback.",
        suffix=".tmp",
        dir=target_path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(backup_path, temporary)
        os.chmod(temporary, 0o600)
        fsync_file(temporary)
        # The failed publication's sidecars must not survive beside the
        # rolled-back file, so they are cleared before it is renamed in.
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{target_path}{suffix}").unlink(missing_ok=True)
        os.replace(temporary, target_path)
    finally:
        temporary.unlink(missing_ok=True)
    fsync_directory(target_path.parent)
    verification = _raw_connection(target_path)
    try:
        version = int(verification.execute("PRAGMA user_version").fetchone()[0])
        checks = check_database_integrity(verification)
    finally:
        verification.close()
    return version == 1 and checks == {
        "integrity_check": "ok",
        "foreign_key_check": "ok",
    }


def _fail_published_migration(
    error: BaseException,
    target_path: Path,
    backup_path: str,
) -> NoReturn:
    """Roll back a published migration and report both outcomes to the caller."""
    rollback_succeeded = False
    rollback_verified = False
    rollback_error: BaseException | None = None
    try:
        rollback_verified = _rollback_published_migration(target_path, backup_path)
        rollback_succeeded = True
    # A failed rollback is reported to the caller, never raised over the
    # verification failure that triggered it.
    except BaseException as caught_rollback_error:  # noqa: BLE001
        rollback_error = caught_rollback_error
    fail(
        "migration_verification_failed",
        "Published migration failed verification; rollback outcome is reported",
        EXIT_ENVIRONMENT,
        {
            "database": str(target_path),
            "backup": backup_path,
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


def _migrate_while_locked(
    args: argparse.Namespace,
    target_path: Path,
) -> dict[str, object]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    source = _raw_connection(target_path)
    staged: Path | None
    try:
        migrate_prepare._require_migratable_source(source, target_path, args.actor)
        backup_path = migrate_prepare._verified_v1_backup(source, target_path, stamp)
        staged, audit_id = migrate_prepare._staged_migrated_copy(
            source,
            target_path,
            stamp,
            args.actor,
            backup_path,
        )
    finally:
        source.close()
    published = False
    try:
        try:
            os.replace(staged, target_path)
        except OSError as error:
            fail(
                "migration_publication_failed",
                "Migrated database could not be published",
                EXIT_ENVIRONMENT,
                {
                    "database": str(target_path),
                    "backup": backup_path,
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
        _verify_published_migration(target_path, audit_id)
    except BaseException as error:
        # A signal can run after the atomic rename returns but before the
        # following Python assignment; the staged name being gone is
        # definitive evidence that publication completed.
        if not published and staged is not None and not staged.exists():
            published = True
            staged = None
        if published:
            _fail_published_migration(error, target_path, backup_path)
        raise
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm", "-journal"):
                Path(f"{staged}{suffix}").unlink(missing_ok=True)
    return {
        "database": str(target_path),
        "from_schema": 1,
        "to_schema": SCHEMA_VERSION,
        "backup": backup_path,
        "verified": True,
        "publication": "atomic_replace",
        "audit_recorded": True,
    }
