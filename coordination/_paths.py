"""Path identity, resolution, durability, and containment primitives."""

from __future__ import annotations

import errno
import os
from pathlib import Path

from coordination._locking import database_lock_path
from coordination.errors import (
    EXIT_ENVIRONMENT,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    fail,
)


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
        Path(f"{path}{suffix}") for suffix in ("", "-wal", "-shm", "-journal", ".lock")
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


def validate_contained_path(candidate: Path, root: Path, *, label: str) -> None:
    """Require a path to resolve inside the coordination root.

    The CLI may read and write wherever its operator points it; a transport
    driven by an agent must not. Containment is decided on resolved paths so
    `..` segments and symbolic links cannot escape the root.
    """
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        fail(
            "path_outside_coordination_root",
            f"{label} must stay inside the coordination root",
            EXIT_USAGE,
            {"path": str(candidate), "root": str(resolved_root)},
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
