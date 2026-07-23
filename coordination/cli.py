"""Top-level command parser and entity dispatcher."""

from __future__ import annotations

import argparse
import sqlite3
import sys

from coordination.core import connect, discover_db, emit, schema_path
from coordination.entities import (
    agents,
    artifacts,
    decisions,
    dependencies,
    escalations,
    evidence,
    messages,
    reports,
    reviews,
    tasks,
)


def command_init(args: argparse.Namespace) -> None:
    path = discover_db(args.db, for_init=True)
    connection = connect(path, require_initialized=False)
    with connection:
        connection.executescript(schema_path().read_text(encoding="utf-8"))
    emit({"database": str(path), "schema_version": 1, "status": "initialized"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coordination",
        description="Local multi-agent coordination backed by SQLite",
    )
    parser.add_argument("--db", help="Path to coordination.sqlite3; otherwise discover the nearest project")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Initialize the database")
    init.set_defaults(func=command_init)

    for entity in (
        agents,
        tasks,
        evidence,
        dependencies,
        reviews,
        decisions,
        messages,
        artifacts,
        escalations,
        reports,
    ):
        entity.register(commands)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except sqlite3.IntegrityError as error:
        print(f"Coordination constraint failed: {error}", file=sys.stderr)
        return 2
    return 0
