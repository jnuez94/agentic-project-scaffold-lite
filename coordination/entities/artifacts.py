"""Artifact entity commands."""

from __future__ import annotations


# fmt: off
# isort: off
from coordination.entities._artifacts_read import (
    ARTIFACT_STATUSES as ARTIFACT_STATUSES, list_artifacts as list_artifacts,
    shape_artifacts as shape_artifacts, show as show,
)
from coordination.entities._artifacts_write import (
    add as add, require_expected_status as require_expected_status,
    status as status, update as update,
)
import argparse
from coordination.core import (
    DEFAULT_LIST_LIMIT,
    because_reference,
    identifier,
    list_limit,
    list_offset,
    optional_text,
    required_text,
)
from coordination.entities.audit import register_history
from coordination.entities.descriptors import (
    ARTIFACTS,
    add_query_arguments,
)
# isort: on
# fmt: on


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    artifact = commands.add_parser("artifact", help="Manage artifacts").add_subparsers(
        dest="artifact_command",
        required=True,
    )
    add_parser = artifact.add_parser("add")
    add_parser.add_argument("--id", required=True, type=identifier)
    add_parser.add_argument("--uri", required=True, type=required_text)
    add_parser.add_argument("--owner", required=True, type=identifier)
    add_parser.add_argument("--type", required=True, type=required_text)
    add_parser.add_argument("--status", choices=ARTIFACT_STATUSES, default="draft")
    add_parser.add_argument("--usage-boundaries", default="", type=optional_text)
    add_parser.add_argument("--task", action="append", default=[], type=identifier)
    add_parser.add_argument(
        "--reviewer",
        action="append",
        default=[],
        type=identifier,
    )
    add_parser.set_defaults(func=add)

    list_parser = artifact.add_parser("list")
    list_parser.add_argument("--status", choices=ARTIFACT_STATUSES)
    add_query_arguments(list_parser, ARTIFACTS)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_artifacts)

    status_parser = artifact.add_parser("status")
    status_parser.add_argument("id", type=identifier)
    status_parser.add_argument("status", choices=ARTIFACT_STATUSES)
    status_parser.add_argument("--actor", required=True, type=identifier)
    status_parser.add_argument(
        "--if-status",
        choices=ARTIFACT_STATUSES,
        help="Only change the status if it is currently this value",
    )
    status_parser.add_argument(
        "--because",
        type=because_reference,
        help="Record the review, decision, or message (TYPE:ID) that caused this",
    )
    status_parser.set_defaults(func=status)

    update_parser = artifact.add_parser("update")
    update_parser.add_argument("id", type=identifier)
    update_parser.add_argument("--uri", type=required_text)
    update_parser.add_argument("--type", type=required_text)
    update_parser.add_argument("--usage-boundaries", type=optional_text)
    update_parser.add_argument("--actor", required=True, type=identifier)
    update_parser.add_argument(
        "--if-status",
        choices=ARTIFACT_STATUSES,
        help="Only update if the status is currently this value",
    )
    update_parser.set_defaults(func=update)
    show_parser = artifact.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)
    register_history(artifact, "artifact")
