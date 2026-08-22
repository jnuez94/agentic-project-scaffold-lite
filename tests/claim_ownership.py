#!/usr/bin/env python3
"""Claim-exclusivity qualification for the 1.2.0 task write surface.

`task assign`, `task update`, and `task release` were added in 1.2.0. As
shipped, release performed an unowned status transition on a task nobody held,
and assign and update let any active actor bump a claimed task's revision --
which could stall the claim owner's own release indefinitely, in a model whose
premise is exclusive claims.

These probes pin the corrected behavior and the boundaries of it.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Imported after the repository root joins sys.path so this probe always tests
# the in-tree runtime rather than an installed copy.
from coordination.errors import CoordinationError  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


def _expect_error(code: str, call: object, *args: object, **kwargs: object) -> None:
    assert callable(call)
    try:
        call(*args, **kwargs)
    except CoordinationError as error:
        assert error.code == code, f"expected {code}, got {error.code}"
    else:
        raise AssertionError(f"expected {code}, but the operation succeeded")


def _project(root: Path) -> Path:
    subprocess.run(
        [
            str(ROOT / "scripts" / "install.sh"),
            "--target",
            str(root),
            "--adapter",
            "sqlite",
        ],
        check=True,
        capture_output=True,
    )
    return root / ".coordination" / "coordination.sqlite3"


def _seed(database: Path) -> None:
    service = CoordinationService(db=str(database))
    for actor in ("alice", "bob", "carol"):
        service.agent_add(id=actor, name=actor.title(), role="engineering")
    for actor in ("alice", "bob"):
        service.session_start(
            id=f"s-{actor}",
            agent=actor,
            harness="qualification",
            model="none",
        )


def test_release_requires_an_owned_claim(database: Path) -> None:
    alice = CoordinationService(db=str(database), session="s-alice")
    alice.task_create(id="R1", title="Never claimed", actor="alice")

    # The shipped 1.2.0 behavior: this succeeded and moved todo -> blocked.
    _expect_error(
        "task_not_claimed",
        alice.task_release,
        id="R1",
        status="blocked",
        actor="alice",
        if_revision=1,
    )

    # The same transition through `task status` stays available.
    result = alice.task_status(id="R1", status="blocked", actor="alice", if_revision=1)
    assert result["status"] == "blocked", result


def test_release_rejects_a_foreign_claim(database: Path) -> None:
    alice = CoordinationService(db=str(database), session="s-alice")
    bob = CoordinationService(db=str(database), session="s-bob")
    alice.task_create(id="R2", title="Alice holds this", actor="alice")
    alice.task_claim(id="R2", agent="alice", if_revision=1)

    _expect_error(
        "task_claim_owner_mismatch",
        bob.task_release,
        id="R2",
        status="todo",
        actor="bob",
        if_revision=2,
    )
    released = alice.task_release(id="R2", status="todo", actor="alice", if_revision=2)
    assert released["status"] == "todo", released


def test_claimed_tasks_reject_foreign_writes(database: Path) -> None:
    alice = CoordinationService(db=str(database), session="s-alice")
    bob = CoordinationService(db=str(database), session="s-bob")
    alice.task_create(id="C1", title="Claimed", actor="alice")
    claim = alice.task_claim(id="C1", agent="alice", if_revision=1)
    revision = int(claim["revision"])

    _expect_error(
        "task_claim_owner_mismatch",
        bob.task_update,
        id="C1",
        actor="bob",
        if_revision=revision,
        description="bob was here",
    )
    _expect_error(
        "task_claim_owner_mismatch",
        bob.task_assign,
        id="C1",
        actor="bob",
        if_revision=revision,
        add=["carol"],
    )

    # The owner's revision is still the one she was handed, so her own release
    # cannot be starved by another actor's writes.
    released = alice.task_release(
        id="C1", status="review", actor="alice", if_revision=revision
    )
    assert released["status"] == "review", released


def test_claim_owner_retains_full_access(database: Path) -> None:
    alice = CoordinationService(db=str(database), session="s-alice")
    alice.task_create(id="C2", title="Owner writes", actor="alice")
    claim = alice.task_claim(id="C2", agent="alice", if_revision=1)
    revision = int(claim["revision"])
    updated = alice.task_update(
        id="C2", actor="alice", if_revision=revision, description="owner edit"
    )
    assigned = alice.task_assign(
        id="C2", actor="alice", if_revision=int(updated["revision"]), add=["carol"]
    )
    assert "carol" in assigned["assignees"], assigned


def test_unclaimed_tasks_stay_open(database: Path) -> None:
    alice = CoordinationService(db=str(database), session="s-alice")
    bob = CoordinationService(db=str(database), session="s-bob")
    alice.task_create(id="U1", title="Unclaimed", actor="alice")
    updated = bob.task_update(
        id="U1", actor="bob", if_revision=1, description="collaborator edit"
    )
    assigned = bob.task_assign(
        id="U1", actor="bob", if_revision=int(updated["revision"]), add=["carol"]
    )
    assert "carol" in assigned["assignees"], assigned


def test_a_session_may_not_borrow_another_session_claim(database: Path) -> None:
    """Same actor, different session, must not inherit the claim."""
    alice = CoordinationService(db=str(database), session="s-alice")
    alice.task_create(id="S1", title="Session bound", actor="alice")
    claim = alice.task_claim(id="S1", agent="alice", if_revision=1)
    alice.session_start(
        id="s-alice-2", agent="alice", harness="qualification", model="none"
    )
    other_session = CoordinationService(db=str(database), session="s-alice-2")
    _expect_error(
        "task_claim_session_mismatch",
        other_session.task_update,
        id="S1",
        actor="alice",
        if_revision=int(claim["revision"]),
        description="wrong session",
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "project"
        root.mkdir()
        database = _project(root)
        _seed(database)
        test_release_requires_an_owned_claim(database)
        test_release_rejects_a_foreign_claim(database)
        test_claimed_tasks_reject_foreign_writes(database)
        test_claim_owner_retains_full_access(database)
        test_unclaimed_tasks_stay_open(database)
        test_a_session_may_not_borrow_another_session_claim(database)
    print("Claim ownership qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
