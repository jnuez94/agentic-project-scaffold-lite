"""Task entity commands and shared task query."""

from __future__ import annotations


# fmt: off
# isort: off
from coordination.entities._tasks_shared import (
    reject_stale_revision as reject_stale_revision,
    require_claim_ownership as require_claim_ownership, shape_tasks as shape_tasks,
    STATUS_TRANSITIONS as STATUS_TRANSITIONS, STATUSES as STATUSES,
    task_query as task_query,
)
from coordination.entities._tasks_read import (
    list_tasks as list_tasks, show as show,
)
from coordination.entities._tasks_write import (
    create as create, update as update,
)
from coordination.entities._tasks_assign import (
    assign as assign,
)
from coordination.entities._tasks_claim import (
    claim as claim,
)
from coordination.entities._tasks_status import (
    status as status,
)
import argparse
from coordination.core import (
    DEFAULT_LIST_LIMIT,
    because_reference,
    identifier,
    list_limit,
    list_offset,
    optional_text,
    positive_revision,
    required_text,
    tag_token,
)
from coordination.entities.audit import register_history
from coordination.entities.descriptors import TASKS, add_query_arguments
# isort: on
# fmt: on


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    task = commands.add_parser("task", help="Manage tasks").add_subparsers(
        dest="task_command",
        required=True,
    )
    create_parser = task.add_parser("create")
    create_parser.add_argument("--id", required=True, type=identifier)
    create_parser.add_argument("--title", required=True, type=required_text)
    create_parser.add_argument("--description", default="", type=optional_text)
    create_parser.add_argument("--priority", type=int, choices=range(1, 6), default=3)
    create_parser.add_argument("--tags", default="", type=optional_text)
    create_parser.add_argument("--acceptance", default="", type=optional_text)
    create_parser.add_argument("--next-steps", default="", type=optional_text)
    create_parser.add_argument("--blocked-claims", default="", type=optional_text)
    create_parser.add_argument("--actor", required=True, type=identifier)
    create_parser.add_argument(
        "--assignee",
        action="append",
        default=[],
        type=identifier,
    )
    create_parser.set_defaults(func=create)

    list_parser = task.add_parser("list")
    list_parser.add_argument(
        "--status",
        choices=STATUSES,
        action="append",
        help="Repeatable; tasks in any of the given statuses",
    )
    list_parser.add_argument("--assignee", type=identifier)
    list_parser.add_argument(
        "--tag",
        type=tag_token,
        help="Tasks whose comma-separated tags contain this token",
    )
    add_query_arguments(list_parser, TASKS)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_tasks)

    show_parser = task.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)

    assign_parser = task.add_parser("assign")
    assign_parser.add_argument("id", type=identifier)
    assign_parser.add_argument("--actor", required=True, type=identifier)
    assign_parser.add_argument("--add", action="append", default=[], type=identifier)
    assign_parser.add_argument(
        "--remove",
        action="append",
        default=[],
        type=identifier,
    )
    assign_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    assign_parser.set_defaults(func=assign)

    update_parser = task.add_parser("update")
    update_parser.add_argument("id", type=identifier)
    update_parser.add_argument("--actor", required=True, type=identifier)
    update_parser.add_argument("--title", type=required_text)
    update_parser.add_argument("--description", type=optional_text)
    update_parser.add_argument("--priority", type=int, choices=range(1, 6))
    update_parser.add_argument("--tags", type=optional_text)
    update_parser.add_argument("--acceptance", type=optional_text)
    update_parser.add_argument("--next-steps", type=optional_text)
    update_parser.add_argument("--blocked-claims", type=optional_text)
    update_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    update_parser.set_defaults(func=update)

    claim_parser = task.add_parser("claim")
    claim_parser.add_argument("id", type=identifier)
    claim_parser.add_argument("--agent", required=True, type=identifier)
    claim_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    claim_parser.set_defaults(func=claim)

    status_parser = task.add_parser("status")
    status_parser.add_argument("id", type=identifier)
    status_parser.add_argument("status", choices=STATUSES)
    status_parser.add_argument("--actor", required=True, type=identifier)
    status_parser.add_argument("--note", default="", type=optional_text)
    status_parser.add_argument(
        "--because",
        type=because_reference,
        help="Record the review, decision, or message (TYPE:ID) that caused this",
    )
    status_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    status_parser.set_defaults(func=status, require_owned_claim=False)

    release_parser = task.add_parser(
        "release",
        help="Release the active claim and move the task out of in_progress",
    )
    release_parser.add_argument("id", type=identifier)
    release_parser.add_argument(
        "--to",
        dest="status",
        choices=("todo", "review", "blocked"),
        required=True,
    )
    release_parser.add_argument("--actor", required=True, type=identifier)
    release_parser.add_argument("--note", default="", type=optional_text)
    release_parser.add_argument(
        "--because",
        type=because_reference,
        help="Record the review, decision, or message (TYPE:ID) that caused this",
    )
    release_parser.add_argument(
        "--if-revision",
        required=True,
        type=positive_revision,
    )
    release_parser.set_defaults(func=status, require_owned_claim=True)
    register_history(task, "task")
