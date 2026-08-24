"""The filter and ordering engine over entity descriptors."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import re
from typing import Any

from coordination.core import (
    MAX_IDENTIFIER_ARRAY_ITEMS,
    identifier,
    optional_text,
)
from coordination.errors import EXIT_USAGE, fail


TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00\Z")

MAX_FILTER_INTEGER = 2_147_483_647

OPERATORS_BY_KIND: dict[str, tuple[str, ...]] = {
    "identifier": ("eq", "ne", "in"),
    "enum": ("eq", "ne", "in"),
    "text": ("eq", "ne"),
    "int": ("eq", "ne", "ge", "le"),
    "timestamp": ("ge", "le"),
}

SQL_OPERATORS = {"eq": "=", "ne": "<>", "ge": ">=", "le": "<="}


def timestamp(value: str) -> str:
    """Validate the contract's UTC ISO 8601 one-second timestamp form."""
    if TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "must be a UTC timestamp like 2026-08-23T10:11:12+00:00"
        )
    return value


@dataclass(frozen=True)
class Column:
    kind: str
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityDescriptor:
    name: str
    alias: str  # SQL alias prefix used by the list query, "" when none
    columns: dict[str, Column]
    orderable: tuple[str, ...]
    has_updated_at: bool = False

    def qualified(self, column: str) -> str:
        return f"{self.alias}.{column}" if self.alias else column


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    values: tuple[Any, ...] = field(default_factory=tuple)


def parse_where(descriptor: EntityDescriptor, raw: str) -> Filter:
    """Parse and validate one `COLUMN:OP=VALUE` filter against a descriptor."""
    head, separator, value = raw.partition("=")
    column, colon, op = head.partition(":")
    if not separator or not colon or not column or not op:
        fail(
            "invalid_arguments",
            "where must be COLUMN:OP=VALUE",
            EXIT_USAGE,
            {"field": "where", "value": raw},
        )
    spec = descriptor.columns.get(column)
    if spec is None:
        fail(
            "invalid_arguments",
            f"{descriptor.name} cannot be filtered by {column}",
            EXIT_USAGE,
            {
                "field": "where",
                "column": column,
                "columns": sorted(descriptor.columns),
            },
        )
    if op not in OPERATORS_BY_KIND[spec.kind]:
        fail(
            "invalid_arguments",
            f"{column} supports operators: {', '.join(OPERATORS_BY_KIND[spec.kind])}",
            EXIT_USAGE,
            {"field": "where", "column": column, "operator": op},
        )
    raw_values = value.split(",") if op == "in" else [value]
    if op == "in" and len(raw_values) > MAX_IDENTIFIER_ARRAY_ITEMS:
        fail(
            "invalid_arguments",
            f"{column} in-list may contain at most {MAX_IDENTIFIER_ARRAY_ITEMS} values",
            EXIT_USAGE,
            {"field": "where", "column": column, "maximum": MAX_IDENTIFIER_ARRAY_ITEMS},
        )
    values = tuple(_coerce(descriptor, column, spec, item) for item in raw_values)
    return Filter(column, op, values)


def _coerce(descriptor: EntityDescriptor, column: str, spec: Column, item: str) -> Any:
    try:
        if spec.kind == "identifier":
            return identifier(item)
        if spec.kind == "enum":
            if item not in spec.choices:
                raise argparse.ArgumentTypeError(
                    "must be one of: " + ", ".join(spec.choices)
                )
            return item
        if spec.kind == "text":
            return optional_text(item)
        if spec.kind == "int":
            number = int(item)
            if not -MAX_FILTER_INTEGER <= number <= MAX_FILTER_INTEGER:
                raise argparse.ArgumentTypeError("is out of range")
            return number
        return timestamp(item)
    except (argparse.ArgumentTypeError, ValueError) as error:
        fail(
            "invalid_arguments",
            f"{descriptor.name} {column} {error}",
            EXIT_USAGE,
            {"field": "where", "column": column, "value": item},
        )


def parse_order(descriptor: EntityDescriptor, raw: str) -> tuple[str, str]:
    column, _, direction = raw.partition(":")
    direction = direction or "asc"
    if column not in descriptor.orderable or direction not in ("asc", "desc"):
        fail(
            "invalid_arguments",
            f"{descriptor.name} may be ordered by: "
            + ", ".join(descriptor.orderable)
            + " with :asc or :desc",
            EXIT_USAGE,
            {"field": "order_by", "value": raw, "columns": list(descriptor.orderable)},
        )
    return column, direction


def query_options(
    descriptor: EntityDescriptor,
    args: argparse.Namespace,
) -> tuple[list[str], list[Any], str | None]:
    """Conditions, parameters, and an ORDER BY for one list invocation.

    Reads `where` (repeatable COLUMN:OP=VALUE), `order_by` (repeatable
    COLUMN[:asc|desc]), and `updated_since` (sugar for `updated_at:ge=`) off
    the parsed arguments when present. Ordering always ends with the id so it
    is deterministic.
    """
    conditions: list[str] = []
    parameters: list[Any] = []
    filters = [
        parse_where(descriptor, raw) for raw in (getattr(args, "where", None) or [])
    ]
    updated_since = getattr(args, "updated_since", None)
    if updated_since:
        filters.append(Filter("updated_at", "ge", (timestamp(updated_since),)))
    for item in filters:
        qualified = descriptor.qualified(item.column)
        if item.op == "in":
            placeholders = ",".join("?" for _ in item.values)
            conditions.append(f"{qualified} IN ({placeholders})")
        else:
            conditions.append(f"{qualified} {SQL_OPERATORS[item.op]} ?")
        parameters.extend(item.values)
    order_sql: str | None = None
    raw_orders = getattr(args, "order_by", None) or []
    if raw_orders:
        parts = []
        seen: set[str] = set()
        for raw in raw_orders:
            column, direction = parse_order(descriptor, raw)
            if column in seen:
                continue
            seen.add(column)
            parts.append(f"{descriptor.qualified(column)} {direction.upper()}")
        if "id" not in seen:
            parts.append(f"{descriptor.qualified('id')} ASC")
        order_sql = "ORDER BY " + ", ".join(parts)
    return conditions, parameters, order_sql


def add_query_arguments(
    parser: argparse.ArgumentParser,
    descriptor: EntityDescriptor,
) -> None:
    parser.add_argument(
        "--where",
        action="append",
        metavar="COLUMN:OP=VALUE",
        help=(
            "Repeatable filter; columns: "
            + ", ".join(sorted(descriptor.columns))
            + "; operators eq, ne, in, ge, le by column kind"
        ),
    )
    parser.add_argument(
        "--order-by",
        action="append",
        metavar="COLUMN[:asc|desc]",
        help="Repeatable ordering; columns: " + ", ".join(descriptor.orderable),
    )
    if descriptor.has_updated_at:
        parser.add_argument(
            "--updated-since",
            type=timestamp,
            help="Only rows with updated_at at or after this UTC timestamp",
        )
