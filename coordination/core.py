"""Shared database, discovery, audit, and output infrastructure.

This module is the stable import surface for the runtime; the implementation
lives in the sibling `coordination._*` modules, each within the 250-line file
budget. Every name re-exported here is public API for the transports, the
service, and the entity modules.
"""

from __future__ import annotations


# fmt: off
# isort: off
from coordination._config import (
    _project_database_from_config as _project_database_from_config,
)
from coordination._connections import (
    check_coordination_invariants as check_coordination_invariants,
    check_database_integrity as check_database_integrity, connect as connect,
    connect_read_only as connect_read_only,
)
from coordination._db_helpers import (
    audit as audit, read_transaction as read_transaction,
    require_active_actor as require_active_actor,
    require_active_session as require_active_session, require_row as require_row,
    resolve_reference as resolve_reference, transaction as transaction,
)
from coordination._discovery import (
    canonical_schema_sql as canonical_schema_sql, discover_db as discover_db,
    runtime_root as runtime_root, runtime_version as runtime_version,
    schema_path as schema_path,
)
from coordination._guards import (
    protected_coordination_metadata_paths as protected_coordination_metadata_paths,
    validate_enclosing_configured_database_namespace as validate_enclosing_configured_database_namespace,  # noqa: E501
    validate_external_path as validate_external_path,
    validate_not_managed_metadata as validate_not_managed_metadata,
    validate_output_path as validate_output_path,
    validate_restore_target_path as validate_restore_target_path,
)
from coordination._locking import (
    _acquire_file_lock as _acquire_file_lock,
    _CONNECTION_LOCKS as _CONNECTION_LOCKS, _OPEN_CONNECTIONS as _OPEN_CONNECTIONS,
    _release_file_lock as _release_file_lock,
    _track_connection as _track_connection,
    advisory_file_lock as advisory_file_lock, close_connection as close_connection,
    configured_busy_timeout_ms as configured_busy_timeout_ms,
    connection_scope as connection_scope, current_scope as current_scope,
    database_lock_path as database_lock_path, OperationScope as OperationScope,
    output_lock_path as output_lock_path,
)
from coordination._output import (
    emit as emit,
    operation_log_sink_from_environment as operation_log_sink_from_environment,
    publish_temporary_file as publish_temporary_file, rows as rows,
)
from coordination._paths import (
    coordination_root_for_database as coordination_root_for_database,
    expand_user_path as expand_user_path, fsync_directory as fsync_directory,
    fsync_file as fsync_file, operational_path as operational_path,
    paths_refer_to_same_file as paths_refer_to_same_file,
    protected_database_paths as protected_database_paths,
    validate_contained_path as validate_contained_path,
    validate_database_namespaces_disjoint as validate_database_namespaces_disjoint,
    validate_database_operational_files as validate_database_operational_files,
)
from coordination._primitives import (
    DEFAULT_BUSY_TIMEOUT_MS as DEFAULT_BUSY_TIMEOUT_MS,
    DEFAULT_LIST_LIMIT as DEFAULT_LIST_LIMIT,
    IDENTIFIER_PATTERN as IDENTIFIER_PATTERN, MAX_AUDIT_CURSOR as MAX_AUDIT_CURSOR,
    MAX_BUSY_TIMEOUT_MS as MAX_BUSY_TIMEOUT_MS,
    MAX_DIAGNOSTIC_FINDINGS as MAX_DIAGNOSTIC_FINDINGS,
    MAX_IDENTIFIER_ARRAY_ITEMS as MAX_IDENTIFIER_ARRAY_ITEMS,
    MAX_IDENTIFIER_LENGTH as MAX_IDENTIFIER_LENGTH,
    MAX_LIST_LIMIT as MAX_LIST_LIMIT, MAX_PATH_LENGTH as MAX_PATH_LENGTH,
    MAX_STALE_DAYS as MAX_STALE_DAYS, MAX_STALE_SECONDS as MAX_STALE_SECONDS,
    MAX_STALE_SESSION_MINUTES as MAX_STALE_SESSION_MINUTES,
    MAX_TEXT_LENGTH as MAX_TEXT_LENGTH, MIN_STALE_SECONDS as MIN_STALE_SECONDS,
    now as now, Params as Params, SCHEMA_VERSION as SCHEMA_VERSION,
    SESSION_LEASE_SECONDS as SESSION_LEASE_SECONDS,
)
from coordination._schema import (
    ensure_supported_schema as ensure_supported_schema,
    expected_schema_definitions as expected_schema_definitions,
    schema_details as schema_details,
)
from coordination._schema_objects import (
    REQUIRED_COLUMNS as REQUIRED_COLUMNS, REQUIRED_INDEXES as REQUIRED_INDEXES,
    REQUIRED_TABLES as REQUIRED_TABLES, REQUIRED_TRIGGERS as REQUIRED_TRIGGERS,
)
from coordination._validators import (
    _bounded_integer as _bounded_integer, audit_cursor as audit_cursor,
    because_reference as because_reference, BECAUSE_TABLES as BECAUSE_TABLES,
    identifier as identifier, list_limit as list_limit, list_offset as list_offset,
    optional_text as optional_text, path_argument as path_argument,
    positive_revision as positive_revision, require_unique as require_unique,
    required_text as required_text, stale_days as stale_days,
    stale_seconds as stale_seconds, stale_session_minutes as stale_session_minutes,
    tag_token as tag_token,
)
from coordination.errors import (
    CoordinationError as CoordinationError, EXIT_BUSY as EXIT_BUSY,
    EXIT_CONFLICT as EXIT_CONFLICT, EXIT_ENVIRONMENT as EXIT_ENVIRONMENT,
    EXIT_INTERNAL as EXIT_INTERNAL, EXIT_NOT_FOUND as EXIT_NOT_FOUND,
    EXIT_USAGE as EXIT_USAGE, fail as fail,
)
# isort: on
# fmt: on
