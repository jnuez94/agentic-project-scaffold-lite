"""The locked restore engine: publication, verification, rollback orchestration."""

from __future__ import annotations


# fmt: off
# isort: off
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from coordination.core import (
    SCHEMA_VERSION, check_coordination_invariants, check_database_integrity,
    close_connection, connect_read_only, ensure_supported_schema, fsync_directory,
    require_active_actor, require_active_session,
    validate_database_operational_files
)
from coordination.entities import _maintenance_restore_support as restore_support
from coordination.entities._maintenance_backup import (
    _raw_connection, atomic_backup, preserve_unhealthy_target
)
from coordination.entities._maintenance_restore_support import (
    _active_target_sessions, _safety_backup_path
)
from coordination.errors import (
    EXIT_CONFLICT, EXIT_ENVIRONMENT, EXIT_USAGE, CoordinationError, fail
)
# isort: on
# fmt: on


def _restore_while_locked(
    args: argparse.Namespace,
    target_path: Path,
    source_path: Path,
) -> dict[str, object]:
    validate_database_operational_files(target_path)
    if target_path.is_symlink() or (target_path.exists() and not target_path.is_file()):
        fail(
            "invalid_arguments",
            "Restore target must be absent or a non-symbolic-link regular file",
            EXIT_USAGE,
            {"database": str(target_path), "target_unchanged": True},
        )
    source = connect_read_only(source_path)
    staged: Path | None = None
    try:
        check_database_integrity(source)
        check_coordination_invariants(source)
        require_active_actor(source, args.actor)
        if args.session:
            require_active_session(source, args.session, args.actor)
        staged, audit_id, checks, invariant_checks = restore_support._prepare_restore(
            source,
            target_path,
            source_path,
            args.actor,
            args.session,
        )
    finally:
        close_connection(source)

    target_existed = target_path.is_file()
    safety_backup: str | None = None
    safety_backup_verified: bool | None = None
    published = False
    rollback_performed = False
    target_connection: sqlite3.Connection | None = None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
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

        verification = _raw_connection(target_path)
        try:
            ensure_supported_schema(verification)
            final_checks = check_database_integrity(verification)
            final_invariants = check_coordination_invariants(verification)
            journal_mode = str(
                verification.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if journal_mode != "wal":
                raise sqlite3.OperationalError(
                    f"unexpected journal mode: {journal_mode}"
                )
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
    except BaseException as error:
        if target_connection is not None:
            target_connection.close()
        # A signal can run after the atomic rename returns but before the
        # following Python assignment. The staged name is then gone, which is
        # definitive evidence that publication completed and must be rolled
        # back rather than reported as a prepublication interruption.
        if not published and staged is not None and not staged.exists():
            published = True
            staged = None
        if published:
            rollback_performed = True
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
                            f"{type(error).__name__}; "
                            f"rollback {type(rollback_error).__name__}"
                        )
                    ),
                },
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
