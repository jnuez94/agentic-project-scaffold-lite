#!/usr/bin/env python3
"""Qualify the bound on `task show` detail arrays.

`task show` (and the `coordination_task_inspect` MCP tool over it) used to
return every evidence, dependency, and review row attached to a task with no
limit, while every sibling list command is capped at MAX_LIST_LIMIT. The
response grew linearly with attached rows; at a few thousand reviews near the
text cap it reached hundreds of megabytes, built in memory and handed to a
client in one message. The detail arrays now share the list bound, and any
truncation is reported in `truncated_sections` rather than silently dropped.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.core import MAX_LIST_LIMIT  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="coordination-inspect-") as name:
        database = Path(name) / "coordination.sqlite3"
        service = CoordinationService(db=str(database))
        service.invoke("init", {})
        service.invoke("agent_add", {"id": "owner", "name": "Owner", "role": "r"})
        service.invoke(
            "task_create", {"id": "T-1", "title": "Bounded", "actor": "owner"}
        )

        # Rows go in directly: the point is the read bound, not the write path,
        # and MAX_LIST_LIMIT + 1 service calls would dominate the run time.
        stamp = "2026-01-01T00:00:00+00:00"
        with sqlite3.connect(database) as raw:
            raw.executemany(
                "INSERT INTO task_evidence(task_id, uri, evidence_type, added_by,"
                " created_at) VALUES ('T-1', ?, 'artifact', 'owner', ?)",
                [(f"evidence://{index}", stamp) for index in range(MAX_LIST_LIMIT + 7)],
            )
            raw.executemany(
                "INSERT INTO reviews(id, task_id, reviewer_id, artifact_uri, scope,"
                " decision, created_at) VALUES (?, 'T-1', 'owner', 'a', 's',"
                " 'accepted', ?)",
                [(f"R-{index}", stamp) for index in range(3)],
            )

        shown = service.invoke("task_show", {"id": "T-1"})
        assert isinstance(shown, dict), shown
        assert len(shown["evidence"]) == MAX_LIST_LIMIT, len(shown["evidence"])
        assert shown["evidence_count"] == MAX_LIST_LIMIT + 7, shown["evidence_count"]
        assert len(shown["reviews"]) == 3
        assert shown["dependencies"] == []
        assert shown["truncated_sections"] == ["evidence"], shown["truncated_sections"]

        # The per-entity list command remains the complete, pageable view.
        page = service.invoke(
            "evidence_list",
            {"task": "T-1", "limit": MAX_LIST_LIMIT, "offset": MAX_LIST_LIMIT},
        )
        assert isinstance(page, list) and len(page) == 7, len(page)

        # Under the bound nothing is reported as truncated.
        service.invoke("task_create", {"id": "T-2", "title": "Small", "actor": "owner"})
        small = service.invoke("task_show", {"id": "T-2"})
        assert isinstance(small, dict) and small["truncated_sections"] == []
    print("Task inspect bound qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
