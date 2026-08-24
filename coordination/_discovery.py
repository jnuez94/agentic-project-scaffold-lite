"""Database discovery and the canonical runtime layout."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from coordination._config import _project_database_from_config
from coordination._guards import (
    validate_enclosing_configured_database_namespace,
    validate_not_managed_metadata,
)
from coordination._paths import expand_user_path
from coordination.errors import EXIT_ENVIRONMENT, EXIT_USAGE, fail


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
    if (
        re.fullmatch(
            r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
            r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
            value,
        )
        is None
    ):
        fail(
            "installation_error",
            "Installed VERSION is not valid semantic version text",
            EXIT_ENVIRONMENT,
            {"version_file": str(version)},
        )
    return value
