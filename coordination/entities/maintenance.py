"""Verified backup and restore operations."""

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
    audit,
    check_database_integrity,
    check_coordination_invariants,
    configured_busy_timeout_ms,
    connect,
    connect_read_only,
    discover_db,
    emit,
    ensure_supported_schema,
    require_row,
    transaction,
)
from coordination.errors import (
    EXIT_CONFLICT,
    EXIT_ENVIRONMENT,
    EXIT_USAGE,
    CoordinationError,
    fail,
)


def atomic_backup(
    source: sqlite3.Connection,
    destination: Path,
    *,
    force: bool,
) -> dict[str, object]:
    if destination.exists() and not force:
        fail(
            "output_exists",
            f"Backup already exists: {destination}. Pass --force to replace it.",
            EXIT_CONFLICT,
            {"output": str(destination)},
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    destination_connection: sqlite3.Connection | None = None
    try:
        destination_connection = sqlite3.connect(temporary)
        destination_connection.row_factory = sqlite3.Row
        source.backup(destination_connection)
        destination_connection.execute("PRAGMA foreign_keys = ON")
        ensure_supported_schema(destination_connection)
        checks = check_database_integrity(destination_connection)
        invariant_checks = check_coordination_invariants(destination_connection)
        destination_connection.close()
        destination_connection = None
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if destination_connection is not None:
            destination_connection.close()
        temporary.unlink(missing_ok=True)
        Path(f"{temporary}-wal").unlink(missing_ok=True)
        Path(f"{temporary}-shm").unlink(missing_ok=True)
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
    destination = Path(args.output).expanduser().resolve()
    if source_path == destination:
        fail(
            "invalid_arguments",
            "Backup destination must differ from the source database",
            EXIT_USAGE,
        )
    source = connect(source_path)
    result = atomic_backup(source, destination, force=args.force)
    result["source"] = str(source_path)
    emit(result)


def preserve_unhealthy_target(target: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, destination)
    os.chmod(destination, 0o600)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{target}{suffix}")
        if sidecar.is_file():
            copied_sidecar = Path(f"{destination}{suffix}")
            shutil.copy2(sidecar, copied_sidecar)
            os.chmod(copied_sidecar, 0o600)
    return str(destination)


def replace_unreadable_target(
    source: sqlite3.Connection,
    target_path: Path,
) -> sqlite3.Connection:
    descriptor, staged_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.restore.",
        suffix=".sqlite3",
        dir=target_path.parent,
    )
    os.close(descriptor)
    staged = Path(staged_name)
    staged.unlink()
    try:
        atomic_backup(source, staged, force=False)
        for suffix in ("-wal", "-shm"):
            Path(f"{target_path}{suffix}").unlink(missing_ok=True)
        os.replace(staged, target_path)
    finally:
        staged.unlink(missing_ok=True)
    timeout_ms = configured_busy_timeout_ms()
    connection = sqlite3.connect(target_path, timeout=timeout_ms / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
    return connection


def restore(args: argparse.Namespace) -> None:
    if not args.force:
        fail(
            "confirmation_required",
            "Restore replaces coordination state; pass --force to confirm",
            EXIT_USAGE,
        )
    target_path = discover_db(args.db)
    source_path = Path(args.input).expanduser().resolve()
    if source_path == target_path:
        fail(
            "invalid_arguments",
            "Restore input must differ from the coordination database",
            EXIT_USAGE,
        )

    source = connect_read_only(source_path)
    check_database_integrity(source)
    check_coordination_invariants(source)
    require_row(
        source,
        "SELECT id FROM agents WHERE id = ? AND status = 'active'",
        (args.actor,),
        f"active agent {args.actor} in restore input",
    )

    target_existed = target_path.is_file()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = configured_busy_timeout_ms()
    target = sqlite3.connect(target_path, timeout=timeout_ms / 1000)
    target.row_factory = sqlite3.Row
    target.execute("PRAGMA foreign_keys = ON")
    target.execute(f"PRAGMA busy_timeout = {timeout_ms}")

    target_healthy = False
    target_unreadable = False
    if target_existed:
        try:
            ensure_supported_schema(target)
            check_database_integrity(target)
            check_coordination_invariants(target)
            target_healthy = True
        except CoordinationError as error:
            if error.exit_code != EXIT_ENVIRONMENT:
                raise
        except sqlite3.DatabaseError:
            target_unreadable = True

    safety_backup: str | None = None
    safety_backup_verified: bool | None = None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if target_healthy:
        active_sessions = [
            str(row[0])
            for row in target.execute(
                """SELECT id FROM agent_sessions
                   WHERE status = 'active'
                   ORDER BY id"""
            )
        ]
        if active_sessions:
            fail(
                "restore_active_sessions",
                "End or recover every active session before restoring",
                EXIT_CONFLICT,
                {"sessions": active_sessions},
            )
        safety_path = target_path.parent / "backups" / f"pre-restore-{stamp}.sqlite3"
        safety_backup = str(
            atomic_backup(target, safety_path, force=False)["backup"]
        )
        safety_backup_verified = True
    elif target_existed:
        safety_path = (
            target_path.parent
            / "backups"
            / f"pre-restore-unverified-{stamp}.sqlite3"
        )
        target.close()
        safety_backup = preserve_unhealthy_target(target_path, safety_path)
        safety_backup_verified = False
        target = sqlite3.connect(target_path, timeout=timeout_ms / 1000)
        target.row_factory = sqlite3.Row
        target.execute(f"PRAGMA busy_timeout = {timeout_ms}")

    try:
        if target_unreadable:
            target.close()
            target = replace_unreadable_target(source, target_path)
        else:
            try:
                source.backup(target)
            except sqlite3.DatabaseError:
                target.close()
                target = replace_unreadable_target(source, target_path)
        ensure_supported_schema(target)
        checks = check_database_integrity(target)
        invariant_checks = check_coordination_invariants(target)
        target.execute("PRAGMA journal_mode = WAL")
        with transaction(target):
            audit(
                target,
                args.actor,
                "restore",
                "database",
                str(target_path),
                f"restored from {source_path}",
            )
    except Exception:
        target.close()
        raise
    target.close()
    source.close()
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
            ),
        }
    )


def register(commands: argparse._SubParsersAction) -> None:
    backup_parser = commands.add_parser(
        "backup",
        help="Create and verify an atomic SQLite backup",
    )
    backup_parser.add_argument("--output", required=True)
    backup_parser.add_argument("--force", action="store_true")
    backup_parser.set_defaults(func=backup)

    restore_parser = commands.add_parser(
        "restore",
        help="Restore a verified SQLite backup",
    )
    restore_parser.add_argument("--input", required=True)
    restore_parser.add_argument("--actor", required=True)
    restore_parser.add_argument("--force", action="store_true")
    restore_parser.set_defaults(func=restore)
