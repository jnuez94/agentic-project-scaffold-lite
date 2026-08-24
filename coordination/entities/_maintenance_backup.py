"""Verified, failure-atomic backup: staged copy, checks, publication."""

from __future__ import annotations

import argparse
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
    database_lock_path,
    discover_db,
    ensure_supported_schema,
    fsync_directory,
    fsync_file,
    operational_path,
    output_lock_path,
    publish_temporary_file,
    transaction,
    validate_database_namespaces_disjoint,
    validate_database_operational_files,
    validate_output_path,
)
from coordination.errors import (
    EXIT_CONFLICT,
    EXIT_USAGE,
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


def backup(args: argparse.Namespace) -> dict[str, object]:
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
        # Egress belongs in the record. When an actor is named, the backup is
        # audited in the source database after the copy is published; over
        # MCP the actor is required.
        actor = getattr(args, "actor", None)
        if actor:
            with transaction(source):
                audit(
                    source,
                    actor,
                    "backup",
                    "database",
                    str(source_path),
                    f"output {destination}",
                    session_id=args.session,
                )
        result["audit_recorded"] = bool(actor)
    finally:
        close_connection(source)
    result["source"] = str(source_path)
    return result


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
