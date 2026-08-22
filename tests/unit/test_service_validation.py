"""Unit coverage for transport-neutral parameter validation in the service layer."""

from __future__ import annotations

import pytest

from coordination.core import MAX_IDENTIFIER_ARRAY_ITEMS, identifier
from coordination.errors import EXIT_USAGE, CoordinationError
from coordination.service import (
    SERVICE_OPERATIONS,
    CoordinationService,
    _boolean,
    _choice,
    _choices,
    _identifiers,
    _integer,
    _optional,
    _optional_choice,
    _validate,
)


def _service() -> CoordinationService:
    return CoordinationService()


@pytest.mark.parametrize("value", [1, 1.0, True, None, [], {}, object()])
def test_validate_rejects_non_string_input(value: object) -> None:
    with pytest.raises(CoordinationError) as caught:
        _validate("actor", identifier, value)
    assert caught.value.code == "invalid_arguments"
    assert caught.value.exit_code == EXIT_USAGE
    assert caught.value.details == {"field": "actor"}


def test_validate_wraps_validator_failures_with_the_field_name() -> None:
    with pytest.raises(CoordinationError) as caught:
        _validate("actor", identifier, "not valid")
    assert caught.value.details == {"field": "actor"}
    assert caught.value.message.startswith("actor ")


def test_optional_passes_none_through() -> None:
    assert _optional("actor", identifier, None) is None
    assert _optional("actor", identifier, "josh") == "josh"


def test_choice_accepts_only_listed_values() -> None:
    assert _choice("status", "todo", ("todo", "done")) == "todo"
    with pytest.raises(CoordinationError) as caught:
        _choice("status", "archived", ("todo", "done"))
    assert caught.value.details == {"field": "status", "choices": ["todo", "done"]}


@pytest.mark.parametrize("value", [None, 1, True, ["todo"]])
def test_choice_rejects_non_string_input(value: object) -> None:
    if value is None:
        assert _optional_choice("status", None, ("todo",)) is None
        return
    with pytest.raises(CoordinationError):
        _choice("status", value, ("todo",))


def test_integer_enforces_inclusive_bounds() -> None:
    assert _integer("limit", 1, 1, 500) == 1
    assert _integer("limit", 500, 1, 500) == 500
    for out_of_range in (0, 501):
        with pytest.raises(CoordinationError) as caught:
            _integer("limit", out_of_range, 1, 500)
        assert caught.value.details["minimum"] == 1
        assert caught.value.details["maximum"] == 500


def test_integer_rejects_booleans_and_non_integers() -> None:
    """bool is an int subclass, so it needs an explicit guard."""
    for value in (True, False, 1.0, "1", None):
        with pytest.raises(CoordinationError) as caught:
            _integer("limit", value, 1, 500)
        assert caught.value.details["field"] == "limit"


def test_boolean_requires_a_real_boolean() -> None:
    assert _boolean("force", True) is True
    assert _boolean("force", False) is False
    for value in (1, 0, "true", None):
        with pytest.raises(CoordinationError):
            _boolean("force", value)


def test_identifiers_requires_a_list_of_valid_identifiers() -> None:
    assert _identifiers("assignees", ["a", "b"]) == ["a", "b"]
    assert _identifiers("assignees", []) == []
    with pytest.raises(CoordinationError) as caught:
        _identifiers("assignees", "not-a-list")
    assert caught.value.details == {"field": "assignees"}
    with pytest.raises(CoordinationError):
        _identifiers("assignees", ["valid", "not valid"])


def test_identifiers_enforces_the_array_cap() -> None:
    at_cap = [f"actor-{index}" for index in range(MAX_IDENTIFIER_ARRAY_ITEMS)]
    assert _identifiers("assignees", at_cap) == at_cap
    with pytest.raises(CoordinationError) as caught:
        _identifiers("assignees", [*at_cap, "actor-overflow"])
    assert caught.value.details["maximum"] == MAX_IDENTIFIER_ARRAY_ITEMS
    assert caught.value.details["actual"] == MAX_IDENTIFIER_ARRAY_ITEMS + 1


def test_service_rejects_unknown_operations() -> None:
    with pytest.raises(CoordinationError) as caught:
        _service().invoke("definitely_not_an_operation", {})
    assert caught.value.code == "invalid_arguments"
    assert caught.value.exit_code == EXIT_USAGE
    assert caught.value.details["operation"] == "definitely_not_an_operation"


@pytest.mark.parametrize(
    "operation",
    ["_args", "_validate", "__init__", "invoke", "invoke_cli"],
)
def test_service_refuses_to_dispatch_non_operations(operation: str) -> None:
    """Only the public operation registry is reachable over a transport."""
    assert operation not in SERVICE_OPERATIONS
    with pytest.raises(CoordinationError) as caught:
        _service().invoke(operation, {})
    assert caught.value.code == "invalid_arguments"


def test_service_operations_are_derived_from_the_class() -> None:
    """A new public method is exposed automatically, so the registry cannot drift."""
    assert "task_create" in SERVICE_OPERATIONS
    assert "backup" in SERVICE_OPERATIONS
    assert all(not name.startswith("_") for name in SERVICE_OPERATIONS)
    assert {"invoke", "invoke_cli"}.isdisjoint(SERVICE_OPERATIONS)


def test_service_reports_unusable_parameters_as_usage_errors() -> None:
    with pytest.raises(CoordinationError) as caught:
        _service().invoke("task_create", {"not_a_parameter": "x"})
    assert caught.value.code == "invalid_arguments"
    assert caught.value.exit_code == EXIT_USAGE
    assert caught.value.details["operation"] == "task_create"


def test_service_constructor_validates_its_own_arguments() -> None:
    with pytest.raises(CoordinationError) as caught:
        CoordinationService(session="not a session")
    assert caught.value.details == {"field": "session"}
    with pytest.raises(CoordinationError) as caught:
        CoordinationService(db="   ")
    assert caught.value.details == {"field": "db"}


def test_service_path_containment_is_off_by_default_and_validated() -> None:
    assert CoordinationService().contain_paths is False
    assert CoordinationService(contain_paths=True).contain_paths is True
    with pytest.raises(CoordinationError) as caught:
        CoordinationService(contain_paths="yes")  # type: ignore[arg-type]
    assert caught.value.code == "invalid_arguments"
    assert caught.value.details == {"field": "contain_paths"}


def test_choices_accepts_one_or_many_and_deduplicates() -> None:
    statuses = ("todo", "review", "done")
    assert _choices("status", None, statuses) is None
    assert _choices("status", "todo", statuses) == ["todo"]
    assert _choices("status", ["review", "todo", "review"], statuses) == [
        "review",
        "todo",
    ]
    assert _choices("status", [], statuses) is None


@pytest.mark.parametrize("value", [7, ["todo", "nope"], ("todo",), {"todo"}, [1]])
def test_choices_rejects_unlisted_or_non_list_values(value: object) -> None:
    with pytest.raises(CoordinationError) as caught:
        _choices("status", value, ("todo", "review"))
    assert caught.value.code == "invalid_arguments"
    assert caught.value.details["field"] == "status"
