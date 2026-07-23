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

`COORDINATION_BUSY_TIMEOUT_MS` controls how long a process waits for SQLite's
writer lock. It defaults to `5000` and accepts integers from `0` through
`60000`.

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
journal mode, coordination claim invariants, and filesystem writability. A
successful check reports `integrity_check`, `foreign_key_check`, and
`coordination_invariants` as `ok`.

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

Every task starts at revision `1`. `task claim` and `task status` require the
revision last observed by the caller through `--if-revision`. A mismatch fails
with `stale_task_revision` and reports both the expected and actual revisions.
Each successful claim or status transition increments the revision.

Assignments identify planned collaborators and are not exclusive. An active
claim is exclusive and belongs to one active agent session:

- `task claim` requires `--session`, `--agent`, and `--if-revision`
- only one concurrent claimant can succeed
- claiming is the only way to enter `in_progress`
- only the claiming agent and session may transition an `in_progress` task
- leaving `in_progress` removes the active claim
- a session with an active claim cannot end
- an agent with an active session cannot be deactivated

The same claimant may safely retry a claim with the original revision. If the
first attempt committed, the retry succeeds with `idempotent_replay: true`
without changing the task again.

All mutations against an initialized coordination database use short
`BEGIN IMMEDIATE` transactions. Competing writers therefore observe committed
state before evaluating preconditions. If the configured wait expires, the CLI
returns `database_busy` with exit code `6` and no partial database mutation.
Initialized database connections use WAL journal mode and SQLite `FULL`
synchronous durability.

## Recovery And Durability

`session recover` is the explicit crash-recovery path. It only accepts an
active session whose `last_seen_at` is at or before the requested stale
threshold. Recovery atomically:

- moves each task claimed by that session from `in_progress` to `blocked`
- increments each affected task revision
- appends the required recovery reason to task notes
- removes the active claims
- ends the stale session
- records task and session recovery audit entries under the recovery actor

The default stale threshold is 3600 seconds. Callers may set
`--stale-after-seconds` to a non-negative value.

`backup` writes through a temporary file in the destination directory. It
validates schema identity, SQLite integrity, foreign keys, and coordination
invariants before atomically replacing the destination. A successful result
contains `verified: true`; new backup files use mode `0600`.

`restore` requires `--force` and `--actor`. It validates the input before
changing the target and refuses to run while the current target has active
sessions. When the current target is healthy, it first writes a verified
pre-restore backup under `.coordination/backups/`. It then restores through
SQLite's online backup API, validates the result, and records a restore audit
entry. If the current target is unreadable, restore preserves its database and
available WAL sidecars as an explicitly unverified safety copy before
atomically replacing it with the verified input. The result distinguishes this
case with `safety_backup_verified: false`. All other coordination processes
should remain stopped until the command completes.

Markdown file export also uses temporary-file replacement, so an interrupted
export does not leave a partially written requested output.

## Retry And Idempotency

- query commands, `version`, and `doctor` are safe to retry
- `init` is safe to retry only against an empty or complete supported database
- `session heartbeat` is safe to retry
- `task claim` is safe to retry with the same agent, session, and original
  revision
- retrying `task status` with an already-consumed revision returns
  `stale_task_revision` and does not apply the transition twice
- `export` and `backup` refuse to overwrite by default
- `restore` is destructive, requires explicit confirmation, and is not
  idempotent
- other create, send, add, resolve, update, and session lifecycle mutations are
  not generally idempotent

Callers must inspect the result after an interrupted mutation before retrying.

## Stable Command Surface

- `init`
- `version`
- `doctor`
- `agent add|list|update`
- `session start|list|heartbeat|end|recover`
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
- `restore`
