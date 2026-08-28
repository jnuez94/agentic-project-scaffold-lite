"""Verified, failure-atomic backup and restore operations."""

from __future__ import annotations


# fmt: off
# isort: off
from coordination.entities._maintenance_backup import (
    _atomic_raw_copy as _atomic_raw_copy, _raw_connection as _raw_connection,
    _write_verified_copy as _write_verified_copy, atomic_backup as atomic_backup,
    backup as backup, preserve_unhealthy_target as preserve_unhealthy_target,
)
from coordination.entities._maintenance_restore_support import (
    _active_target_sessions as _active_target_sessions,
    _prepare_restore as _prepare_restore,
    _restore_safety_directory as _restore_safety_directory,
    _rollback_published_restore as _rollback_published_restore,
    _safety_backup_path as _safety_backup_path,
)
from coordination.entities._maintenance_restore import (
    _restore_while_locked as _restore_while_locked,
)
from coordination.entities._maintenance_migrate import (
    _migrate_while_locked as _migrate_while_locked,
)
from coordination.entities._maintenance_archive import (
    archive as archive,
)
import argparse
from coordination.core import (
    advisory_file_lock,
    database_lock_path,
    discover_db,
    identifier,
    stale_days,
    operational_path,
    path_argument,
    paths_refer_to_same_file,
    validate_database_namespaces_disjoint,
    validate_database_operational_files,
    validate_enclosing_configured_database_namespace,
    validate_external_path,
    validate_not_managed_metadata,
    validate_restore_target_path,
)
from coordination.errors import (
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    fail,
)
# isort: on
# fmt: on


def restore(args: argparse.Namespace) -> dict[str, object]:
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
        return _restore_while_locked(args, target_path, source_path)


def migrate(args: argparse.Namespace) -> dict[str, object]:
    target_path = discover_db(args.db)
    if not target_path.is_file():
        fail(
            "not_found",
            f"Not found: database {target_path}",
            EXIT_NOT_FOUND,
            {"database": str(target_path)},
        )
    validate_database_operational_files(target_path)
    # The exclusive lock covers validation, backup, staging, and publication:
    # no canonical client may write to the database being transformed.
    with advisory_file_lock(database_lock_path(target_path), exclusive=True):
        return _migrate_while_locked(args, target_path)


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    backup_parser = commands.add_parser(
        "backup",
        help="Create and verify an atomic SQLite backup",
    )
    backup_parser.add_argument("--output", required=True, type=path_argument)
    backup_parser.add_argument("--force", action="store_true")
    backup_parser.add_argument(
        "--actor",
        type=identifier,
        help="Record the backup in the audit log, attributed to this actor",
    )
    backup_parser.set_defaults(func=backup)

    restore_parser = commands.add_parser(
        "restore",
        help="Restore a verified SQLite backup",
    )
    restore_parser.add_argument("--input", required=True, type=path_argument)
    restore_parser.add_argument("--actor", required=True, type=identifier)
    restore_parser.add_argument("--force", action="store_true")
    restore_parser.set_defaults(func=restore)

    migrate_parser = commands.add_parser(
        "migrate",
        help="Upgrade a schema-1 database to the current schema, with a backup",
    )
    migrate_parser.add_argument("--actor", required=True, type=identifier)
    migrate_parser.set_defaults(func=migrate)

    archive_parser = commands.add_parser(
        "archive",
        help="Move closed records past a cutoff into a verified archive database",
    )
    archive_parser.add_argument(
        "--older-than-days",
        dest="older_than_days",
        required=True,
        type=stale_days,
    )
    archive_parser.add_argument("--actor", required=True, type=identifier)
    archive_parser.add_argument("--force", action="store_true")
    archive_parser.set_defaults(func=archive)
