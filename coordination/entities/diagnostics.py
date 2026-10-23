"""CLI version and database diagnostic commands."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys

from coordination.core import (
    MAX_DIAGNOSTIC_FINDINGS,
    SCHEMA_VERSION,
    check_coordination_invariants,
    check_database_integrity,
    connect,
    discover_db,
    read_transaction,
    runtime_version,
)
from coordination.errors import EXIT_ENVIRONMENT, fail


def version(args: argparse.Namespace) -> dict[str, object]:
    return {
        "cli_version": runtime_version(),
        "schema_version": SCHEMA_VERSION,
    }


# SQLite's WAL mode needs every process on one host with shared memory; a
# network, VM-share, or FUSE filesystem breaks that silently.
SHARED_FILESYSTEM_TYPES = frozenset(
    {
        "9p",
        "afpfs",
        "cifs",
        "drvfs",
        "lxfs",
        "nfs",
        "nfs4",
        "prl_fs",
        "smb3",
        "smbfs",
        "sshfs",
        "vboxsf",
        "virtiofs",
        "vmhgfs",
        "webdav",
    }
)


def mount_entries_linux(text: str) -> list[tuple[str, str]]:
    """(mount point, filesystem type) pairs from /proc/self/mounts text."""
    entries = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 3:
            mount_point = fields[1].replace("\\040", " ").replace("\\011", "\t")
            entries.append((mount_point, fields[2]))
    return entries


def mount_entries_darwin(text: str) -> list[tuple[str, str]]:
    """(mount point, filesystem type) pairs from macOS `mount` output."""
    entries = []
    for line in text.splitlines():
        match = re.match(r"^.+? on (.+) \(([^,)]+)", line)
        if match:
            entries.append((match.group(1), match.group(2).strip()))
    return entries


def filesystem_type_for(path: Path, entries: list[tuple[str, str]]) -> str | None:
    """The type of the longest mount point that contains `path`."""
    best: tuple[int, str] | None = None
    resolved = str(path.resolve())
    for mount_point, filesystem in entries:
        prefix = mount_point.rstrip("/") or "/"
        contains = resolved == prefix or resolved.startswith(prefix.rstrip("/") + "/")
        if contains and (best is None or len(prefix) > best[0]):
            best = (len(prefix), filesystem)
    return None if best is None else best[1]


def is_shared_filesystem(filesystem: str | None) -> bool:
    if filesystem is None:
        return False
    lowered = filesystem.lower()
    return (
        lowered in SHARED_FILESYSTEM_TYPES
        or lowered.startswith("nfs")
        or "fuse" in lowered
    )


def filesystem_report(database: Path) -> dict[str, object]:
    """Report the database's filesystem; a shared one earns a warning."""
    entries: list[tuple[str, str]] = []
    try:
        mounts = Path("/proc/self/mounts")
        if mounts.is_file():
            entries = mount_entries_linux(mounts.read_text(encoding="utf-8"))
        elif sys.platform == "darwin" and Path("/sbin/mount").is_file():
            completed = subprocess.run(
                ["/sbin/mount"], capture_output=True, text=True, timeout=5
            )
            if completed.returncode == 0:
                entries = mount_entries_darwin(completed.stdout)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        entries = []
    filesystem = filesystem_type_for(database.parent, entries)
    leftovers = sorted(
        candidate.name for candidate in database.parent.glob(".fuse_hidden*")
    )
    warning: str | None = None
    if is_shared_filesystem(filesystem):
        warning = (
            f"The database is on a {filesystem} filesystem. SQLite WAL mode"
            " requires every process on one host; run agents on the machine"
            " that holds the database."
        )
    elif leftovers:
        warning = (
            "FUSE leftovers beside the database show it was reached through"
            " a VM or FUSE mount; run agents on the machine that holds it."
        )
    return {
        "filesystem_type": filesystem,
        "filesystem_warning": warning,
        "filesystem_fuse_leftovers": leftovers,
    }


