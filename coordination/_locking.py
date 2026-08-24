"""Advisory file locks, connection tracking, and the operation scope."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
import fcntl
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import BinaryIO

from coordination._primitives import DEFAULT_BUSY_TIMEOUT_MS, MAX_BUSY_TIMEOUT_MS
from coordination.errors import EXIT_BUSY, EXIT_ENVIRONMENT, fail


_CONNECTION_LOCKS: dict[int, BinaryIO] = {}

_OPEN_CONNECTIONS = threading.local()


@dataclass
class OperationScope:
    """What one service operation opened, wrote, and waited for.

    Connections are released at scope exit. Audit ids written inside the
    operation are contiguous (one write transaction holds the writer lock), so
    the receipt the dispatch boundary returns is simply their min and max.
    Advisory-lock wait is accumulated so the operation log can report
    contention that never reaches the database.
    """

    connections: list[sqlite3.Connection] = field(default_factory=list)
    audit_ids: list[int] = field(default_factory=list)
    lock_wait_ms: float = 0.0


def current_scope() -> OperationScope | None:
    stack = getattr(_OPEN_CONNECTIONS, "stack", None)
    return stack[-1] if stack else None


def configured_busy_timeout_ms() -> int:
    raw = os.environ.get("COORDINATION_BUSY_TIMEOUT_MS", str(DEFAULT_BUSY_TIMEOUT_MS))
    try:
        value = int(raw)
    except ValueError:
        fail(
            "configuration_error",
            "COORDINATION_BUSY_TIMEOUT_MS must be an integer",
            EXIT_ENVIRONMENT,
            {"value": raw},
        )
    if not 0 <= value <= MAX_BUSY_TIMEOUT_MS:
        fail(
            "configuration_error",
            f"COORDINATION_BUSY_TIMEOUT_MS must be between 0 and {MAX_BUSY_TIMEOUT_MS}",
            EXIT_ENVIRONMENT,
            {"value": value},
        )
    return value


def database_lock_path(path: Path) -> Path:
    return Path(f"{path}.lock")


def output_lock_path(path: Path) -> Path:
    return path.parent / f".{path.name}.publish.lock"


def _acquire_file_lock(
    path: Path,
    *,
    exclusive: bool,
    timeout_ms: int,
) -> BinaryIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    handle = os.fdopen(descriptor, "a+b", buffering=0)
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    started = time.monotonic()
    deadline = started + (timeout_ms / 1000)
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), operation | fcntl.LOCK_NB)
                return handle
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    fail(
                        "database_busy",
                        "Timed out waiting for an operational file lock",
                        EXIT_BUSY,
                        {"lock": str(path), "timeout_ms": timeout_ms},
                    )
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            except BaseException:
                handle.close()
                raise
    finally:
        scope = current_scope()
        if scope is not None:
            scope.lock_wait_ms += (time.monotonic() - started) * 1000


def _release_file_lock(handle: BinaryIO) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def advisory_file_lock(
    path: Path,
    *,
    exclusive: bool,
    timeout_ms: int | None = None,
) -> Generator[None, None, None]:
    handle = _acquire_file_lock(
        path,
        exclusive=exclusive,
        timeout_ms=(configured_busy_timeout_ms() if timeout_ms is None else timeout_ms),
    )
    try:
        yield
    finally:
        _release_file_lock(handle)


def close_connection(connection: sqlite3.Connection) -> None:
    try:
        connection.close()
    finally:
        handle = _CONNECTION_LOCKS.pop(id(connection), None)
        if handle is not None:
            _release_file_lock(handle)


def _track_connection(connection: sqlite3.Connection) -> None:
    """Register a connection for release at the end of the active operation."""
    scope = current_scope()
    if scope is not None:
        # A strong reference also stops CPython from recycling the id() that
        # keys _CONNECTION_LOCKS while the handle is still live.
        scope.connections.append(connection)


@contextmanager
def connection_scope() -> Generator[OperationScope, None, None]:
    """Release every connection and advisory lock opened by one operation.

    Entity functions open connections and return materialized rows; none of
    them own the closing side. That is harmless in a one-shot CLI process,
    where exit releases everything, but a long-lived transport accumulates
    shared locks on the database lock file until an operation needing the
    exclusive lock -- restore -- can no longer take it, and blocks every other
    process too. Dispatch boundaries wrap each operation in this scope.
    """
    stack = getattr(_OPEN_CONNECTIONS, "stack", None)
    if stack is None:
        stack = []
        _OPEN_CONNECTIONS.stack = stack
    scope = OperationScope()
    stack.append(scope)
    try:
        yield scope
    finally:
        finished = stack.pop()
        for connection in finished.connections:
            # Already-closed connections are fine: sqlite3 close() is
            # idempotent and close_connection tolerates a missing handle.
            with suppress(sqlite3.Error):
                close_connection(connection)
        # Scopes nest: the dispatch boundary opens one around the whole
        # operation and each service method opens its own. What the inner
        # scope wrote and waited for belongs to the operation, so it rolls up
        # to the parent; connections were released here and do not.
        if stack:
            stack[-1].audit_ids.extend(finished.audit_ids)
            stack[-1].lock_wait_ms += finished.lock_wait_ms
