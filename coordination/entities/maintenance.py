"""Verified, failure-atomic backup and restore operations."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from coordination.core import (
    SCHEMA_VERSION,
    advisory_file_lock,
    audit,
    check_coordination_invariants,
    check_database_integrity,
    close_connection,
    configured_busy_timeout_ms,
    connect,
    connect_read_only,
    coordination_root_for_database,
    database_lock_path,
    discover_db,
    emit,
    ensure_supported_schema,
    fsync_directory,
    fsync_file,
    identifier,
    operational_path,
    output_lock_path,
    path_argument,
    paths_refer_to_same_file,
    publish_temporary_file,
    require_active_actor,
    require_active_session,
    transaction,
    validate_external_path,
    validate_enclosing_configured_database_namespace,
    validate_database_namespaces_disjoint,
    validate_database_operational_files,
    validate_not_managed_metadata,
    validate_output_path,
    validate_restore_target_path,
)
from coordination.errors import (
    EXIT_CONFLICT,
    EXIT_ENVIRONMENT,
    EXIT_USAGE,
    CoordinationError,
    fail,
)


def _raw_connection(path: Path) -> sqlite3.Connection:
    timeout_ms = configured_busy_timeout_ms()
    connection = sqlite3.connect(path, timeout=timeout_ms / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def _write_verified_copy(
    source: sqlite3.Connection,
    destination: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    destination_connection: sqlite3.Connection | None = None
    try:
        destination_connection = _raw_connection(destination)
        source.backup(destination_connection)
        ensure_supported_schema(destination_connection)
        checks = check_database_integrity(destination_connection)
        invariant_checks = check_coordination_invariants(destination_connection)
        destination_connection.close()
        destination_connection = None
        os.chmod(destination, 0o600)
        fsync_file(destination)
        return checks, invariant_checks
    finally:
        if destination_connection is not None:
            destination_connection.close()
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{destination}{suffix}").unlink(missing_ok=True)


def atomic_backup(
    source: sqlite3.Connection,
    destination: Path,
    *,
    force: bool,
) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    prefix = f".{destination.name}."
    suffix = ".tmp"
    with advisory_file_lock(output_lock_path(destination), exclusive=True):
        if not force and destination.exists():
            fail(
                "output_exists",
                f"Output already exists: {destination}. Pass --force to replace it.",
                EXIT_CONFLICT,
                {"output": str(destination)},
            )
        with advisory_file_lock(database_lock_path(destination), exclusive=True):
            validate_database_operational_files(destination)
            existing_sidecars = [
                str(sidecar)
                for sidecar in (
                    Path(f"{destination}{sidecar_suffix}")
                    for sidecar_suffix in ("-wal", "-shm", "-journal")
                )
                if sidecar.exists() or sidecar.is_symlink()
            ]
            if existing_sidecars:
                fail(
                    "invalid_arguments",
                    "Backup output has existing SQLite sidecars",
                    EXIT_USAGE,
                    {
                        "output": str(destination),
                        "sidecars": existing_sidecars,
                    },
                )
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=prefix,
                suffix=suffix,
                dir=destination.parent,
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                checks, invariant_checks = _write_verified_copy(source, temporary)
                publish_temporary_file(
                    temporary,
                    destination,
                    force=force,
                )
            finally:
                temporary.unlink(missing_ok=True)
                for temporary_suffix in ("-wal", "-shm", "-journal"):
                    Path(f"{temporary}{temporary_suffix}").unlink(missing_ok=True)
    return {
        "backup": str(destination),
        "bytes": destination.stat().st_size,
        "schema_version": SCHEMA_VERSION,
        "verified": (
            checks == {"integrity_check": "ok", "foreign_key_check": "ok"}
            and invariant_checks == {"coordination_invariants": "ok"}
        ),
    }


def backup(args: argparse.Namespace) -> None:
    source_path = discover_db(args.db)
    destination = operational_path(
        args.output,
        label="Backup output",
        must_exist=False,
    )
    validate_output_path(
        destination,
        source_path,
        label="Backup output",
        database_namespace=True,
    )
    validate_database_namespaces_disjoint(
        source_path,
        destination,
        label="Backup source and output",
    )
    source = connect(source_path)
    try:
        # Opening the source may materialize WAL, shared-memory, and advisory
        # lock files. Recheck aliases against that complete operational set.
        validate_output_path(
            destination,
            source_path,
            label="Backup output",
            database_namespace=True,
        )
        validate_database_namespaces_disjoint(
            source_path,
            destination,
            label="Backup source and output",
        )
        result = atomic_backup(source, destination, force=args.force)
    finally:
        close_connection(source)
    result["source"] = str(source_path)
    emit(result)


def _atomic_raw_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.chmod(temporary, 0o600)
        publish_temporary_file(temporary, destination, force=False)
    finally:
        temporary.unlink(missing_ok=True)


def preserve_unhealthy_target(target: Path, destination: Path) -> str:
    _atomic_raw_copy(target, destination)
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{target}{suffix}")
        if sidecar.is_file():
            _atomic_raw_copy(sidecar, Path(f"{destination}{suffix}"))
    fsync_directory(destination.parent)
    return str(destination)


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


def _restore_while_locked(
    args: argparse.Namespace,
    target_path: Path,
    source_path: Path,
) -> None:
    validate_database_operational_files(target_path)
    if target_path.is_symlink() or (
        target_path.exists() and not target_path.is_file()
    ):
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
        staged, audit_id, checks, invariant_checks = _prepare_restore(
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
                raise sqlite3.IntegrityError(
                    "published restore audit is missing"
                )
        finally:
            verification.close()
        fsync_file(target_path)
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
                rollback_verified = _rollback_published_restore(
                    target_path,
                    target_existed=target_existed,
                    safety_backup=safety_backup,
                    safety_backup_verified=safety_backup_verified,
                )
                rollback_succeeded = True
            except BaseException as caught_rollback_error:
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

    emit(
        {
            "database": str(target_path),
            "restored_from": str(source_path),
            "safety_backup": safety_backup,
            "safety_backup_verified": safety_backup_verified,
            "schema_version": SCHEMA_VERSION,
            "verified": (
                checks == {"integrity_check": "ok", "foreign_key_check": "ok"}
                and invariant_checks == {"coordination_invariants": "ok"}
                and final_checks
                == {"integrity_check": "ok", "foreign_key_check": "ok"}
                and final_invariants == {"coordination_invariants": "ok"}
            ),
            "publication": "atomic_replace",
            "audit_recorded": True,
            "rollback_performed": rollback_performed,
        }
    )


def restore(args: argparse.Namespace) -> None:
    if not args.force:
        fail(
            "confirmation_required",
            "Restore replaces coordination state; pass --force to confirm",
            EXIT_USAGE,
        )
    target_path = discover_db(args.db)
    source_path = operational_path(
        args.input,
        label="Restore input",
        must_exist=True,
    )
    validate_not_managed_metadata(source_path, label="Restore input")
    validate_enclosing_configured_database_namespace(
        source_path,
        label="Restore input",
        allow_configured_main=True,
    )
    validate_external_path(source_path, target_path, label="Restore input")
    validate_database_namespaces_disjoint(
        source_path,
        target_path,
        label="Restore source and target",
    )
    validate_restore_target_path(target_path)
    safety_directory = _restore_safety_directory(target_path)
    if paths_refer_to_same_file(target_path, safety_directory):
        fail(
            "invalid_arguments",
            "Restore target must not alias its safety-backup directory",
            EXIT_USAGE,
            {
                "database": str(target_path),
                "safety_backup_directory": str(safety_directory),
                "target_unchanged": True,
            },
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    validate_database_operational_files(target_path)

    # The target lock covers source verification and staging as well as publication.
    # Once a restore intent has passed input validation, no canonical client may
    # start a mutation against the state that is about to be replaced.
    with advisory_file_lock(database_lock_path(target_path), exclusive=True):
        _restore_while_locked(args, target_path, source_path)


def register(commands: argparse._SubParsersAction) -> None:
    backup_parser = commands.add_parser(
        "backup",
        help="Create and verify an atomic SQLite backup",
    )
    backup_parser.add_argument("--output", required=True, type=path_argument)
    backup_parser.add_argument("--force", action="store_true")
    backup_parser.set_defaults(func=backup)

    restore_parser = commands.add_parser(
        "restore",
        help="Restore a verified SQLite backup",
    )
    restore_parser.add_argument("--input", required=True, type=path_argument)
    restore_parser.add_argument("--actor", required=True, type=identifier)
    restore_parser.add_argument("--force", action="store_true")
    restore_parser.set_defaults(func=restore)
