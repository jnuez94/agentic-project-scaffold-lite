#!/usr/bin/env python3
"""Qualify `task show` review ordering: insertion order, with `sequence`.

Reviews written in one second share `created_at`, and the old tie-break by ID
text put REV-10 before REV-9, so the last review in `task show` was not the
latest. `task show` now agrees with `review list`.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.service import CoordinationService  # noqa: E402


def test_same_second_reviews_keep_insertion_order(database: Path) -> None:
    service = CoordinationService(db=str(database))
    service.invoke("init", {})
    service.invoke("agent_add", {"id": "toby", "name": "t", "role": "r"})
    service.invoke("task_create", {"id": "T-1", "title": "t", "actor": "toby"})
    # Written in one tick: an accept, then a request for changes. The request
    # is the latest word, and must be the last element.
    for review_id, decision in (
        ("REV-9", "accepted"),
        ("REV-10", "changes_requested"),
    ):
        service.invoke(
            "review_add",
            {
                "id": review_id,
                "reviewer": "toby",
                "artifact": "a",
                "scope": "s",
                "decision": decision,
                "task": "T-1",
            },
        )
    shown = service.invoke("task_show", {"id": "T-1"})["reviews"]
    assert [review["id"] for review in shown] == ["REV-9", "REV-10"]
    assert shown[-1]["decision"] == "changes_requested"
    assert shown[0]["sequence"] < shown[1]["sequence"]

    listed = service.invoke("review_list", {"task": "T-1"})
    assert [(r["id"], r["sequence"]) for r in shown] == [
        (r["id"], r["sequence"]) for r in listed
    ]

    via_cli = subprocess.run(
        [
            str(ROOT / "scripts" / "coordination.py"),
            "--db",
            str(database),
            "task",
            "show",
            "T-1",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    reviews = json.loads(via_cli.stdout)["data"]["reviews"]
    assert [review["id"] for review in reviews] == ["REV-9", "REV-10"]
    assert all(isinstance(review["sequence"], int) for review in reviews)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="coordination-show-reviews-") as name:
        test_same_second_reviews_keep_insertion_order(Path(name) / "c.sqlite3")
    print("Task show review ordering qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
