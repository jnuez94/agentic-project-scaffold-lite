"""Success envelopes, published output files, and the operation-log sink."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from coordination._paths import fsync_directory, fsync_file
from coordination.errors import EXIT_CONFLICT, EXIT_ENVIRONMENT, fail


def emit(value: Any, *, audit_range: list[int] | None = None) -> None:
    envelope: dict[str, Any] = {"ok": True, "data": value}
    if audit_range is not None:
        envelope["audit_range"] = audit_range
    print(json.dumps(envelope, indent=2, sort_keys=True))


def operation_log_sink_from_environment(
    *,
    default: str,
) -> Callable[[dict[str, Any]], None] | None:
    """Resolve COORDINATION_LOG into an operation-log sink, or None.

    `stderr` writes one JSON object per line to standard error; `off` (or
    empty, `0`, `false`) disables the log. The log is observability, not a
    ledger: it never creates managed files and is the only place refused or
    failed operations, durations, and lock waits are visible.
    """
    raw = os.environ.get("COORDINATION_LOG", default).strip().lower()
    if raw in ("", "off", "0", "false", "none"):
        return None
    if raw == "stderr":

        def sink(record: dict[str, Any]) -> None:
            print(json.dumps(record, sort_keys=True), file=sys.stderr, flush=True)

        return sink
    fail(
        "configuration_error",
        "COORDINATION_LOG must be 'stderr' or 'off'",
        EXIT_ENVIRONMENT,
        {"value": raw},
    )


def rows(values: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(value) for value in values]


def publish_temporary_file(
    temporary: Path,
    destination: Path,
    *,
    force: bool,
) -> None:
    fsync_file(temporary)
    if force:
        os.replace(temporary, destination)
    else:
        try:
            os.link(temporary, destination)
        except FileExistsError:
            fail(
                "output_exists",
                f"Output already exists: {destination}. Pass --force to replace it.",
                EXIT_CONFLICT,
                {"output": str(destination)},
            )
        temporary.unlink()
    fsync_directory(destination.parent)
