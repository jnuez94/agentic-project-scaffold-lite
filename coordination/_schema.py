"""Schema identity verification against the canonical inventory."""

from __future__ import annotations

from functools import lru_cache
import sqlite3
from typing import Any

from coordination._discovery import canonical_schema_sql, schema_path
from coordination._primitives import SCHEMA_VERSION
from coordination._schema_objects import (
    REQUIRED_COLUMNS,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    REQUIRED_TRIGGERS,
)
from coordination.errors import EXIT_ENVIRONMENT, fail


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
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
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
                "Installed SQLite schema does not define the canonical object set",
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
        message = (
            f"Database schema {version} is unsupported; "
            f"this runtime supports schema {SCHEMA_VERSION}"
        )
        if version == 1:
            message += "; run 'coordination migrate' to upgrade this database"
        fail(
            "unsupported_schema",
            message,
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
