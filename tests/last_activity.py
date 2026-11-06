#!/usr/bin/env python3
"""Qualify `last_activity_at`: reviews, evidence, and dependencies show on tasks.

`review add`, `evidence add`, and `dependency add` leave the task row alone,
so a watcher of `updated_at` missed them. Task rows now carry
`last_activity_at`, the latest of `updated_at` and those rows' `created_at`,
and `task list --activity-since` filters on it. The stored `updated_at` is
unchanged, so doctor's record consistency is unaffected.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.service import CoordinationService  # noqa: E402


OLD = "2026-01-01T00:00:00+00:00"
MIDPOINT = "2026-06-01T00:00:00+00:00"


def test_activity_is_joined_onto_tasks(database: Path) -> None:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    service.invoke("agent_add", {"id": "toby", "name": "t", "role": "r"})
    for task_id in ("T-REVIEWED", "T-EVIDENCED", "T-DEPENDENT", "T-QUIET"):
        service.invoke(
            "task_create", {"id": task_id, "title": task_id, "actor": "toby"}
        )
    # Age every task so new activity is distinguishable from creation.
    with sqlite3.connect(database) as raw:
        raw.execute("UPDATE tasks SET updated_at = ?", (OLD,))
    before = {
        task["id"]: task["last_activity_at"] for task in service.invoke("task_list", {})
    }
    assert set(before.values()) == {OLD}, before
    assert service.invoke("task_list", {"activity_since": MIDPOINT}) == []

    service.invoke(
        "review_add",
        {
            "id": "R-1",
            "reviewer": "toby",
            "artifact": "a",
            "scope": "s",
            "decision": "accepted",
            "task": "T-REVIEWED",
        },
    )
    service.invoke(
        "evidence_add", {"task": "T-EVIDENCED", "uri": "evidence://x", "actor": "toby"}
    )
    service.invoke(
        "dependency_add",
        {
            "task": "T-DEPENDENT",
            "depends_on": "T-QUIET",
            "actor": "toby",
            "type": "informs",
        },
    )

    after = {task["id"]: task for task in service.invoke("task_list", {})}
    for task_id in ("T-REVIEWED", "T-EVIDENCED", "T-DEPENDENT"):
        assert after[task_id]["last_activity_at"] > MIDPOINT, after[task_id]
        # The stored row is untouched: the activity is joined, not stamped.
        assert after[task_id]["updated_at"] == OLD
    # A dependency counts for the task that depends, not its target.
    assert after["T-QUIET"]["last_activity_at"] == OLD

    recent = service.invoke("task_list", {"activity_since": MIDPOINT})
    assert sorted(task["id"] for task in recent) == [
        "T-DEPENDENT",
        "T-EVIDENCED",
        "T-REVIEWED",
    ]
    shown = service.invoke("task_show", {"id": "T-REVIEWED"})
    assert shown["last_activity_at"] == shown["reviews"][-1]["created_at"]

    via_cli = subprocess.run(
        [
            str(ROOT / "scripts" / "coordination.py"),
            "--db",
            str(database),
            "task",
            "list",
            "--activity-since",
            MIDPOINT,
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert sorted(task["id"] for task in json.loads(via_cli.stdout)["data"]) == [
        "T-DEPENDENT",
        "T-EVIDENCED",
        "T-REVIEWED",
    ]
    rejected = subprocess.run(
        [
            str(ROOT / "scripts" / "coordination.py"),
            "--db",
            str(database),
            "task",
            "list",
            "--activity-since",
            "yesterday",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert rejected.returncode == 2, rejected.stderr


def test_doctor_stays_consistent(database: Path) -> None:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    service.invoke("agent_add", {"id": "toby", "name": "t", "role": "r"})
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "toby"})
    service.invoke(
        "review_add",
        {
            "id": "R-1",
            "reviewer": "toby",
            "artifact": "a",
            "scope": "s",
            "decision": "accepted",
            "task": "T-1",
        },
    )
    service.invoke(
        "evidence_add", {"task": "T-1", "uri": "evidence://x", "actor": "toby"}
    )
    doctor = service.invoke("doctor", {})
    assert doctor["record_consistency"] == "ok", doctor["out_of_band_edits"]


def main() -> int:
    for test in (test_activity_is_joined_onto_tasks, test_doctor_stays_consistent):
        with tempfile.TemporaryDirectory(prefix="coordination-activity-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Last activity qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
