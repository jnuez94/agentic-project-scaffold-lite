"""Protections for managed coordination state against aliasing outputs."""

from __future__ import annotations

from pathlib import Path

from coordination._config import _project_database_from_config
from coordination._locking import output_lock_path
from coordination._paths import paths_refer_to_same_file, protected_database_paths
from coordination.errors import EXIT_USAGE, fail


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
                f"{label} must not alias the coordination database "
                "or its operational files",
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
