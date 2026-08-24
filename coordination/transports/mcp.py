"""Optional local stdio MCP transport for canonical coordination services."""

from __future__ import annotations


# fmt: off
# isort: off
import argparse
import signal
from typing import Any, NoReturn
from mcp.server.fastmcp import FastMCP
from coordination.core import (
    operation_log_sink_from_environment,
    path_argument,
)
from coordination.errors import (
    EXIT_USAGE,
    CoordinationError,
    emit_error,
)
from coordination.service import OperationLog
from coordination.transports import (
    _mcp_agent_tools, _mcp_artifact_tools, _mcp_collab_tools,
    _mcp_decision_tools, _mcp_maintenance_tools, _mcp_read_tools,
    _mcp_shared, _mcp_task_tools,
)
from coordination.transports._mcp_shared import (
    _require_confirmation as _require_confirmation, _tool_result as _tool_result,
)
from coordination.transports._mcp_types import (
    ActorType as ActorType, AgentStatus as AgentStatus,
    ArtifactStatus as ArtifactStatus, DecisionStatus as DecisionStatus,
    DependencyType as DependencyType, EscalationResolution as EscalationResolution,
    EscalationStatus as EscalationStatus, HealthSection as HealthSection,
    HistoryObjectType as HistoryObjectType, IdentifierArray as IdentifierArray,
    ReleaseStatus as ReleaseStatus, ReviewDecision as ReviewDecision,
    ShowObjectType as ShowObjectType, SummarySection as SummarySection,
    TaskStatus as TaskStatus,
)
# isort: on
# fmt: on


def build_server(
    *,
    db: str | None = None,
    operation_log: OperationLog | None = None,
) -> FastMCP:
    """Build the fixed stdio-only MCP server for one project database."""
    _mcp_shared._OPERATION_LOG = operation_log
    server = FastMCP(
        "Harness-neutral SQLite coordination",
        instructions=(
            "Use explicit durable actor IDs and execution-session IDs. "
            "Harness and model identify sessions, never actors. All tools use "
            "the same canonical SQLite coordination services as the CLI."
        ),
        json_response=True,
    )
    for module in (
        _mcp_read_tools,
        _mcp_agent_tools,
        _mcp_task_tools,
        _mcp_collab_tools,
        _mcp_decision_tools,
        _mcp_artifact_tools,
        _mcp_maintenance_tools,
    ):
        module.register(server, db)
    return server


class MCPArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> NoReturn:
        # Every other failure path in this project reports a JSON envelope, so
        # a launcher argument error must not fall back to argparse's prose.
        raise CoordinationError("invalid_arguments", message, EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    parser = MCPArgumentParser(
        prog="coordination-mcp",
        description="Local stdio MCP transport for SQLite coordination",
    )
    parser.add_argument(
        "--db",
        type=path_argument,
        help="SQLite coordination database; otherwise discover from the server cwd",
    )
    try:
        args = parser.parse_args(argv)
    except CoordinationError as error:
        emit_error(error)
        return error.exit_code
    # A long-lived server is the process most likely to be SIGTERMed -- by the
    # client on shutdown, by the host on reboot. Python's default handler
    # terminates without unwinding, so an in-flight backup's `finally` never
    # ran and its staging file was orphaned. Map the termination signals to an
    # interrupt so the stack unwinds: transactions roll back, staging files
    # are removed, and the server exits cleanly.
    for signal_name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), _interrupt)
    try:
        operation_log = operation_log_sink_from_environment(default="stderr")
    except CoordinationError as error:
        emit_error(error)
        return error.exit_code
    try:
        build_server(db=args.db, operation_log=operation_log).run(transport="stdio")
    except KeyboardInterrupt:
        return 0
    return 0


def _interrupt(signum: int, _frame: object) -> None:
    raise KeyboardInterrupt(signum)


if __name__ == "__main__":
    raise SystemExit(main())
