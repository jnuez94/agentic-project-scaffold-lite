"""Shared database, discovery, audit, and output infrastructure."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import fcntl
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, BinaryIO, Generator, Iterable

from coordination.errors import (
    EXIT_BUSY,
    EXIT_CONFLICT,
    EXIT_ENVIRONMENT,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    fail,
)


SCHEMA_VERSION = 1
DEFAULT_BUSY_TIMEOUT_MS = 5000
MAX_BUSY_TIMEOUT_MS = 60000
MAX_IDENTIFIER_LENGTH = 128
MAX_TEXT_LENGTH = 65536
MAX_PATH_LENGTH = 4096
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500
MAX_STALE_DAYS = 3650
MAX_STALE_SESSION_MINUTES = 5_256_000
MAX_STALE_SECONDS = 315_360_000
MAX_DIAGNOSTIC_FINDINGS = 100
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+-]*\Z")
_CONNECTION_LOCKS: dict[int, BinaryIO] = {}
REQUIRED_COLUMNS = {
    "metadata": frozenset({"key", "value"}),
    "agents": frozenset(
        {
            "id",
            "name",
            "role",
            "actor_type",
            "status",
            "responsibilities",
            "goal",
            "operating_style",
            "decision_authority",
            "review_authority",
            "escalation_rules",
            "unavailable_for",
            "created_at",
            "updated_at",
        }
    ),
    "agent_sessions": frozenset(
        {
            "id",
            "agent_id",
            "harness",
            "model",
            "status",
            "started_at",
            "last_seen_at",
            "ended_at",
        }
    ),
    "tasks": frozenset(
        {
            "id",
            "title",
            "description",
            "status",
            "priority",
            "tags",
            "acceptance_criteria",
            "next_steps",
            "blocked_claims",
            "notes",
            "revision",
            "created_by",
            "created_at",
            "updated_at",
        }
    ),
    "task_assignees": frozenset({"task_id", "agent_id", "assigned_at"}),
    "task_claims": frozenset({"task_id", "agent_id", "session_id", "claimed_at"}),
    "task_dependencies": frozenset(
        {
            "task_id",
            "depends_on_task_id",
            "dependency_type",
            "status",
            "rationale",
            "created_at",
        }
    ),
    "task_evidence": frozenset(
        {"id", "task_id", "uri", "evidence_type", "added_by", "created_at"}
    ),
    "messages": frozenset(
        {"id", "sender_id", "recipient", "task_id", "body", "tags", "created_at"}
    ),
    "reviews": frozenset(
        {
            "id",
            "task_id",
            "reviewer_id",
            "artifact_uri",
            "scope",
            "decision",
            "accepted_items",
            "required_changes",
            "remaining_risks",
            "blocked_claims",
            "follow_up_tasks",
            "created_at",
        }
    ),
    "decisions": frozenset(
        {
            "id",
            "title",
            "owner_id",
            "status",
            "context",
            "decision",
            "options_considered",
            "implications",
            "evidence",
            "blocked_claims",
            "review_required",
            "created_at",
            "updated_at",
        }
    ),
    "artifacts": frozenset(
        {
            "id",
            "uri",
            "owner_id",
            "type",
            "status",
            "usage_boundaries",
            "created_at",
            "updated_at",
        }
    ),
    "artifact_tasks": frozenset({"artifact_id", "task_id"}),
    "artifact_reviewers": frozenset({"artifact_id", "reviewer_id"}),
    "escalations": frozenset(
        {
            "id",
            "raised_by",
            "owner",
            "status",
            "related_tasks",
            "needed_by",
            "issue",
            "requested_decision",
            "resolution",
            "follow_up_tasks",
            "created_at",
            "updated_at",
        }
    ),
    "audit_log": frozenset(
        {
            "id",
            "actor",
            "session_id",
            "action",
            "object_type",
            "object_id",
            "detail",
            "created_at",
        }
    ),
}
REQUIRED_TABLES = frozenset(REQUIRED_COLUMNS)
REQUIRED_INDEXES = frozenset(
    {
        "idx_tasks_status_priority",
        "idx_agent_sessions_agent_status",
        "idx_task_assignees_agent",
        "idx_task_claims_agent",
        "idx_evidence_task",
        "idx_reviews_task",
        "idx_messages_recipient",
        "idx_escalations_status",
        "idx_audit_session",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "task_claim_requires_active_session",
        "task_claim_requires_claimable_state",
        "task_enter_in_progress_requires_claim",
        "task_insert_done_requires_evidence",
        "task_status_requires_next_revision",
        "task_update_done_requires_evidence",
    }
)


def identifier(value: str) -> str:
    """Validate a stable public identifier without silently rewriting it."""
    if (
        not 1 <= len(value) <= MAX_IDENTIFIER_LENGTH
        or IDENTIFIER_PATTERN.fullmatch(value) is None
    ):
        raise argparse.ArgumentTypeError(
            "must be 1-128 ASCII characters: letters, digits, '.', '_', ':', '@', '+', or '-'"
        )
    return value


def required_text(value: str) -> str:
    """Validate a required human-readable value while preserving its content."""
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be empty or whitespace")
    return optional_text(value)


def optional_text(value: str) -> str:
    if "\x00" in value:
        raise argparse.ArgumentTypeError("must not contain a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise argparse.ArgumentTypeError(
            "must contain valid Unicode scalar values"
        ) from error
    if len(value) > MAX_TEXT_LENGTH:
        raise argparse.ArgumentTypeError(
            f"must be at most {MAX_TEXT_LENGTH} characters"
        )
    return value


def path_argument(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("path must not be empty or whitespace")
    if "\x00" in value:
        raise argparse.ArgumentTypeError("path must not contain a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise argparse.ArgumentTypeError(
            "path must contain valid Unicode scalar values"
        ) from error
    if len(value) > MAX_PATH_LENGTH:
        raise argparse.ArgumentTypeError(
            f"path must be at most {MAX_PATH_LENGTH} characters"
        )
    return value


def _bounded_integer(value: str, minimum: int, maximum: int, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{label} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(
            f"{label} must be between {minimum} and {maximum}"
        )
    return parsed


def positive_revision(value: str) -> int:
    return _bounded_integer(value, 1, 2_147_483_647, "revision")


def list_limit(value: str) -> int:
    return _bounded_integer(value, 1, MAX_LIST_LIMIT, "limit")


def list_offset(value: str) -> int:
    return _bounded_integer(value, 0, 2_147_483_647, "offset")


def stale_days(value: str) -> int:
    return _bounded_integer(value, 0, MAX_STALE_DAYS, "stale days")


def stale_session_minutes(value: str) -> int:
    return _bounded_integer(
        value,
        0,
        MAX_STALE_SESSION_MINUTES,
        "stale session minutes",
    )


def stale_seconds(value: str) -> int:
    return _bounded_integer(value, 0, MAX_STALE_SECONDS, "stale seconds")


def require_unique(values: list[str], option: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        fail(
            "invalid_arguments",
            f"{option} may not contain duplicate values",
            EXIT_USAGE,
            {"option": option, "duplicates": duplicates},
        )


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def configured_busy_timeout_ms() -> int:
    raw = os.environ.get("COORDINATION_BUSY_TIMEOUT_MS", str(DEFAULT_BUSY_TIMEOUT_MS))
    try:
        value = int(raw)
    except ValueError:
        fail(
            "configuration_error",
            "COORDINATION_BUSY_TIMEOUT_MS must be an integer",
            EXIT_ENVIRONMENT,
            {"value": raw},
        )
    if not 0 <= value <= MAX_BUSY_TIMEOUT_MS:
        fail(
            "configuration_error",
            f"COORDINATION_BUSY_TIMEOUT_MS must be between 0 and {MAX_BUSY_TIMEOUT_MS}",
            EXIT_ENVIRONMENT,
            {"value": value},
        )
    return value


def database_lock_path(path: Path) -> Path:
    return Path(f"{path}.lock")


def output_lock_path(path: Path) -> Path:
    return path.parent / f".{path.name}.publish.lock"


def validate_database_operational_files(path: Path) -> None:
    database_exists = path.exists()
    if database_exists:
        if path.is_symlink() or not path.is_file():
            fail(
                "database_configuration_error",
                "Coordination database must be a regular file",
                EXIT_ENVIRONMENT,
                {"database": str(path)},
            )
        if path.stat().st_nlink != 1:
            fail(
                "database_configuration_error",
                "Coordination database must not have hard-link aliases",
                EXIT_ENVIRONMENT,
                {"database": str(path)},
            )
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.is_symlink() or (sidecar.exists() and not sidecar.is_file()):
            fail(
                "database_configuration_error",
                "SQLite operational sidecars must be regular files",
                EXIT_ENVIRONMENT,
                {"database": str(path), "operational_path": str(sidecar)},
            )
        if sidecar.is_file():
            if not database_exists:
                fail(
                    "database_configuration_error",
                    "Refusing stale SQLite sidecars for an absent database",
                    EXIT_ENVIRONMENT,
                    {"database": str(path), "operational_path": str(sidecar)},
                )
            if sidecar.stat().st_nlink != 1:
                fail(
                    "database_configuration_error",
                    "SQLite operational sidecars must not have hard-link aliases",
                    EXIT_ENVIRONMENT,
                    {"database": str(path), "operational_path": str(sidecar)},
                )
    lock = database_lock_path(path)
    if lock.is_symlink() or (lock.exists() and not lock.is_file()):
        fail(
            "database_configuration_error",
            "The database advisory lock must be a regular file",
            EXIT_ENVIRONMENT,
            {"database": str(path), "operational_path": str(lock)},
        )
    if lock.is_file() and lock.stat().st_nlink != 1:
        fail(
            "database_configuration_error",
            "The database advisory lock must not have hard-link aliases",
            EXIT_ENVIRONMENT,
            {"database": str(path), "operational_path": str(lock)},
        )


def _acquire_file_lock(
    path: Path,
    *,
    exclusive: bool,
    timeout_ms: int,
) -> BinaryIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    handle = os.fdopen(descriptor, "a+b", buffering=0)
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    deadline = time.monotonic() + (timeout_ms / 1000)
    while True:
        try:
            fcntl.flock(handle.fileno(), operation | fcntl.LOCK_NB)
            return handle
        except BlockingIOError:
            if time.monotonic() >= deadline:
                handle.close()
                fail(
                    "database_busy",
                    "Timed out waiting for an operational file lock",
                    EXIT_BUSY,
                    {"lock": str(path), "timeout_ms": timeout_ms},
                )
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        except BaseException:
            handle.close()
            raise


def _release_file_lock(handle: BinaryIO) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def advisory_file_lock(
    path: Path,
    *,
    exclusive: bool,
    timeout_ms: int | None = None,
) -> Generator[None, None, None]:
    handle = _acquire_file_lock(
        path,
        exclusive=exclusive,
        timeout_ms=(
            configured_busy_timeout_ms() if timeout_ms is None else timeout_ms
        ),
    )
    try:
        yield
    finally:
        _release_file_lock(handle)


def close_connection(connection: sqlite3.Connection) -> None:
    try:
        connection.close()
    finally:
        handle = _CONNECTION_LOCKS.pop(id(connection), None)
        if handle is not None:
            _release_file_lock(handle)


def paths_refer_to_same_file(left: Path, right: Path) -> bool:
    left_resolved = left.resolve()
    right_resolved = right.resolve()
    if left_resolved == right_resolved:
        return True
    try:
        if left.exists() and right.exists() and os.path.samefile(left, right):
            return True
    except OSError:
        pass
    try:
        parents_match = (
            left_resolved.parent == right_resolved.parent
            or os.path.samefile(left_resolved.parent, right_resolved.parent)
        )
    except OSError:
        parents_match = False
    return (
        parents_match
        and left_resolved.name.casefold() == right_resolved.name.casefold()
    )


def expand_user_path(value: str, *, label: str) -> Path:
    try:
        return Path(value).expanduser()
    except RuntimeError as error:
        fail(
            "invalid_arguments",
            f"{label} contains an unknown home-directory alias",
            EXIT_USAGE,
            {"path": value, "reason": str(error)},
        )


def operational_path(
    value: str,
    *,
    label: str,
    must_exist: bool,
) -> Path:
    expanded = expand_user_path(value, label=label)
    parent = expanded.parent.resolve()
    candidate = parent / expanded.name
    if candidate.is_symlink():
        fail(
            "invalid_arguments",
            f"{label} must not be a symbolic link",
            EXIT_USAGE,
            {"path": str(candidate)},
        )
    if candidate.exists() and not candidate.is_file():
        fail(
            "invalid_arguments",
            f"{label} must be a regular file",
            EXIT_USAGE,
            {"path": str(candidate)},
        )
    if must_exist and not candidate.is_file():
        fail(
            "database_not_found",
            f"{label} not found: {candidate}",
            EXIT_NOT_FOUND,
            {"path": str(candidate)},
        )
    if parent.exists() and not parent.is_dir():
        fail(
            "invalid_arguments",
            f"{label} parent must be a directory",
            EXIT_USAGE,
            {"path": str(candidate), "parent": str(parent)},
        )
    return candidate


def protected_database_paths(path: Path) -> tuple[Path, ...]:
    return tuple(
        Path(f"{path}{suffix}")
        for suffix in ("", "-wal", "-shm", "-journal", ".lock")
    )


def validate_database_namespaces_disjoint(
    left: Path,
    right: Path,
    *,
    label: str,
) -> None:
    for left_path in protected_database_paths(left):
        for right_path in protected_database_paths(right):
            if paths_refer_to_same_file(left_path, right_path):
                fail(
                    "invalid_arguments",
                    f"{label} databases must have disjoint operational paths",
                    EXIT_USAGE,
                    {
                        "left_database": str(left),
                        "right_database": str(right),
                        "left_protected_path": str(left_path),
                        "right_protected_path": str(right_path),
                    },
                )


def coordination_root_for_database(database: Path) -> Path:
    for ancestor in (database.parent, *database.parent.parents):
        if ancestor.name.casefold() == ".coordination":
            return ancestor
    return database.parent


def protected_coordination_metadata_paths(database: Path) -> tuple[Path, ...]:
    roots = [
        ancestor
        for ancestor in (database.parent, *database.parent.parents)
        if ancestor.name.casefold() == ".coordination"
    ]
    candidates = [
        root / filename
        for root in dict.fromkeys(roots)
        for filename in ("config.yml", "README.md")
    ]
    return tuple(dict.fromkeys(candidates))


def validate_not_managed_metadata(candidate: Path, *, label: str) -> None:
    for ancestor in (candidate.parent, *candidate.parent.parents):
        if ancestor.name.casefold() != ".coordination":
            continue
        for filename in ("config.yml", "README.md"):
            metadata = ancestor / filename
            if paths_refer_to_same_file(candidate, metadata):
                fail(
                    "invalid_arguments",
                    f"{label} must not alias managed coordination metadata",
                    EXIT_USAGE,
                    {"path": str(candidate), "protected_path": str(metadata)},
                )


def validate_enclosing_configured_database_namespace(
    candidate: Path,
    *,
    label: str,
    allow_configured_main: bool,
    candidate_is_database: bool = True,
) -> None:
    """Protect the live database namespace selected by an enclosing project."""
    for ancestor in (candidate.parent, *candidate.parent.parents):
        if ancestor.name.casefold() != ".coordination":
            continue
        config = ancestor / "config.yml"
        if config.is_symlink() or (config.exists() and not config.is_file()):
            fail(
                "invalid_arguments",
                f"{label} is inside a coordination root with invalid configuration",
                EXIT_USAGE,
                {"path": str(candidate), "configuration": str(config)},
            )
        if not config.is_file():
            continue
        configured_database = _project_database_from_config(config)
        if allow_configured_main and paths_refer_to_same_file(
            candidate,
            configured_database,
        ):
            continue
        candidate_paths = (
            protected_database_paths(candidate)
            if candidate_is_database
            else (candidate,)
        )
        for candidate_path in candidate_paths:
            for protected in protected_database_paths(configured_database):
                if paths_refer_to_same_file(candidate_path, protected):
                    fail(
                        "invalid_arguments",
                        (
                            f"{label} must have a disjoint operational namespace "
                            "from the configured database"
                        ),
                        EXIT_USAGE,
                        {
                            "path": str(candidate),
                            "candidate_protected_path": str(candidate_path),
                            "configured_database": str(configured_database),
                            "protected_path": str(protected),
                        },
                    )


def validate_restore_target_path(target: Path) -> None:
    validate_not_managed_metadata(target, label="Restore target")
    validate_enclosing_configured_database_namespace(
        target,
        label="Restore target",
        allow_configured_main=True,
    )


def validate_external_path(
    candidate: Path,
    database: Path,
    *,
    label: str,
) -> None:
    validate_not_managed_metadata(candidate, label=label)
    for protected in protected_database_paths(database):
        if paths_refer_to_same_file(candidate, protected):
            fail(
                "invalid_arguments",
                f"{label} must not alias the coordination database or its operational files",
                EXIT_USAGE,
                {
                    "path": str(candidate),
                    "database": str(database),
                    "protected_path": str(protected),
                },
            )
    for metadata in protected_coordination_metadata_paths(database):
        if paths_refer_to_same_file(candidate, metadata):
            fail(
                "invalid_arguments",
                f"{label} must not alias managed coordination metadata",
                EXIT_USAGE,
                {"path": str(candidate), "protected_path": str(metadata)},
            )


def validate_output_path(
    candidate: Path,
    database: Path,
    *,
    label: str,
    database_namespace: bool,
) -> None:
    validate_external_path(candidate, database, label=label)
    validate_enclosing_configured_database_namespace(
        candidate,
        label=label,
        allow_configured_main=False,
        candidate_is_database=database_namespace,
    )
    validate_external_path(
        output_lock_path(candidate),
        database,
        label=f"{label} publication lock",
    )
    validate_enclosing_configured_database_namespace(
        output_lock_path(candidate),
        label=f"{label} publication lock",
        allow_configured_main=False,
        candidate_is_database=False,
    )


def fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
    finally:
        os.close(descriptor)


def publish_temporary_file(
    temporary: Path,
    destination: Path,
    *,
    force: bool,
) -> None:
    fsync_file(temporary)
    if force:
        os.replace(temporary, destination)
    else:
        try:
            os.link(temporary, destination)
        except FileExistsError:
            fail(
                "output_exists",
                f"Output already exists: {destination}. Pass --force to replace it.",
                EXIT_CONFLICT,
                {"output": str(destination)},
            )
        temporary.unlink()
    fsync_directory(destination.parent)


def emit(value: Any) -> None:
    print(json.dumps({"ok": True, "data": value}, indent=2, sort_keys=True))


def rows(values: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(value) for value in values]


def _project_database_from_config(config: Path) -> Path:
    try:
        content = config.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        fail(
            "configuration_error",
            f"Cannot read coordination configuration: {config}",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "reason": str(error)},
        )
    settings: dict[str, str] = {}
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)", line)
        if match is None:
            fail(
                "configuration_error",
                f"Invalid coordination configuration line {line_number}",
                EXIT_ENVIRONMENT,
                {"configuration": str(config), "line": line_number},
            )
        key, value = match.groups()
        if key in settings:
            fail(
                "configuration_error",
                f"Duplicate coordination configuration key: {key}",
                EXIT_ENVIRONMENT,
                {"configuration": str(config), "key": key},
            )
        settings[key] = value.strip()
    if settings.get("version") != "1":
        fail(
            "configuration_error",
            "Coordination configuration version must be 1",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "version": settings.get("version")},
        )
    if settings.get("backend") != "sqlite":
        fail(
            "configuration_error",
            "The nearest coordination project is not configured for SQLite",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "backend": settings.get("backend")},
        )
    database_value = settings.get("database")
    if not database_value or not database_value.strip():
        fail(
            "configuration_error",
            "SQLite coordination configuration requires a database path",
            EXIT_ENVIRONMENT,
            {"configuration": str(config)},
        )
    if "\x00" in database_value or len(database_value) > MAX_PATH_LENGTH:
        fail(
            "configuration_error",
            "Configured database path is invalid",
            EXIT_ENVIRONMENT,
            {"configuration": str(config)},
        )
    relative = Path(database_value)
    if relative.is_absolute():
        fail(
            "configuration_error",
            "Configured database path must be relative to .coordination",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "database": database_value},
        )
    if ".." in relative.parts:
        fail(
            "configuration_error",
            "Configured database path may not contain parent-directory aliases",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "database": database_value},
        )
    if any(part.casefold() == ".coordination" for part in relative.parts):
        fail(
            "configuration_error",
            "Configured database path may not contain a nested .coordination directory",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "database": database_value},
        )
    if relative.parts and relative.parts[0].casefold() in {
        "config.yml",
        "readme.md",
        "backups",
    }:
        fail(
            "configuration_error",
            "Configured database path conflicts with managed coordination state",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "database": database_value},
        )
    coordination = config.parent.resolve()
    probe = coordination
    for index, part in enumerate(relative.parts):
        if part in ("", "."):
            continue
        probe = probe / part
        if probe.is_symlink():
            fail(
                "configuration_error",
                "Configured database path may not traverse symbolic links",
                EXIT_ENVIRONMENT,
                {
                    "configuration": str(config),
                    "database": database_value,
                    "symbolic_link": str(probe),
                },
            )
        if probe.exists():
            is_last = index == len(relative.parts) - 1
            if is_last and not probe.is_file():
                fail(
                    "configuration_error",
                    "Configured database destination must be a regular file",
                    EXIT_ENVIRONMENT,
                    {"configuration": str(config), "database": str(probe)},
                )
            if not is_last and not probe.is_dir():
                fail(
                    "configuration_error",
                    "Configured database parent must be a directory",
                    EXIT_ENVIRONMENT,
                    {
                        "configuration": str(config),
                        "database": database_value,
                        "parent": str(probe),
                    },
                )
    database = (coordination / relative).resolve()
    try:
        database.relative_to(coordination)
    except ValueError:
        fail(
            "configuration_error",
            "Configured database path must stay inside .coordination",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "database": database_value},
        )
    if database == coordination:
        fail(
            "configuration_error",
            "Configured database path must name a file",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "database": database_value},
        )
    if database.exists() and not database.is_file():
        fail(
            "configuration_error",
            "Configured database path must be a regular file when it exists",
            EXIT_ENVIRONMENT,
            {
                "configuration": str(config),
                "database": str(database),
            },
        )
    if paths_refer_to_same_file(database, config):
        fail(
            "configuration_error",
            "Configured database path must not alias config.yml",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "database": str(database)},
        )
    readme = coordination / "README.md"
    if paths_refer_to_same_file(database, readme):
        fail(
            "configuration_error",
            "Configured database path must not alias the coordination README",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "database": str(database)},
        )
    if database.is_file() and database.stat().st_nlink != 1:
        fail(
            "configuration_error",
            "Configured database must not have hard-link aliases",
            EXIT_ENVIRONMENT,
            {"configuration": str(config), "database": str(database)},
        )
    return database


def discover_db(explicit: str | None, for_init: bool = False) -> Path:
    if explicit is not None:
        if not explicit.strip():
            fail(
                "invalid_arguments",
                "--db must not be empty or whitespace",
                EXIT_USAGE,
            )
        expanded = expand_user_path(explicit, label="Database path")
        if expanded.is_symlink():
            fail(
                "invalid_arguments",
                "--db must not be a symbolic link",
                EXIT_USAGE,
                {"database": str(expanded)},
            )
        database = expanded.resolve()
        if database.exists() and not database.is_file():
            fail(
                "invalid_arguments",
                "--db must be a regular file when it exists",
                EXIT_USAGE,
                {"database": str(database)},
            )
        if database.is_file() and database.stat().st_nlink != 1:
            fail(
                "invalid_arguments",
                "--db must not have hard-link aliases",
                EXIT_USAGE,
                {"database": str(database)},
            )
        database_label = "Initialization database" if for_init else "Database"
        validate_not_managed_metadata(database, label=database_label)
        validate_enclosing_configured_database_namespace(
            database,
            label=database_label,
            allow_configured_main=True,
        )
        return database
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        coordination = directory / ".coordination"
        config = coordination / "config.yml"
        if coordination.is_symlink() or config.is_symlink():
            fail(
                "configuration_error",
                "Coordination discovery does not follow symbolic links",
                EXIT_ENVIRONMENT,
                {"configuration": str(config)},
            )
        if coordination.exists() and not coordination.is_dir():
            fail(
                "configuration_error",
                "Nearest .coordination path must be a directory",
                EXIT_ENVIRONMENT,
                {"coordination": str(coordination)},
            )
        if config.exists() and not config.is_file():
            fail(
                "configuration_error",
                "Nearest coordination configuration must be a regular file",
                EXIT_ENVIRONMENT,
                {"configuration": str(config)},
            )
        if config.is_file():
            return _project_database_from_config(config)
        if coordination.is_dir():
            if for_init and directory == current:
                return coordination / "coordination.sqlite3"
            fail(
                "configuration_error",
                "Nearest coordination directory is missing config.yml",
                EXIT_ENVIRONMENT,
                {"coordination": str(coordination), "configuration": str(config)},
            )
    if for_init:
        return current / ".coordination" / "coordination.sqlite3"
    fail(
        "configuration_error",
        "No SQLite coordination project found. Run from the project or pass --db PATH.",
        EXIT_ENVIRONMENT,
    )


def runtime_root() -> Path:
    """Resolve only the canonical source or managed installed layout."""
    package_directory = Path(__file__).resolve().parent
    package_parent = package_directory.parent
    if (
        package_directory.name == "coordination"
        and package_parent.name == "lib"
        and (package_parent.parent / "bin" / "coordination").is_file()
    ):
        return package_parent.parent
    if (
        package_directory.name == "coordination"
        and (package_parent / "scripts" / "coordination.py").is_file()
    ):
        return package_parent
    fail(
        "installation_error",
        "The coordination package is not in the canonical source or installed layout",
        EXIT_ENVIRONMENT,
    )


def schema_path() -> Path:
    candidate = runtime_root() / "sqlite" / "schema.sql"
    if candidate.is_symlink() or not candidate.is_file():
        fail(
            "installation_error",
            "SQLite schema is not installed with the coordination runtime",
            EXIT_ENVIRONMENT,
        )
    return candidate


@lru_cache(maxsize=1)
def canonical_schema_sql() -> str:
    path = schema_path()
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        fail(
            "installation_error",
            "Installed SQLite schema cannot be read as UTF-8",
            EXIT_ENVIRONMENT,
            {"schema": str(path), "reason": type(error).__name__},
        )
    if not content.strip():
        fail(
            "installation_error",
            "Installed SQLite schema is empty",
            EXIT_ENVIRONMENT,
            {"schema": str(path)},
        )
    return content


def runtime_version() -> str:
    version = runtime_root() / "VERSION"
    if version.is_symlink() or not version.is_file():
        fail(
            "installation_error",
            "VERSION is not installed with the coordination runtime",
            EXIT_ENVIRONMENT,
        )
    try:
        value = version.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        fail(
            "installation_error",
            "Installed VERSION cannot be read",
            EXIT_ENVIRONMENT,
            {"version_file": str(version), "reason": str(error)},
        )
    if re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
        r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
        value,
    ) is None:
        fail(
            "installation_error",
            "Installed VERSION is not valid semantic version text",
            EXIT_ENVIRONMENT,
            {"version_file": str(version)},
        )
    return value


def schema_details(connection: sqlite3.Connection) -> dict[str, Any]:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    objects: dict[str, set[str]] = {
        "table": set(),
        "index": set(),
        "trigger": set(),
        "view": set(),
    }
    definitions: dict[tuple[str, str], tuple[str, str]] = {}
    for row in connection.execute(
        """SELECT type, name, tbl_name, sql FROM sqlite_master
           WHERE type IN ('table', 'index', 'trigger', 'view')
             AND name NOT LIKE 'sqlite_%'"""
    ):
        objects[str(row[0])].add(str(row[1]))
        definitions[(str(row[0]), str(row[1]))] = (
            str(row[2]),
            str(row[3] or ""),
        )
    tables = objects["table"]
    columns = {
        table: {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        for table in REQUIRED_TABLES & tables
    }
    metadata_version: str | None = None
    if REQUIRED_COLUMNS["metadata"] <= columns.get("metadata", set()):
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None:
            metadata_version = str(row[0])
    return {
        "schema_version": version,
        "metadata_schema_version": metadata_version,
        "tables": tables,
        "columns": columns,
        "indexes": objects["index"],
        "triggers": objects["trigger"],
        "views": objects["view"],
        "definitions": definitions,
    }


@lru_cache(maxsize=1)
def expected_schema_definitions() -> dict[tuple[str, str], tuple[str, str]]:
    connection = sqlite3.connect(":memory:")
    try:
        try:
            connection.executescript(canonical_schema_sql())
        except sqlite3.DatabaseError as error:
            fail(
                "installation_error",
                "Installed SQLite schema is not valid SQL",
                EXIT_ENVIRONMENT,
                {
                    "schema": str(schema_path()),
                    "reason": type(error).__name__,
                },
            )
        details = schema_details(connection)
        if (
            details["schema_version"] != SCHEMA_VERSION
            or details["metadata_schema_version"] != str(SCHEMA_VERSION)
            or details["tables"] != REQUIRED_TABLES
            or any(
                required - details["columns"].get(table, set())
                for table, required in REQUIRED_COLUMNS.items()
            )
            or details["indexes"] != REQUIRED_INDEXES
            or details["triggers"] != REQUIRED_TRIGGERS
            or details["views"]
        ):
            fail(
                "installation_error",
                "Installed SQLite schema does not define the canonical v1 object set",
                EXIT_ENVIRONMENT,
                {"schema": str(schema_path())},
            )
        return dict(details["definitions"])
    finally:
        connection.close()


def ensure_supported_schema(connection: sqlite3.Connection) -> dict[str, Any]:
    details = schema_details(connection)
    version = details["schema_version"]
    if version != SCHEMA_VERSION:
        fail(
            "unsupported_schema",
            (
                f"Database schema {version} is unsupported; "
                f"this runtime supports schema {SCHEMA_VERSION}"
            ),
            EXIT_ENVIRONMENT,
            {"database_schema": version, "supported_schema": SCHEMA_VERSION},
        )
    missing_tables = sorted(REQUIRED_TABLES - details["tables"])
    if missing_tables:
        fail(
            "incomplete_schema",
            "Database schema is missing required tables",
            EXIT_ENVIRONMENT,
            {"missing_tables": missing_tables},
        )
    missing_columns = {
        table: sorted(required - details["columns"].get(table, set()))
        for table, required in REQUIRED_COLUMNS.items()
        if required - details["columns"].get(table, set())
    }
    missing_indexes = sorted(REQUIRED_INDEXES - details["indexes"])
    missing_triggers = sorted(REQUIRED_TRIGGERS - details["triggers"])
    if missing_columns or missing_indexes or missing_triggers:
        problems: dict[str, Any] = {}
        if missing_columns:
            problems["missing_columns"] = missing_columns
        if missing_indexes:
            problems["missing_indexes"] = missing_indexes
        if missing_triggers:
            problems["missing_triggers"] = missing_triggers
        fail(
            "incomplete_schema",
            "Database schema is missing required objects",
            EXIT_ENVIRONMENT,
            problems,
        )
    if details["metadata_schema_version"] != str(SCHEMA_VERSION):
        fail(
            "schema_mismatch",
            "Database metadata does not match PRAGMA user_version",
            EXIT_ENVIRONMENT,
            {
                "database_schema": version,
                "metadata_schema": details["metadata_schema_version"],
            },
        )
    expected_definitions = expected_schema_definitions()
    unexpected_objects = [
        {"type": object_type, "name": name}
        for object_type, name in sorted(
            set(details["definitions"]) - set(expected_definitions)
        )
    ]
    mismatched_objects = [
        {"type": object_type, "name": name}
        for (object_type, name), expected in sorted(expected_definitions.items())
        if details["definitions"].get((object_type, name)) != expected
    ]
    if mismatched_objects or unexpected_objects:
        fail(
            "schema_definition_mismatch",
            "Database schema object definitions do not match the supported schema",
            EXIT_ENVIRONMENT,
            {
                "mismatched_objects": mismatched_objects,
                "unexpected_objects": unexpected_objects,
            },
        )
    return details


def connect(
    path: Path,
    require_initialized: bool = True,
    *,
    configure_journal: bool = True,
) -> sqlite3.Connection:
    if require_initialized and not path.is_file():
        fail(
            "database_not_found",
            f"Coordination database not found: {path}",
            EXIT_NOT_FOUND,
        )
    validate_database_operational_files(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = configured_busy_timeout_ms()
    handle = _acquire_file_lock(
        database_lock_path(path),
        exclusive=False,
        timeout_ms=timeout_ms,
    )
    try:
        validate_database_operational_files(path)
        connection = sqlite3.connect(path, timeout=timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
        if require_initialized:
            ensure_supported_schema(connection)
            if configure_journal:
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
                ).lower()
                if journal_mode != "wal":
                    fail(
                        "database_configuration_error",
                        "Coordination database must use WAL journal mode",
                        EXIT_ENVIRONMENT,
                        {"journal_mode": journal_mode},
                    )
        connection.execute("PRAGMA synchronous = FULL")
        synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])
        if synchronous != 2:
            fail(
                "database_configuration_error",
                "Coordination database must use FULL synchronous durability",
                EXIT_ENVIRONMENT,
                {"synchronous": synchronous},
            )
    except BaseException:
        try:
            connection.close()
        except UnboundLocalError:
            pass
        _release_file_lock(handle)
        raise
    _CONNECTION_LOCKS[id(connection)] = handle
    return connection


def connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        fail(
            "database_not_found",
            f"Coordination database not found: {path}",
            EXIT_NOT_FOUND,
        )
    validate_database_operational_files(path)
    timeout_ms = configured_busy_timeout_ms()
    handle = _acquire_file_lock(
        database_lock_path(path),
        exclusive=False,
        timeout_ms=timeout_ms,
    )
    try:
        validate_database_operational_files(path)
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro",
            timeout=timeout_ms / 1000,
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
        ensure_supported_schema(connection)
    except BaseException:
        try:
            connection.close()
        except UnboundLocalError:
            pass
        _release_file_lock(handle)
        raise
    _CONNECTION_LOCKS[id(connection)] = handle
    return connection


def check_database_integrity(connection: sqlite3.Connection) -> dict[str, str]:
    integrity_results: list[str] = []
    integrity_result_count = 0
    for row in connection.execute("PRAGMA integrity_check"):
        integrity_result_count += 1
        if len(integrity_results) < 10:
            integrity_results.append(str(row[0]))
    if integrity_results != ["ok"]:
        fail(
            "database_corrupt",
            "SQLite integrity check failed",
            EXIT_ENVIRONMENT,
            {
                "integrity_check": integrity_results,
                "result_count": integrity_result_count,
                "truncated": integrity_result_count > len(integrity_results),
            },
        )
    foreign_key_violations: list[dict[str, Any]] = []
    foreign_key_violation_count = 0
    for row in connection.execute("PRAGMA foreign_key_check"):
        foreign_key_violation_count += 1
        if len(foreign_key_violations) < 10:
            foreign_key_violations.append(dict(row))
    if foreign_key_violation_count:
        fail(
            "foreign_key_violation",
            "SQLite foreign-key consistency check failed",
            EXIT_ENVIRONMENT,
            {
                "violation_count": foreign_key_violation_count,
                "violations": foreign_key_violations,
                "truncated": (
                    foreign_key_violation_count > len(foreign_key_violations)
                ),
            },
        )
    return {"integrity_check": "ok", "foreign_key_check": "ok"}


def check_coordination_invariants(connection: sqlite3.Connection) -> dict[str, str]:
    truncated_sections: list[str] = []

    def bounded_ids(name: str, query: str) -> list[str]:
        values = [
            str(row[0])
            for row in connection.execute(
                query + " LIMIT ?",
                (MAX_DIAGNOSTIC_FINDINGS + 1,),
            )
        ]
        if len(values) > MAX_DIAGNOSTIC_FINDINGS:
            truncated_sections.append(name)
        return values[:MAX_DIAGNOSTIC_FINDINGS]

    def bounded_rows(name: str, query: str) -> list[dict[str, Any]]:
        values = rows(
            connection.execute(
                query + " LIMIT ?",
                (MAX_DIAGNOSTIC_FINDINGS + 1,),
            )
        )
        if len(values) > MAX_DIAGNOSTIC_FINDINGS:
            truncated_sections.append(name)
        return values[:MAX_DIAGNOSTIC_FINDINGS]

    unclaimed = bounded_ids(
        "unclaimed_in_progress_tasks",
        """SELECT t.id FROM tasks t
           WHERE t.status = 'in_progress'
             AND NOT EXISTS (
               SELECT 1 FROM task_claims c WHERE c.task_id = t.id
             )
           ORDER BY t.id""",
    )
    invalid_claims = bounded_rows(
        "invalid_active_claims",
        """SELECT c.task_id, c.agent_id, c.session_id,
                  t.status AS task_status,
                  s.status AS session_status,
                  s.agent_id AS session_agent_id,
                  a.status AS agent_status
           FROM task_claims c
           JOIN tasks t ON t.id = c.task_id
           JOIN agent_sessions s ON s.id = c.session_id
           JOIN agents a ON a.id = c.agent_id
           WHERE t.status <> 'in_progress'
              OR s.status <> 'active'
              OR s.agent_id <> c.agent_id
              OR a.status <> 'active'
           ORDER BY c.task_id""",
    )
    done_without_evidence = bounded_ids(
        "done_without_evidence",
        """SELECT t.id FROM tasks t
           WHERE t.status = 'done'
             AND NOT EXISTS (
               SELECT 1 FROM task_evidence e WHERE e.task_id = t.id
             )
           ORDER BY t.id""",
    )
    invalid_sessions = bounded_rows(
        "invalid_sessions",
        """SELECT s.id, s.agent_id, s.status, s.ended_at,
                  a.status AS agent_status
           FROM agent_sessions s
           JOIN agents a ON a.id = s.agent_id
           WHERE (s.status = 'active' AND (
                    s.ended_at IS NOT NULL OR a.status <> 'active'
                 ))
              OR (s.status = 'ended' AND s.ended_at IS NULL)
           ORDER BY s.id""",
    )
    if unclaimed or invalid_claims or done_without_evidence or invalid_sessions:
        fail(
            "coordination_invariant_violation",
            "Coordination state invariants failed",
            EXIT_ENVIRONMENT,
            {
                "unclaimed_in_progress_tasks": unclaimed,
                "invalid_active_claims": invalid_claims,
                "done_without_evidence": done_without_evidence,
                "invalid_sessions": invalid_sessions,
                "truncated_sections": truncated_sections,
            },
        )
    return {"coordination_invariants": "ok"}


@contextmanager
def transaction(connection: sqlite3.Connection) -> Generator[None, None, None]:
    """Run a short write transaction that acquires SQLite's writer lock first."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


