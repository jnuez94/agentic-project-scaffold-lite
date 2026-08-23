"""Unit coverage for the declarative read surface: descriptors and the
predicate builder accept only what a descriptor lists."""

from __future__ import annotations

import argparse

import pytest

from coordination.entities.descriptors import (
    DESCRIPTORS,
    TASKS,
    Filter,
    parse_order,
    parse_where,
    query_options,
    timestamp,
)
from coordination.errors import CoordinationError


def _ns(**values: object) -> argparse.Namespace:
    return argparse.Namespace(**values)


def test_parse_where_by_kind() -> None:
    assert parse_where(TASKS, "status:in=todo,review") == Filter(
        "status", "in", ("todo", "review")
    )
    assert parse_where(TASKS, "priority:le=2") == Filter("priority", "le", (2,))
    assert parse_where(TASKS, "id:eq=T-1") == Filter("id", "eq", ("T-1",))
    assert parse_where(TASKS, "updated_at:ge=2026-08-01T00:00:00+00:00").values == (
        "2026-08-01T00:00:00+00:00",
    )
    assert parse_where(TASKS, "title:ne=x").op == "ne"


@pytest.mark.parametrize(
    "raw",
    [
        "status=todo",  # no operator
        "nope:eq=1",  # unknown column
        "status:ge=todo",  # operator not allowed for enum
        "status:eq=bogus",  # value not a choice
        "priority:eq=high",  # not an int
        "updated_at:ge=yesterday",  # not a timestamp
        "title:in=a,b",  # text does not support in
        "id:in=bad id",  # not an identifier
        "id:eq=",  # empty identifier
    ],
)
def test_parse_where_rejects_what_the_descriptor_does_not_list(raw: str) -> None:
    with pytest.raises(CoordinationError) as caught:
        parse_where(TASKS, raw)
    assert caught.value.code == "invalid_arguments"
    assert caught.value.details["field"] == "where"


def test_parse_order_whitelist_and_direction() -> None:
    assert parse_order(TASKS, "priority") == ("priority", "asc")
    assert parse_order(TASKS, "updated_at:desc") == ("updated_at", "desc")
    for raw in ("description", "priority:sideways", "tags"):
        with pytest.raises(CoordinationError):
            parse_order(TASKS, raw)


def test_query_options_builds_parameterized_sql_with_deterministic_order() -> None:
    conditions, parameters, order = query_options(
        TASKS,
        _ns(
            where=["status:in=todo,review", "priority:le=2"],
            order_by=["priority:desc", "updated_at", "priority"],
            updated_since="2026-08-01T00:00:00+00:00",
        ),
    )
    assert conditions == ["t.status IN (?,?)", "t.priority <= ?", "t.updated_at >= ?"]
    assert parameters == ["todo", "review", 2, "2026-08-01T00:00:00+00:00"]
    assert order == "ORDER BY t.priority DESC, t.updated_at ASC, t.id ASC"
    assert query_options(TASKS, _ns()) == ([], [], None)
    assert query_options(TASKS, _ns(order_by=["id:desc"]))[2] == "ORDER BY t.id DESC"


def test_every_descriptor_is_well_formed() -> None:
    for name, descriptor in DESCRIPTORS.items():
        assert "id" in descriptor.columns and "id" in descriptor.orderable, name
        assert set(descriptor.orderable) <= set(descriptor.columns), name
        if descriptor.has_updated_at:
            assert "updated_at" in descriptor.columns, name


def test_timestamp_validator() -> None:
    assert timestamp("2026-08-23T10:11:12+00:00") == "2026-08-23T10:11:12+00:00"
    for bad in ("2026-08-23", "2026-08-23 10:11:12", "2026-08-23T10:11:12Z", "now"):
        with pytest.raises(argparse.ArgumentTypeError):
            timestamp(bad)
