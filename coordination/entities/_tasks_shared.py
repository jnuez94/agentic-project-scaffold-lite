"""Task statuses, transitions, shared query, and claim-ownership checks."""

from __future__ import annotations

from collections.abc import Iterable
import sqlite3
from typing import Any

from coordination.errors import EXIT_CONFLICT, fail


STATUSES = ("todo", "in_progress", "review", "blocked", "done")

STATUS_TRANSITIONS = {
    "todo": frozenset({"in_progress", "blocked"}),
    "in_progress": frozenset({"todo", "review", "blocked"}),
    "review": frozenset({"in_progress", "blocked", "done"}),
    "blocked": frozenset({"todo", "in_progress"}),
    "done": frozenset(),
}


def task_query() -> str:
    return """SELECT t.*,
        tc.agent_id AS claimed_by,
        tc.session_id AS claim_session_id,
        tc.claimed_at
      FROM tasks t
      LEFT JOIN task_claims tc ON tc.task_id = t.id"""


def shape_tasks(
    connection: Any,
    task_rows: Iterable[Any],
) -> list[dict[str, Any]]:
    values = [dict(row) for row in task_rows]
    if not values:
        return []
    task_ids = [str(value["id"]) for value in values]
    assignees: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    evidence_counts = dict.fromkeys(task_ids, 0)
    for offset in range(0, len(task_ids), 400):
        batch = task_ids[offset : offset + 400]
        placeholders = ",".join("?" for _ in batch)
        for row in connection.execute(
            f"""SELECT task_id, agent_id FROM task_assignees
                WHERE task_id IN ({placeholders})
                ORDER BY task_id, agent_id""",
            batch,
        ):
            assignees[str(row["task_id"])].append(str(row["agent_id"]))
        for row in connection.execute(
            f"""SELECT task_id, COUNT(*) AS evidence_count FROM task_evidence
                WHERE task_id IN ({placeholders})
                GROUP BY task_id
                ORDER BY task_id""",
            batch,
        ):
            evidence_counts[str(row["task_id"])] = int(row["evidence_count"])
    for value in values:
        task_id = str(value["id"])
        value["assignees"] = assignees[task_id]
        value["evidence_count"] = evidence_counts[task_id]
    return values


def reject_stale_revision(task_id: str, expected: int, actual: int) -> None:
    fail(
        "stale_task_revision",
        f"Task {task_id} changed after revision {expected}",
        EXIT_CONFLICT,
        {
            "task": task_id,
            "expected_revision": expected,
            "actual_revision": actual,
        },
    )


def require_claim_ownership(
    connection: sqlite3.Connection,
    task_id: str,
    actor: str,
    session: str | None,
) -> None:
    """Reject mutating a claimed task from anyone but the claim holder.

    An exclusive claim that any actor can write around is not exclusive. Every
    write bumps the revision, so without this an uninvolved actor could keep a
    claimed task's revision moving and stall the owner's own release. Callers
    must hold the write transaction so the claim cannot change underneath.
    Unclaimed tasks stay open to any active actor.
    """
    claim = connection.execute(
        "SELECT agent_id, session_id FROM task_claims WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if claim is None:
        return
    if actor != claim["agent_id"]:
        fail(
            "task_claim_owner_mismatch",
            f"Task {task_id} is claimed by {claim['agent_id']}",
            EXIT_CONFLICT,
            {
                "task": task_id,
                "claimed_by": claim["agent_id"],
                "actor": actor,
            },
        )
    if session != claim["session_id"]:
        fail(
            "task_claim_session_mismatch",
            f"Task {task_id} is claimed by session {claim['session_id']}",
            EXIT_CONFLICT,
            {
                "task": task_id,
                "claim_session_id": claim["session_id"],
                "session_id": session,
            },
        )