@contextmanager
def read_transaction(connection: sqlite3.Connection) -> Generator[None, None, None]:
    """Keep multi-statement reports on one coherent SQLite snapshot."""
    connection.execute("BEGIN")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def audit(
    connection: sqlite3.Connection,
    actor: str | None,
    action: str,
    object_type: str,
    object_id: str,
    detail: str = "",
    session_id: str | None = None,
) -> int:
    stamp = now()
    require_active_actor(connection, actor)
    if session_id:
        require_active_session(connection, session_id, actor)
        connection.execute(
            "UPDATE agent_sessions SET last_seen_at = ? WHERE id = ?",
            (stamp, session_id),
        )
    cursor = connection.execute(
        """INSERT INTO audit_log(
             actor, session_id, action, object_type, object_id, detail, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (actor, session_id, action, object_type, object_id, detail, stamp),
    )
    return int(cursor.lastrowid)


def require_active_actor(
    connection: sqlite3.Connection,
    actor: str | None,
) -> sqlite3.Row:
    if not actor:
        fail(
            "invalid_actor",
            "A mutation requires an accountable actor",
            EXIT_USAGE,
        )
    value = connection.execute(
        "SELECT id, status FROM agents WHERE id = ?",
        (actor,),
    ).fetchone()
    if value is None:
        fail(
            "not_found",
            f"Not found: agent {actor}",
            EXIT_NOT_FOUND,
            {"resource": f"agent {actor}"},
        )
    if value["status"] != "active":
        fail(
            "inactive_actor",
            f"Agent {actor} is not active",
            EXIT_CONFLICT,
            {"actor": actor},
        )
    return value


def require_active_session(
    connection: sqlite3.Connection,
    session_id: str,
    actor: str | None,
) -> sqlite3.Row:
    if not actor:
        fail(
            "invalid_actor",
            "A session-aware mutation requires an actor",
            EXIT_USAGE,
        )
    session = require_row(
        connection,
        """SELECT s.agent_id, s.status, a.status AS agent_status
           FROM agent_sessions s
           JOIN agents a ON a.id = s.agent_id
           WHERE s.id = ?""",
        (session_id,),
        f"agent session {session_id}",
    )
    if session["agent_id"] != actor:
        fail(
            "session_actor_mismatch",
            f"Session {session_id} belongs to {session['agent_id']}, not actor {actor}",
            EXIT_CONFLICT,
        )
    if session["status"] != "active":
        fail(
            "inactive_session",
            f"Agent session {session_id} is not active",
            EXIT_CONFLICT,
        )
    if session["agent_status"] != "active":
        fail(
            "inactive_actor",
            f"Agent {actor} is not active",
            EXIT_CONFLICT,
            {"actor": actor},
        )
    return session


def require_row(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...],
    label: str,
) -> sqlite3.Row:
    value = connection.execute(query, parameters).fetchone()
    if value is None:
        fail("not_found", f"Not found: {label}", EXIT_NOT_FOUND, {"resource": label})
    return value
