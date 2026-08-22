"""Every CLI subcommand must dispatch to a service operation whose parameters
the parsed namespace can satisfy.

`CoordinationService.invoke_cli` builds the operation name from the command
and subcommand, then reads one namespace attribute per service parameter. A
parser `dest` that does not match a service parameter name is a KeyError at
runtime, reported as `internal_error` -- a defect no contract test notices
until a user runs that exact subcommand. This walks the whole parser once.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
import inspect

from coordination.cli import build_parser
from coordination.service import SERVICE_OPERATIONS, CoordinationService


GLOBAL_DESTS = {"db", "session", "command"}


def _leaves(
    parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], argparse.ArgumentParser]]:
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            nested = [
                a for a in sub._actions if isinstance(a, argparse._SubParsersAction)
            ]
            if nested:
                yield from _leaves(sub, (*prefix, name))
            else:
                yield (*prefix, name), sub


def test_every_cli_subcommand_maps_to_a_satisfiable_service_operation() -> None:
    seen: set[str] = set()
    for path, sub in _leaves(build_parser()):
        command = path[0].replace("-", "_")
        operation = (
            f"{command}_{path[1].replace('-', '_')}" if len(path) > 1 else command
        )
        seen.add(operation)
        method = getattr(CoordinationService, operation, None)
        assert method is not None, f"{' '.join(path)} has no service operation"
        assert operation in SERVICE_OPERATIONS, operation
        dests = {a.dest for a in sub._actions if a.dest != "help"}
        dests |= GLOBAL_DESTS | {f"{command}_command"}
        parameters = [
            name for name in inspect.signature(method).parameters if name != "self"
        ]
        missing = [name for name in parameters if name not in dests]
        assert not missing, (
            f"{' '.join(path)}: service parameters {missing} have no parser dest"
        )
    assert len(seen) >= 40, f"only {len(seen)} subcommands walked"


def test_service_operations_without_a_cli_are_the_known_transport_only_ones() -> None:
    cli_operations: set[str] = set()
    for path, _ in _leaves(build_parser()):
        command = path[0].replace("-", "_")
        cli_operations.add(
            f"{command}_{path[1].replace('-', '_')}" if len(path) > 1 else command
        )
    assert SERVICE_OPERATIONS - cli_operations == {"project_status"}
