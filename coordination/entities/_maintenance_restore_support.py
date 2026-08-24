"""Restore internals: staging, safety backups, and rollback.

This module is the single patch point the restore qualification probes
patch; the restore engine resolves these helpers through it at call time.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from coordination.core import (
    audit,
    check_coordination_invariants,
    check_database_integrity,
    coordination_root_for_database,
    ensure_supported_schema,
    fsync_directory,
    transaction,
)
from coordination.core import (
    fsync_file as fsync_file,
)
from coordination.entities._maintenance_backup import (
    _atomic_raw_copy,
    _raw_connection,
    _write_verified_copy,
)
from coordination.errors import (
    EXIT_ENVIRONMENT,
    CoordinationError,
    fail,
)


def _restore_safety_directory(target: Path) -> Path:
    coordination_root = coordination_root_for_database(target)
    return coordination_root / "backups"


def _safety_backup_path(target: Path, filename: str) -> Path:
    coordination_root = coordination_root_for_database(target)
    directory = _restore_safety_directory(target)
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        fail(
            "environment_error",
            "Restore safety-backup destination must be a real directory",
            EXIT_ENVIRONMENT,
            {
                "database": str(target),
                "safety_backup_directory": str(directory),
                "target_unchanged": True,
            },
        )
    directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    if directory.resolve().parent != coordination_root.resolve():
        fail(
            "environment_error",
            "Restore safety-backup destination escaped the coordination directory",
            EXIT_ENVIRONMENT,
            {
                "database": str(target),
                "safety_backup_directory": str(directory),
                "target_unchanged": True,
            },
        )
    return directory / filename


def _prepare_restore(
    source: sqlite3.Connection,
    target_path: Path,
    source_path: Path,
    actor: str,
    session_id: str | None,
) -> tuple[Path, int, dict[str, str], dict[str, str]]:
    descriptor, staged_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.restore.",
        suffix=".sqlite3",
        dir=target_path.parent,
    )
    os.close(descriptor)
    staged = Path(staged_name)
    try:
        _write_verified_copy(source, staged)
        staged_connection = _raw_connection(staged)
        try:
            try:
                with transaction(staged_connection):
                    audit_id = audit(
                        staged_connection,
                        actor,
                        "restore",
                        "database",
                        str(target_path),
                        f"restored from {source_path}",
                        session_id=session_id,
                    )
                ensure_supported_schema(staged_connection)
                checks = check_database_integrity(staged_connection)
                invariant_checks = check_coordination_invariants(staged_connection)
                audit_row = staged_connection.execute(
                    """SELECT action, object_type, object_id
                       FROM audit_log WHERE id = ?""",
                    (audit_id,),
                ).fetchone()
                if (
                    audit_row is None
                    or audit_row["action"] != "restore"
                    or audit_row["object_type"] != "database"
                    or audit_row["object_id"] != str(target_path)
                ):
                    raise sqlite3.IntegrityError(
                        "staged restore audit did not match its intent"
                    )
                staged_connection.execute("PRAGMA journal_mode = DELETE")
            except CoordinationError as error:
                if error.code == "operation_interrupted":
                    raise
                fail(
                    "restore_audit_failed",
                    "Restore audit could not be verified before publication",
                    EXIT_ENVIRONMENT,
                    {
                        "database": str(target_path),
                        "restored_from": str(source_path),
                        "target_unchanged": True,
                        "reason": error.code,
                    },
                )
            except sqlite3.DatabaseError as error:
                fail(
                    "restore_audit_failed",
                    "Restore audit could not be verified before publication",
                    EXIT_ENVIRONMENT,
                    {
                        "database": str(target_path),
                        "restored_from": str(source_path),
                        "target_unchanged": True,
                        "reason": type(error).__name__,
                    },
                )
        finally:
            staged_connection.close()
        os.chmod(staged, 0o600)
        fsync_file(staged)
        return staged, audit_id, checks, invariant_checks
    except BaseException:
        staged.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{staged}{suffix}").unlink(missing_ok=True)
        raise


def _active_target_sessions(connection: sqlite3.Connection) -> list[str]:
    try:
        return [
            str(row[0])
            for row in connection.execute(
                """SELECT id FROM agent_sessions
                   WHERE status = 'active'
                   ORDER BY id"""
            )
        ]
    except sqlite3.DatabaseError:
        return []


def _rollback_published_restore(
    target: Path,
    *,
    target_existed: bool,
    safety_backup: str | None,
    safety_backup_verified: bool | None,
) -> bool:
    for suffix in ("-wal", "-shm", "-journal"):
        Path(f"{target}{suffix}").unlink(missing_ok=True)
    if not target_existed:
        target.unlink(missing_ok=True)
        fsync_directory(target.parent)
        return True
    if safety_backup is None:
        return False
    safety = Path(safety_backup)
    descriptor, rollback_name = tempfile.mkstemp(
        prefix=f".{target.name}.rollback.",
        suffix=".sqlite3",
        dir=target.parent,
    )
    os.close(descriptor)
    rollback = Path(rollback_name)
    try:
        shutil.copy2(safety, rollback)
        os.chmod(rollback, 0o600)
        fsync_file(rollback)
        os.replace(rollback, target)
        for suffix in ("-wal", "-shm", "-journal"):
            safety_sidecar = Path(f"{safety}{suffix}")
            if safety_sidecar.is_file():
                _atomic_raw_copy(safety_sidecar, Path(f"{target}{suffix}"))
        fsync_directory(target.parent)
    finally:
        rollback.unlink(missing_ok=True)
    if not safety_backup_verified:
        return False
    verification = _raw_connection(target)
    try:
        ensure_supported_schema(verification)
        check_database_integrity(verification)
        check_coordination_invariants(verification)
        journal_mode = str(
            verification.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        ).lower()
        if journal_mode != "wal":
            return False
    finally:
        verification.close()
    fsync_file(target)
    fsync_directory(target.parent)
    return True
