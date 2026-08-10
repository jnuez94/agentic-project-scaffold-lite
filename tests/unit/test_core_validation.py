"""Unit coverage for the shared argument validators in coordination.core."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from coordination.core import (
    DEFAULT_BUSY_TIMEOUT_MS,
    MAX_BUSY_TIMEOUT_MS,
    MAX_IDENTIFIER_LENGTH,
    MAX_LIST_LIMIT,
    MAX_PATH_LENGTH,
    MAX_STALE_DAYS,
    MAX_TEXT_LENGTH,
    configured_busy_timeout_ms,
    database_lock_path,
    identifier,
    list_limit,
    list_offset,
    now,
    optional_text,
    output_lock_path,
    path_argument,
    positive_revision,
    require_unique,
    required_text,
    stale_days,
)
from coordination.errors import EXIT_ENVIRONMENT, EXIT_USAGE, CoordinationError


@pytest.mark.parametrize(
    "value",
    [
        "a",
        "engineering",
        "engineering-1",
        "reviewer.security",
        "actor_name",
        "role:release",
        "josh@example",
        "build+1",
        "0",
        "A" * MAX_IDENTIFIER_LENGTH,
    ],
)
def test_identifier_accepts_documented_grammar(value: str) -> None:
    assert identifier(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "-leading-dash",
        ".leading-dot",
        "_leading-underscore",
        "has space",
        "has/slash",
        "has\\backslash",
        "trailing\n",
        "café",
        "emoji-🙂",
        "A" * (MAX_IDENTIFIER_LENGTH + 1),
    ],
)
def test_identifier_rejects_values_outside_the_grammar(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        identifier(value)


def test_identifier_does_not_rewrite_accepted_values() -> None:
    """The contract promises identifiers are never silently normalized."""
    assert identifier("Mixed.Case_ID") == "Mixed.Case_ID"


@pytest.mark.parametrize("value", ["", "   ", "\t", "\n", " \r\n "])
def test_required_text_rejects_blank_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        required_text(value)


def test_required_text_preserves_surrounding_whitespace() -> None:
    assert required_text("  spaced content  ") == "  spaced content  "


def test_optional_text_accepts_empty_but_rejects_nul() -> None:
    assert optional_text("") == ""
    with pytest.raises(argparse.ArgumentTypeError):
        optional_text("before\x00after")


def test_optional_text_rejects_lone_surrogates() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        optional_text("\ud800")


def test_optional_text_enforces_its_length_bound() -> None:
    assert optional_text("x" * MAX_TEXT_LENGTH) == "x" * MAX_TEXT_LENGTH
    with pytest.raises(argparse.ArgumentTypeError):
        optional_text("x" * (MAX_TEXT_LENGTH + 1))


@pytest.mark.parametrize("value", ["", "   ", "with\x00nul"])
def test_path_argument_rejects_blank_and_nul(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        path_argument(value)


def test_path_argument_enforces_its_length_bound() -> None:
    assert path_argument("p" * MAX_PATH_LENGTH) == "p" * MAX_PATH_LENGTH
    with pytest.raises(argparse.ArgumentTypeError):
        path_argument("p" * (MAX_PATH_LENGTH + 1))


@pytest.mark.parametrize(
    ("parser", "accepted", "rejected"),
    [
        (list_limit, ("1", str(MAX_LIST_LIMIT)), ("0", str(MAX_LIST_LIMIT + 1))),
        (list_offset, ("0", "2147483647"), ("-1", "2147483648")),
        (positive_revision, ("1", "2147483647"), ("0", "2147483648")),
        (stale_days, ("0", str(MAX_STALE_DAYS)), ("-1", str(MAX_STALE_DAYS + 1))),
    ],
)
def test_bounded_integers_enforce_documented_ranges(
    parser: object,
    accepted: tuple[str, ...],
    rejected: tuple[str, ...],
) -> None:
    assert callable(parser)
    for value in accepted:
        assert parser(value) == int(value)
    for value in rejected:
        with pytest.raises(argparse.ArgumentTypeError):
            parser(value)


@pytest.mark.parametrize("value", ["", "seven", "1.5", "0x10", " 1 2 "])
def test_bounded_integers_reject_non_integers(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        list_limit(value)


def test_require_unique_accepts_distinct_values() -> None:
    require_unique(["a", "b", "c"], "--assignee")
    require_unique([], "--assignee")


def test_require_unique_reports_every_duplicate_once() -> None:
    with pytest.raises(CoordinationError) as caught:
        require_unique(["a", "b", "a", "c", "b", "b"], "--assignee")
    error = caught.value
    assert error.code == "invalid_arguments"
    assert error.exit_code == EXIT_USAGE
    assert error.details["option"] == "--assignee"
    assert error.details["duplicates"] == ["a", "b"]


def test_busy_timeout_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COORDINATION_BUSY_TIMEOUT_MS", raising=False)
    assert configured_busy_timeout_ms() == DEFAULT_BUSY_TIMEOUT_MS


@pytest.mark.parametrize("value", ["0", "1", str(MAX_BUSY_TIMEOUT_MS)])
def test_busy_timeout_accepts_in_range_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("COORDINATION_BUSY_TIMEOUT_MS", value)
    assert configured_busy_timeout_ms() == int(value)


@pytest.mark.parametrize(
    "value",
    ["-1", str(MAX_BUSY_TIMEOUT_MS + 1), "not-a-number", ""],
)
def test_busy_timeout_rejects_unusable_configuration(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("COORDINATION_BUSY_TIMEOUT_MS", value)
    with pytest.raises(CoordinationError) as caught:
        configured_busy_timeout_ms()
    assert caught.value.code == "configuration_error"
    assert caught.value.exit_code == EXIT_ENVIRONMENT


def test_busy_timeout_is_interpolated_into_pragma_only_as_an_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRAGMA cannot be parameterized, so the value must never reach SQL as text."""
    monkeypatch.setenv("COORDINATION_BUSY_TIMEOUT_MS", "1000; DROP TABLE agents")
    with pytest.raises(CoordinationError):
        configured_busy_timeout_ms()


def test_now_is_utc_second_resolution_iso8601() -> None:
    stamp = now()
    assert stamp.endswith("+00:00")
    assert "." not in stamp
    assert len(stamp) == len("2026-01-01T00:00:00+00:00")


def test_lock_paths_are_siblings_of_their_target(tmp_path: Path) -> None:
    database = tmp_path / "coordination.sqlite3"
    assert database_lock_path(database) == tmp_path / "coordination.sqlite3.lock"
    lock = output_lock_path(database)
    assert lock.parent == tmp_path
    assert lock.name.startswith(".")
    assert lock.name.endswith(".publish.lock")


def test_validators_do_not_depend_on_process_state() -> None:
    """The validators are pure, so ordering between suites cannot matter."""
    before = dict(os.environ)
    identifier("actor")
    required_text("title")
    path_argument("relative/path")
    assert dict(os.environ) == before
