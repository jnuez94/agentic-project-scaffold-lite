# Coordination CLI Contract

Status: release candidate contract for the stable SQLite CLI planned for
version `1.1.0`.

This document defines the public machine interface for the harness-neutral
coordination CLI. MCP and other transports are outside this contract.

## Supported Environment

- one local machine
- one SQLite database shared by participating processes
- Python 3.10 or newer
- no third-party Python runtime dependencies
- trusted local operating-system users
- no secrets, credentials, regulated data, or unapproved proprietary data

The CLI does not provide network synchronization, authentication, or
authorization.

## Invocation

The installed executable is:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination
```

Global options must appear before the command:

```sh
coordination [--db PATH] [--session ID] COMMAND ...
```

`--db` selects an explicit database. Otherwise the CLI searches the current
directory and its parents for `.coordination/config.yml`.

`--session` attributes a mutation to an active execution session. The
`COORDINATION_SESSION` environment variable provides the default.

## Output

Successful machine-readable commands write one JSON value to standard output:

```json
{
  "ok": true,
  "data": {}
}
```

Expected failures write one JSON value to standard error and do not write a
success value:

```json
{
  "ok": false,
  "error": {
    "code": "stable_snake_case_code",
    "message": "Human-readable explanation",
    "details": {}
  }
}
```

`details` is omitted when no structured detail is available. Consumers must
branch on `error.code`, not on `message`.

The exceptions are:

- `--help`, which writes human-readable help
- `export` without `--output`, which writes a Markdown report

JSON key ordering and whitespace are not contractual. Field names and value
types are contractual after the stable release.

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Unexpected internal failure |
| `2` | Invalid arguments or input |
| `3` | Requested resource or database not found |
| `4` | State conflict or constraint violation |
| `5` | Installation, configuration, schema, database, or filesystem failure |
| `6` | SQLite lock or busy timeout |

## Schema Contract

The initial supported SQLite schema is version `1`. Both
`PRAGMA user_version` and `metadata.schema_version` must equal the supported
version. All tables, columns, indexes, and triggers defined by
`sqlite/schema.sql` are required schema objects; omitting any of them makes
the database incomplete.

`init` has exactly two valid outcomes:

- initialize an empty database as schema version 1
- verify an existing complete schema version 1 database and return `ready`

It refuses unknown, incomplete, mismatched, older, or newer schemas. This
release does not contain a migration framework because no earlier SQLite
schema was released.

`version` reports the CLI and supported schema versions without opening a
coordination database. `doctor` validates database discovery, schema identity,
required schema objects, integrity, foreign-key enforcement and consistency,
journal mode, and filesystem writability. A successful check reports both
`integrity_check` and `foreign_key_check` as `ok`.

## Task Status Contract

The canonical statuses are `todo`, `in_progress`, `review`, `blocked`, and
`done`.

Allowed transitions are:

| From | To |
| --- | --- |
| `todo` | `in_progress`, `blocked` |
| `in_progress` | `todo`, `review`, `blocked` |
| `review` | `in_progress`, `blocked`, `done` |
| `blocked` | `todo`, `in_progress` |
| `done` | none |

Transitioning to the current status is a conflict. Transitioning to `done`
requires at least one evidence record. Project-specific review requirements
remain policy rather than a schema constraint.

Exclusive claim and stale-update semantics are intentionally not declared
stable until the concurrency milestone is complete.

## Retry And Idempotency

- query commands, `version`, and `doctor` are safe to retry
- `init` is safe to retry only against an empty or complete supported database
- `session heartbeat` is safe to retry
- `export` and `backup` refuse to overwrite by default
- create, send, add, resolve, status, claim, update, and session lifecycle
  mutations are not generally idempotent

Callers must inspect the result after an interrupted mutation before retrying.
The concurrency milestone will define stronger retry behavior where required.

## Stable Command Surface

- `init`
- `version`
- `doctor`
- `agent add|list|update`
- `session start|list|heartbeat|end`
- `task create|list|show|claim|status`
- `evidence add|list`
- `dependency add|resolve`
- `review add|list`
- `decision add|list`
- `message send|list`
- `artifact add|list|status`
- `escalation add|list|resolve`
- `health`
- `export`
- `backup`
