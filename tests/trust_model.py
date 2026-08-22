#!/usr/bin/env python3
"""Qualify the 1.3.0 trust-model changes.

Session recovery is the only reaper for a dead agent's claims: `session end`
refuses while claims exist and nothing expires a session on its own, so
another actor must be able to recover. What that actor must not be able to do
is aim recovery at a session that heartbeated a moment ago. The stale
threshold now has a floor, `--force` is the explicit and separately audited
override, `session sweep` reaps every stale session in one bounded pass, and
`task claim` reaps an expired claim lease itself instead of failing forever
against a holder that will never release. Finally, changing an agent's status
names its accountable actor instead of attributing the change to the target.
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
from coordination.core import MIN_STALE_SECONDS, SESSION_LEASE_SECONDS  # noqa: E402
from coordination.errors import CoordinationError  # noqa: E402
from coordination.service import CoordinationService  # noqa: E402


OLD = "2020-01-01T00:00:00+00:00"


def expect(code: str, function: object) -> CoordinationError:
    try:
        function()  # type: ignore[operator]
    except CoordinationError as error:
        assert error.code == code, (code, error.code, error.message)
        return error
    raise AssertionError(f"expected {code} but the call succeeded")


def silence(database: Path, session_id: str, last_seen_at: str = OLD) -> None:
    with sqlite3.connect(database) as raw:
        raw.execute(
            "UPDATE agent_sessions SET last_seen_at = ? WHERE id = ?",
            (last_seen_at, session_id),
        )


def audit_rows(
    database: Path, object_type: str, object_id: str
) -> list[tuple[str, ...]]:
    with sqlite3.connect(database) as raw:
        return [
            tuple(str(value) for value in row)
            for row in raw.execute(
                "SELECT actor, action, detail FROM audit_log"
                " WHERE object_type = ? AND object_id = ? ORDER BY id",
                (object_type, object_id),
            )
        ]


def setup(database: Path) -> dict[str, CoordinationService]:
    base = CoordinationService(db=str(database))
    base.invoke("init", {})
    for actor in ("alice", "mallory", "operator"):
        base.invoke("agent_add", {"id": actor, "name": actor, "role": "r"})
    for session_id, actor in (("s-alice", "alice"), ("s-mallory", "mallory")):
        base.invoke("session_start", {"id": session_id, "agent": actor, "harness": "h"})
    return {
        "base": base,
        "alice": CoordinationService(db=str(database), session="s-alice"),
        "mallory": CoordinationService(db=str(database), session="s-mallory"),
    }


def test_recovery_floor_and_force(database: Path) -> None:
    services = setup(database)
    alice, mallory = services["alice"], services["mallory"]
    alice.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    alice.invoke("task_claim", {"id": "T-1", "agent": "alice", "if_revision": 1})

    # The gate cannot be zeroed: the floor is contractual.
    for below in (0, MIN_STALE_SECONDS - 1):
        error = expect(
            "invalid_arguments",
            lambda below=below: mallory.invoke(
                "session_recover",
                {
                    "id": "s-alice",
                    "actor": "mallory",
                    "reason": "x",
                    "stale_after_seconds": below,
                },
            ),
        )
        assert error.details["minimum"] == MIN_STALE_SECONDS, error.details

    # A live session is not stale at the floor.
    expect(
        "session_not_stale",
        lambda: mallory.invoke(
            "session_recover",
            {
                "id": "s-alice",
                "actor": "mallory",
                "reason": "x",
                "stale_after_seconds": MIN_STALE_SECONDS,
            },
        ),
    )
    assert services["base"].invoke("task_show", {"id": "T-1"})["claimed_by"] == "alice"

    # Force is the explicit override, and it is audited as forced.
    forced = mallory.invoke(
        "session_recover",
        {
            "id": "s-alice",
            "actor": "mallory",
            "reason": "alice is live but I insist",
            "force": True,
        },
    )
    assert forced["forced"] is True and forced["status"] == "ended", forced
    assert forced["recovered_tasks"] == [
        {"id": "T-1", "status": "blocked", "revision": 3}
    ]
    session_audit = audit_rows(database, "session", "s-alice")
    assert session_audit[-1][:2] == ("mallory", "recover"), session_audit
    assert session_audit[-1][2].startswith("forced; "), session_audit[-1]

    # Stale recovery without force is unchanged, and not forced.
    services["base"].invoke(
        "session_start", {"id": "s-alice-2", "agent": "alice", "harness": "h"}
    )
    silence(database, "s-alice-2")
    plain = mallory.invoke(
        "session_recover", {"id": "s-alice-2", "actor": "mallory", "reason": "stale"}
    )
    assert plain["forced"] is False, plain
    assert not audit_rows(database, "session", "s-alice-2")[-1][2].startswith("forced")


def test_sweep_reaps_only_stale_sessions(database: Path) -> None:
    services = setup(database)
    base = services["base"]
    base.invoke(
        "session_start", {"id": "s-operator", "agent": "operator", "harness": "h"}
    )
    operator = CoordinationService(db=str(database), session="s-operator")
    for index in range(3):
        base.invoke(
            "session_start", {"id": f"s-old-{index}", "agent": "alice", "harness": "h"}
        )
    alice_old = CoordinationService(db=str(database), session="s-old-0")
    alice_old.invoke("task_create", {"id": "T-old", "title": "t", "actor": "alice"})
    alice_old.invoke("task_claim", {"id": "T-old", "agent": "alice", "if_revision": 1})
    for index in range(3):
        silence(database, f"s-old-{index}")
    silence(database, "s-operator")  # the operator's own stale session is never swept

    swept = operator.invoke(
        "session_sweep", {"actor": "operator", "reason": "nightly sweep", "limit": 2}
    )
    assert swept["truncated"] is True, swept
    assert [entry["id"] for entry in swept["recovered_sessions"]] == [
        "s-old-0",
        "s-old-1",
    ]
    assert swept["recovered_sessions"][0]["recovered_tasks"] == [
        {"id": "T-old", "status": "blocked", "revision": 3}
    ]
    remaining = operator.invoke(
        "session_sweep", {"actor": "operator", "reason": "nightly sweep"}
    )
    assert [entry["id"] for entry in remaining["recovered_sessions"]] == ["s-old-2"]
    assert remaining["truncated"] is False
    live = {
        row["id"]: row["status"] for row in base.invoke("session_list", {"limit": 500})
    }
    assert live["s-alice"] == "active" and live["s-mallory"] == "active", live
    assert live["s-operator"] == "active", live
    assert all(live[f"s-old-{index}"] == "ended" for index in range(3)), live
    assert (
        operator.invoke("session_sweep", {"actor": "operator", "reason": "again"})[
            "recovered_sessions"
        ]
        == []
    )


def test_claim_lease_expiry(database: Path) -> None:
    services = setup(database)
    base, alice, mallory = services["base"], services["alice"], services["mallory"]
    alice.invoke("task_create", {"id": "T-1", "title": "t", "actor": "alice"})
    claimed = alice.invoke(
        "task_claim", {"id": "T-1", "agent": "alice", "if_revision": 1}
    )
    assert claimed["reaped_session"] is None, claimed

    # A live holder is never displaced, whatever the caller passes.
    expect(
        "task_already_claimed",
        lambda: mallory.invoke(
            "task_claim", {"id": "T-1", "agent": "mallory", "if_revision": 2}
        ),
    )
    # Replay by the holder is unchanged and carries the new field.
    replay = alice.invoke(
        "task_claim", {"id": "T-1", "agent": "alice", "if_revision": 1}
    )
    assert replay["idempotent_replay"] is True and replay["reaped_session"] is None

    # Once the holder has been silent past the lease, another claimant reaps it
    # and takes the task in one transaction, from the revision it observed.
    silence(database, "s-alice")
    taken = mallory.invoke(
        "task_claim", {"id": "T-1", "agent": "mallory", "if_revision": 2}
    )
    assert taken["claimed"] is True, taken
    assert taken["reaped_session"] == "s-alice", taken
    assert taken["revision"] == 4, taken  # 2 observed -> 3 reaped -> 4 claimed
    shown = base.invoke("task_show", {"id": "T-1"})
    assert shown["claimed_by"] == "mallory" and shown["claim_session_id"] == "s-mallory"
    assert "claim lease expired" in shown["notes"], shown["notes"]
    assert str(SESSION_LEASE_SECONDS) in shown["notes"]
    sessions = {row["id"]: row["status"] for row in base.invoke("session_list", {})}
    assert sessions["s-alice"] == "ended", sessions
    # The reap is attributed to the claimant, through the shared reaper.
    task_audit = audit_rows(database, "task", "T-1")
    assert ("mallory", "recover_claim") in {row[:2] for row in task_audit}, task_audit
    assert (
        task_audit[-1][:2] == ("mallory", "claim")
        and "reaped session s-alice" in task_audit[-1][2]
    )
    # The displaced holder learns at its next write: the fence holds.
    expect(
        "inactive_session",
        lambda: alice.invoke(
            "task_release",
            {"id": "T-1", "status": "todo", "actor": "alice", "if_revision": 4},
        ),
    )

    # The lease boundary is exact: silence one second inside the lease is live.
    base.invoke("session_start", {"id": "s-alice-2", "agent": "alice", "harness": "h"})
    alice2 = CoordinationService(db=str(database), session="s-alice-2")
    alice2.invoke("task_create", {"id": "T-2", "title": "t", "actor": "alice"})
    alice2.invoke("task_claim", {"id": "T-2", "agent": "alice", "if_revision": 1})
    from datetime import datetime, timedelta, timezone

    inside = (
        (datetime.now(timezone.utc) - timedelta(seconds=SESSION_LEASE_SECONDS - 5))
        .replace(microsecond=0)
        .isoformat()
    )
    silence(database, "s-alice-2", inside)
    expect(
        "task_already_claimed",
        lambda: mallory.invoke(
            "task_claim", {"id": "T-2", "agent": "mallory", "if_revision": 2}
        ),
    )


def test_agent_status_change_names_its_actor(database: Path) -> None:
    services = setup(database)
    base, mallory = services["base"], services["mallory"]
    base.invoke("agent_add", {"id": "bob", "name": "b", "role": "r"})
    error = expect(
        "invalid_arguments",
        lambda: base.invoke("agent_update", {"id": "bob", "status": "inactive"}),
    )
    assert error.details == {"field": "actor"}, error.details
    # Profile edits keep the documented default attribution.
    base.invoke("agent_update", {"id": "bob", "name": "Bob"})
    assert audit_rows(database, "agent", "bob")[-1][:2] == ("bob", "update")
    # A status change names who did it.
    mallory.invoke(
        "agent_update", {"id": "bob", "status": "inactive", "actor": "mallory"}
    )
    assert audit_rows(database, "agent", "bob")[-1][:2] == ("mallory", "update")


def main() -> int:
    for test in (
        test_recovery_floor_and_force,
        test_sweep_reaps_only_stale_sessions,
        test_claim_lease_expiry,
        test_agent_status_change_names_its_actor,
    ):
        with tempfile.TemporaryDirectory(prefix="coordination-trust-") as name:
            test(Path(name) / "coordination.sqlite3")
    print("Trust model qualification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
