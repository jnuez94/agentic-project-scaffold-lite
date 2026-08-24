"""Unit coverage for the CLI outer boundary: every failure maps to a stable
JSON envelope on stderr and the documented exit code."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from coordination import cli
from coordination.errors import CoordinationError


def run_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raiser: Any,
) -> tuple[int, dict[str, Any]]:
    monkeypatch.setattr(cli, "build_parser", lambda: FakeParser())
    monkeypatch.setattr(
        cli.CoordinationService, "invoke_cli", lambda self, args: raiser()
    )
    code = cli.main()
    captured = capsys.readouterr()
    assert captured.out == ""
    return code, json.loads(captured.err)


class FakeParser:
    def parse_args(self) -> Any:
        from argparse import Namespace

        return Namespace(db=None, session=None, command="doctor")


@pytest.mark.parametrize(
    ("exception", "code", "exit_code"),
    [
        (CoordinationError("database_not_found", "x", 3), "database_not_found", 3),
        (sqlite3.IntegrityError("UNIQUE constraint failed"), "constraint_violation", 4),
        (sqlite3.OperationalError("database is locked"), "database_busy", 6),
        (sqlite3.OperationalError("disk I/O error"), "database_error", 5),
        (sqlite3.DatabaseError("malformed"), "environment_error", 5),
        (OSError("no space left"), "environment_error", 5),
        (KeyboardInterrupt(), "operation_interrupted", 5),
    ],
)
def test_main_maps_failures_to_stable_envelopes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exception: BaseException,
    code: str,
    exit_code: int,
) -> None:
    def raiser() -> None:
        raise exception

    returned, envelope = run_main(monkeypatch, capsys, raiser)
    assert returned == exit_code
    assert envelope["ok"] is False and envelope["error"]["code"] == code


def test_main_emits_nothing_for_a_none_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "build_parser", lambda: FakeParser())
    monkeypatch.setattr(cli.CoordinationService, "invoke_cli", lambda self, args: None)
    assert cli.main() == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
