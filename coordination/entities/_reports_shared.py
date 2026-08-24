"""Shared report sections, row limits, and inline Markdown escaping."""

from __future__ import annotations

import html
import re
import sqlite3

from coordination.core import (
    rows,
)


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
