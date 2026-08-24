"""Declarative read surface: which columns each entity may be filtered and
ordered by, and one predicate builder that accepts only what a descriptor
lists.

The whitelist is the capability boundary for the layers above the service
(ADR 0002 §5): a CLI flag or MCP field can name a column and an operator only
if the descriptor does, and values are validated by the column's kind before
they reach SQL. Transitions, claims, leases, and compare-and-swap stay in
hand-written entity code; this covers reads only.
"""

from __future__ import annotations


# fmt: off
# isort: off
from coordination.entities._descriptor_engine import (
    _coerce as _coerce, add_query_arguments as add_query_arguments,
    Column as Column, EntityDescriptor as EntityDescriptor, Filter as Filter,
    MAX_FILTER_INTEGER as MAX_FILTER_INTEGER,
    OPERATORS_BY_KIND as OPERATORS_BY_KIND, parse_order as parse_order,
    parse_where as parse_where, query_options as query_options,
    SQL_OPERATORS as SQL_OPERATORS, timestamp as timestamp,
    TIMESTAMP_PATTERN as TIMESTAMP_PATTERN,
)
from coordination.entities._descriptor_tables import (
    _ID as _ID, _TEXT as _TEXT, _TS as _TS, AGENTS as AGENTS,
    ARTIFACTS as ARTIFACTS, DECISIONS as DECISIONS, DESCRIPTORS as DESCRIPTORS,
    ESCALATIONS as ESCALATIONS, EVIDENCE as EVIDENCE, MESSAGES as MESSAGES,
    REVIEWS as REVIEWS, SESSIONS as SESSIONS, TASKS as TASKS,
)
# isort: on
# fmt: on
