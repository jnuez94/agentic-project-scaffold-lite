"""Shared report sections, row limits, and atomic text output."""

from __future__ import annotations

import html
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from coordination.core import (
    advisory_file_lock,
    output_lock_path,
    publish_temporary_file,
    rows,
)


def atomic_write_text(output: Path, content: str, *, force: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = f".{output.name}."
    suffix = ".tmp"
    with advisory_file_lock(output_lock_path(output), exclusive=True):
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=prefix,
            suffix=suffix,
            dir=output.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            publish_temporary_file(temporary, output, force=force)
        finally:
            temporary.unlink(missing_ok=True)


def _limited_rows(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...],
    limit: int,
) -> tuple[list[dict[str, object]], bool]:
    values = rows(connection.execute(query + " LIMIT ?", (*parameters, limit + 1)))
    return values[:limit], len(values) > limit


def _markdown_inline(value: object) -> str:
    collapsed = re.sub(r"\s+", " ", str(value)).strip()
    escaped = html.escape(collapsed, quote=False)
    return re.sub(r"([\\`*_\[\]{}|])", r"\\\1", escaped)


HEALTH_ANOMALY_SECTIONS = (
    "unowned_tasks",
    "stale_tasks",
    "stale_sessions",
    "unclaimed_in_progress_tasks",
    "invalid_active_claims",
    "active_blockers",
    "done_without_evidence",
    "open_escalations",
)

HEALTH_INFORMATIONAL_SECTIONS = ("tasks_awaiting_review",)

HEALTH_SECTIONS = HEALTH_ANOMALY_SECTIONS + HEALTH_INFORMATIONAL_SECTIONS

SUMMARY_SECTIONS = (
    "totals",
    "task_status",
    "task_priority",
    "workload",
    "time_in_state",
)
