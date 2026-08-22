"""Unit coverage for the stable error envelope and exit-code contract."""

from __future__ import annotations

from contextlib import redirect_stderr
import io
import json

import pytest

from coordination.errors import (
    EXIT_BUSY,
    EXIT_CONFLICT,
    EXIT_ENVIRONMENT,
    EXIT_INTERNAL,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    CoordinationError,
    emit_error,
    error_envelope,
    fail,
)


def test_exit_codes_match_the_published_contract() -> None:
    """docs/cli-contract.md publishes these numbers; they are not free to move."""
    assert (
        EXIT_INTERNAL,
        EXIT_USAGE,
        EXIT_NOT_FOUND,
        EXIT_CONFLICT,
        EXIT_ENVIRONMENT,
        EXIT_BUSY,
    ) == (1, 2, 3, 4, 5, 6)


def test_fail_raises_a_coordination_error_carrying_its_fields() -> None:
    with pytest.raises(CoordinationError) as caught:
        fail("not_found", "Not found: agent josh", EXIT_NOT_FOUND, {"resource": "x"})
    error = caught.value
    assert error.code == "not_found"
    assert error.message == "Not found: agent josh"
    assert error.exit_code == EXIT_NOT_FOUND
    assert error.details == {"resource": "x"}
    assert str(error) == "Not found: agent josh"


def test_details_default_to_an_empty_mapping() -> None:
    error = CoordinationError("internal_error", "boom", EXIT_INTERNAL)
    assert error.details == {}


def test_envelope_omits_absent_details_and_exit_code() -> None:
    envelope = error_envelope(CoordinationError("usage", "bad", EXIT_USAGE))
    assert envelope == {"ok": False, "error": {"code": "usage", "message": "bad"}}


def test_envelope_includes_details_when_present() -> None:
    envelope = error_envelope(
        CoordinationError("usage", "bad", EXIT_USAGE, {"field": "id"})
    )
    assert envelope["error"]["details"] == {"field": "id"}


def test_envelope_adds_exit_code_only_when_requested() -> None:
    error = CoordinationError("database_busy", "locked", EXIT_BUSY)
    assert "exit_code" not in error_envelope(error)["error"]
    assert error_envelope(error, include_exit_code=True)["error"]["exit_code"] == (
        EXIT_BUSY
    )


def test_emit_error_writes_sorted_indented_json_to_stderr() -> None:
    stream = io.StringIO()
    with redirect_stderr(stream):
        emit_error(CoordinationError("usage", "bad", EXIT_USAGE, {"z": 1, "a": 2}))
    written = stream.getvalue()
    assert json.loads(written) == {
        "ok": False,
        "error": {"code": "usage", "message": "bad", "details": {"a": 2, "z": 1}},
    }
    assert written.startswith("{\n")
    assert '"a"' in written and written.index('"a"') < written.index('"z"')


def test_emit_error_writes_nothing_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_error(CoordinationError("usage", "bad", EXIT_USAGE))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["ok"] is False
