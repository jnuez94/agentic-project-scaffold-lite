"""The strict parser for `.coordination/config.yml`."""

from __future__ import annotations

from pathlib import Path
import re

from coordination._paths import paths_refer_to_same_file
from coordination._primitives import MAX_PATH_LENGTH
from coordination.errors import EXIT_ENVIRONMENT, fail


def _read_config_settings(config: Path) -> dict[str, str]:
    """Parse the flat key/value lines, rejecting malformed and duplicate keys."""
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
    return settings


def _required_database_value(config: Path, settings: dict[str, str]) -> str:
    """Require version 1, the sqlite backend, and a plausible database value."""
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
    return database_value


def _validated_relative_path(config: Path, database_value: str) -> Path:
    """Reject absolute, parent-aliasing, and reserved relative database paths."""
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
    return relative


def _reject_symlinked_components(
    config: Path,
    coordination: Path,
    relative: Path,
    database_value: str,
) -> None:
    """Walk each existing component, rejecting symlinks and wrong node types."""
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


def _validated_resolved_database(
    config: Path,
    coordination: Path,
    relative: Path,
    database_value: str,
) -> Path:
    """Resolve the path and require containment, file identity, and no aliases."""
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


def _project_database_from_config(config: Path) -> Path:
    """Validate the configured database path for the nearest project."""
    settings = _read_config_settings(config)
    database_value = _required_database_value(config, settings)
    relative = _validated_relative_path(config, database_value)
    coordination = config.parent.resolve()
    _reject_symlinked_components(config, coordination, relative, database_value)
    return _validated_resolved_database(config, coordination, relative, database_value)
