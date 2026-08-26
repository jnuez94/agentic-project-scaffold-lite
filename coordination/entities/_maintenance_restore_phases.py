"""Pre-publication and verification phases of the locked restore engine.

These phases call the probed helpers through the `restore_support` module
reference so the restore qualification probes observe every call site.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from coordination.core import (
    check_coordination_invariants,
    check_database_integrity,
    close_connection,
    connect_read_only,
    ensure_supported_schema,
    fsync_directory,
    require_active_actor,
    require_active_session,
    validate_database_operational_files,
)
from coordination.entities import _maintenance_restore_support as restore_support
from coordination.entities._maintenance_backup import (
    _raw_connection,
    atomic_backup,
    preserve_unhealthy_target,
)
from coordination.entities._maintenance_restore_support import (
    _active_target_sessions,
    _safety_backup_path,
)
from coordination.errors import EXIT_CONFLICT, EXIT_USAGE, CoordinationError, fail


def _staged_restore_from_source(
    args: argparse.Namespace,
    target_path: Path,
    source_path: Path,
) -> tuple[Path, int, dict[str, str], dict[str, str]]:
    """Validate the target name, verify the source, and stage the restore."""
    validate_database_operational_files(target_path)
    if target_path.is_symlink() or (target_path.exists() and not target_path.is_file()):
        fail(
            "invalid_arguments",
            "Restore target must be absent or a non-symbolic-link regular file",
            EXIT_USAGE,
            {"database": str(target_path), "target_unchanged": True},
        )
    source = connect_read_only(source_path)
    try:
        check_database_integrity(source)
        check_coordination_invariants(source)
        require_active_actor(source, args.actor)
        if args.session:
            require_active_session(source, args.session, args.actor)
        return restore_support._prepare_restore(
            source,
            target_path,
            source_path,
            args.actor,
            args.session,
        )
    finally:
        close_connection(source)


def _preserved_target_state(
    target_path: Path,
    target_existed: bool,
    stamp: str,
) -> tuple[str | None, bool | None]:
    """Health-check an existing target and take the pre-restore safety backup."""
    safety_backup: str | None = None
    safety_backup_verified: bool | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        target_healthy = False
        if target_existed:
            try:
                target_connection = _raw_connection(target_path)
                active_sessions = _active_target_sessions(target_connection)
                if active_sessions:
                    fail(
                        "restore_active_sessions",
                        "End or recover every active session before restoring",
                        EXIT_CONFLICT,
                        {"sessions": active_sessions},
                    )
                ensure_supported_schema(target_connection)
                check_database_integrity(target_connection)
                check_coordination_invariants(target_connection)
                target_healthy = True
            except CoordinationError as error:
                if error.code in (
                    "restore_active_sessions",
                    "operation_interrupted",
                ):
                    raise
            except sqlite3.DatabaseError:
                pass
        if target_healthy and target_connection is not None:
            safety_path = _safety_backup_path(
                target_path,
                f"pre-restore-{stamp}.sqlite3",
            )
            safety_backup = str(
                atomic_backup(
                    target_connection,
                    safety_path,
                    force=False,
                )["backup"]
            )
            safety_backup_verified = True
        elif target_existed:
            if target_connection is not None:
                target_connection.close()
                target_connection = None
            safety_path = _safety_backup_path(
                target_path,
                f"pre-restore-unverified-{stamp}.sqlite3",
            )
            safety_backup = preserve_unhealthy_target(
                target_path,
                safety_path,
            )
            safety_backup_verified = False
        if target_connection is not None:
            target_connection.close()
            target_connection = None
    except BaseException:
        if target_connection is not None:
            target_connection.close()
        raise
    return safety_backup, safety_backup_verified


def _verified_published_restore(
    target_path: Path,
    audit_id: int,
) -> tuple[dict[str, str], dict[str, str]]:
    """Verify the published database, its journal mode, and its audit record."""
    verification = _raw_connection(target_path)
    try:
        ensure_supported_schema(verification)
        final_checks = check_database_integrity(verification)
        final_invariants = check_coordination_invariants(verification)
        journal_mode = str(
            verification.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        ).lower()
        if journal_mode != "wal":
            raise sqlite3.OperationalError(f"unexpected journal mode: {journal_mode}")
        audit_count = int(
            verification.execute(
                """SELECT COUNT(*) FROM audit_log
                   WHERE id = ? AND action = 'restore'
                     AND object_type = 'database' AND object_id = ?""",
                (audit_id, str(target_path)),
            ).fetchone()[0]
        )
        if audit_count != 1:
            raise sqlite3.IntegrityError("published restore audit is missing")
    finally:
        verification.close()
    restore_support.fsync_file(target_path)
    fsync_directory(target_path.parent)
    return final_checks, final_invariants