def doctor(args: argparse.Namespace) -> dict[str, object]:
    path = discover_db(args.db)
    if not path.is_file():
        # `connect` raises database_not_found for exactly this condition, which
        # is doctor's documented result for a missing database. It never
        # returns here, so this branch produces no diagnostic payload.
        connect(path)
    database_mode = stat.S_IMODE(path.stat().st_mode)
    directory_mode = stat.S_IMODE(path.parent.stat().st_mode)
    database_writable = bool(database_mode & 0o222) and os.access(path, os.W_OK)
    directory_writable = bool(directory_mode & 0o222) and os.access(
        path.parent, os.W_OK
    )
    if not database_writable or not directory_writable:
        fail(
            "database_not_writable",
            "Coordination database and its directory must be writable",
            EXIT_ENVIRONMENT,
            {
                "database_writable": database_writable,
                "directory_writable": directory_writable,
            },
        )
    connection = connect(path)
    with read_transaction(connection):
        checks = check_database_integrity(connection)
        invariant_checks = check_coordination_invariants(connection)
        metadata_version = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
        synchronous_level = int(connection.execute("PRAGMA synchronous").fetchone()[0])
        busy_timeout_ms = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])
        foreign_keys = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
        journal_mode = str(
            connection.execute("PRAGMA journal_mode").fetchone()[0]
        ).lower()
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        out_of_band = out_of_band_edits(connection)
    filesystem = filesystem_report(path)
    synchronous_names = {0: "off", 1: "normal", 2: "full", 3: "extra"}
    return {
        "healthy": True,
        "cli_version": runtime_version(),
        "database": str(path),
        "database_writable": database_writable,
        "directory_writable": directory_writable,
        "busy_timeout_ms": busy_timeout_ms,
        "foreign_keys": foreign_keys,
        **checks,
        **invariant_checks,
        "journal_mode": journal_mode,
        "metadata_schema_version": int(metadata_version),
        "schema_version": schema_version,
        "synchronous": synchronous_names.get(synchronous_level, str(synchronous_level)),
        "record_consistency": "ok" if not out_of_band["findings"] else "findings",
        "out_of_band_edits": out_of_band["findings"],
        "out_of_band_edit_count": out_of_band["count"],
        "out_of_band_edits_truncated": out_of_band["truncated"],
        **filesystem,
    }


# Tables whose rows carry `updated_at`, keyed by the audit object_type that
# records their mutations. Every write through the runtime audits before it
# commits, so a row whose `updated_at` postdates its last audit row -- or that
# has no audit row at all -- was written around the runtime.
OUT_OF_BAND_TABLES = (
    ("tasks", "task"),
    ("agents", "agent"),
    ("decisions", "decision"),
    ("artifacts", "artifact"),
    ("escalations", "escalation"),
)


def out_of_band_edits(connection: sqlite3.Connection) -> dict[str, object]:
    """Find rows changed outside the runtime, bounded, ordered by table and id.

    This is the schema-v1 record-consistency check: not tamper evidence
    against an adversary (ADR 0001), but the honest signal that a cooperating
    human or agent edited the database file directly, which the project's own
    guidance forbids. `doctor` reports it; it does not fail.
    """
    findings: list[dict[str, object]] = []
    count = 0
    truncated = False
    for table, object_type in OUT_OF_BAND_TABLES:
        rows_found = connection.execute(
            f"""SELECT t.id, t.updated_at,
                       (SELECT MAX(a.created_at) FROM audit_log a
                         WHERE a.object_type = ? AND a.object_id = t.id)
                         AS last_audit_at
                  FROM {table} t
                 WHERE t.updated_at > COALESCE(
                         (SELECT MAX(a.created_at) FROM audit_log a
                           WHERE a.object_type = ? AND a.object_id = t.id), '')
                 ORDER BY t.id
                 LIMIT ?""",
            (object_type, object_type, MAX_DIAGNOSTIC_FINDINGS + 1),
        ).fetchall()
        if len(rows_found) > MAX_DIAGNOSTIC_FINDINGS:
            truncated = True
            rows_found = rows_found[:MAX_DIAGNOSTIC_FINDINGS]
        count += len(rows_found)
        findings.extend(
            {
                "table": table,
                "id": str(row["id"]),
                "updated_at": str(row["updated_at"]),
                "last_audit_at": (
                    None if row["last_audit_at"] is None else str(row["last_audit_at"])
                ),
            }
            for row in rows_found
        )
    return {"findings": findings, "count": count, "truncated": truncated}


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    version_parser = commands.add_parser(
        "version",
        help="Report CLI and supported schema versions",
    )
    version_parser.set_defaults(func=version)

    doctor_parser = commands.add_parser(
        "doctor",
        help="Validate the discovered SQLite coordination installation",
    )
    doctor_parser.set_defaults(func=doctor)
