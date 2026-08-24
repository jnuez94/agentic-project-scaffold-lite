"""Agent execution-session commands."""

from __future__ import annotations


# fmt: off
# isort: off
from coordination.entities._sessions_lifecycle import (
    end as end, heartbeat as heartbeat, list_sessions as list_sessions,
    require_open_session as require_open_session,
    SESSION_STATUSES as SESSION_STATUSES, show as show,
    stale_cutoff as stale_cutoff, start as start,
)
from coordination.entities._sessions_recovery import (
    recover as recover, recover_session_claims as recover_session_claims,
    sweep as sweep,
)
import argparse
from coordination.core import (
    DEFAULT_LIST_LIMIT,
    MIN_STALE_SECONDS,
    identifier,
    list_limit,
    list_offset,
    optional_text,
    required_text,
    stale_seconds,
)
from coordination.entities.audit import register_history
from coordination.entities.descriptors import (
    SESSIONS,
    add_query_arguments,
)
# isort: on
# fmt: on


def register(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    session = commands.add_parser(
        "session",
        help="Manage agent execution sessions",
    ).add_subparsers(dest="session_command", required=True)

    start_parser = session.add_parser("start")
    start_parser.add_argument("--id", required=True, type=identifier)
    start_parser.add_argument("--agent", required=True, type=identifier)
    start_parser.add_argument("--harness", required=True, type=required_text)
    start_parser.add_argument("--model", default="", type=optional_text)
    start_parser.set_defaults(func=start)

    list_parser = session.add_parser("list")
    list_parser.add_argument("--agent", type=identifier)
    list_parser.add_argument("--status", choices=SESSION_STATUSES)
    list_parser.add_argument("--harness", type=required_text)
    add_query_arguments(list_parser, SESSIONS)
    list_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    list_parser.add_argument("--offset", type=list_offset, default=0)
    list_parser.set_defaults(func=list_sessions)

    heartbeat_parser = session.add_parser("heartbeat")
    heartbeat_parser.add_argument("id", type=identifier)
    heartbeat_parser.set_defaults(func=heartbeat)

    end_parser = session.add_parser("end")
    end_parser.add_argument("id", type=identifier)
    end_parser.set_defaults(func=end)

    recover_parser = session.add_parser(
        "recover",
        help="End a stale session and block its claimed tasks",
    )
    recover_parser.add_argument("id", type=identifier)
    recover_parser.add_argument("--actor", required=True, type=identifier)
    recover_parser.add_argument("--reason", required=True, type=required_text)
    recover_parser.add_argument(
        "--stale-after-seconds",
        type=stale_seconds,
        default=3600,
        help=(
            "Seconds of silence before a session counts as stale"
            f" (minimum {MIN_STALE_SECONDS})"
        ),
    )
    recover_parser.add_argument(
        "--force",
        action="store_true",
        help="Recover even if the session is not stale; audited as forced",
    )
    recover_parser.set_defaults(func=recover)

    sweep_parser = session.add_parser(
        "sweep",
        help="Recover every active session silent past the stale threshold",
    )
    sweep_parser.add_argument("--actor", required=True, type=identifier)
    sweep_parser.add_argument("--reason", required=True, type=required_text)
    sweep_parser.add_argument(
        "--stale-after-seconds",
        type=stale_seconds,
        default=3600,
    )
    sweep_parser.add_argument("--limit", type=list_limit, default=DEFAULT_LIST_LIMIT)
    sweep_parser.set_defaults(func=sweep)
    show_parser = session.add_parser("show")
    show_parser.add_argument("id", type=identifier)
    show_parser.set_defaults(func=show)
    register_history(session, "session")
