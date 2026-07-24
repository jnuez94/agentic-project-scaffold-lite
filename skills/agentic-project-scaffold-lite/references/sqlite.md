# SQLite Adapter

Status: supported in version `1.1.0`.

Use SQLite when every participant operates on one local project directory.
It provides atomic updates, constraints, audit history, bounded health queries,
verified backups, and deterministic access without running a service.

Do not share the database between independent machines, network filesystems, or
Git clones. Do not commit live SQLite files.

## Requirements

- Python 3.10 or newer
- one local filesystem shared by every participating process
- POSIX advisory-lock and atomic same-directory replacement support
- write access to the project, `.coordination/`, and output directories
- no third-party Python runtime packages

Coordination records must not contain secrets, credentials, regulated data, or
unapproved proprietary data.

## Install

From a complete scaffold checkout:

```sh
./scripts/install.sh --target /path/to/project --adapter sqlite
./scripts/verify-install.sh /path/to/project
```

The installer creates or maintains:

```text
.coordination/
  README.md
  config.yml
  coordination.sqlite3
  backups/
.agents/agentic-project-scaffold-lite/
  VERSION
  bin/coordination
  lib/coordination/
  sqlite/schema.sql
  docs/cli-contract.md
```

The installed `bin/coordination` launcher imports only its sibling
`lib/coordination` package. That package is copied from the repository root
`coordination/` directory, which is the sole implementation. Harness-specific
instructions contain guidance only.

The installer adds an anchored ignore for the exact configured database path
and its sidecars, plus the backup directory, to `.gitignore`; this applies even
when the database uses a nested path or a suffix other than `.sqlite3`.
Reinstalling the same backend repairs managed files and blocks without
replacing coordination state. It rejects an incompatible existing backend, a
database path outside `.coordination/`, invalid destination types, and
destinations that would overlap the source checkout.

## Invoke

Run the installed executable from the project root:

```sh
tool=./.agents/agentic-project-scaffold-lite/bin/coordination
"$tool" version
"$tool" doctor
```

Without `--db`, the CLI searches the current directory and its parents for the
nearest `.coordination/config.yml`. Every participant must resolve to the same
configured database.

Successful machine commands return one `{"ok": true, "data": ...}` JSON value
on standard output. Expected failures return one
`{"ok": false, "error": ...}` value on standard error and a documented
nonzero exit code. The installed machine contract is
`.agents/agentic-project-scaffold-lite/docs/cli-contract.md`.

## Actor And Session Model

An actor is the durable accountable principal. Keep its ID stable when its
harness or model changes.

- `agents.id`: stable identity
- `agents.actor_type`: `ai`, `human`, or `service`
- `agents.role`: project responsibility
- `agent_sessions.harness`: execution environment for one run
- `agent_sessions.model`: optional model for one run
- `agent_sessions.id`: unique execution session

```sh
"$tool" agent add \
  --id engineering-1 \
  --name "Engineering 1" \
  --role engineering \
  --actor-type ai

"$tool" session start \
  --id engineering-1-run-001 \
  --agent engineering-1 \
  --harness local-agent \
  --model model-name

export COORDINATION_SESSION=engineering-1-run-001
```

All mutations have an accountable active actor. Some commands identify it
through a domain option such as `--owner`, `--reviewer`, or `--sender`; others
require `--actor`; session heartbeat and normal end derive it from the session
record. When a global session is supplied, it must be active and belong to the
mutation actor.

## Task Workflow

```sh
"$tool" task create \
  --id TASK-001 \
  --title "Implement feature" \
  --actor engineering-1 \
  --assignee engineering-1 \
  --acceptance "Tests pass"

"$tool" --session engineering-1-run-001 task claim TASK-001 \
  --agent engineering-1 \
  --if-revision 1

"$tool" --session engineering-1-run-001 evidence add \
  --task TASK-001 \
  --uri "test://suite-passed" \
  --type test \
  --actor engineering-1

"$tool" --session engineering-1-run-001 task status TASK-001 review \
  --actor engineering-1 \
  --if-revision 2
```

Assignments are planning metadata. A claim is exclusive. Claim and status
operations require the last observed revision, and each success increments it.
Leaving `in_progress` removes the claim. A session cannot end while it owns a
claim. Transitioning to `done` requires evidence.

## Concurrency And Limits

Initialized connections enforce foreign keys, WAL journal mode, and `FULL`
synchronous durability. Mutations use short immediate transactions. Advisory
file locks coordinate ordinary access with maintenance operations.

`COORDINATION_BUSY_TIMEOUT_MS` defaults to `5000` and accepts `0` through
`60000`. A timeout returns `database_busy` with exit code `6` and no partial
mutation.

List commands accept `--limit` (default `100`, maximum `500`) and `--offset`
(default `0`). Identifiers are at most 128 ASCII characters from the documented
token alphabet, text is at most 65,536 characters, and paths are at most 4,096
characters. Required text and paths cannot be empty or whitespace-only; text
and paths cannot contain NUL.

## Health And Diagnostics

```sh
"$tool" doctor
"$tool" health \
  --stale-days 7 \
  --stale-session-minutes 60 \
  --limit 100
```

`doctor` validates installation, exact schema identity, database integrity,
foreign keys, coordination invariants, durability settings, timeout
configuration, and filesystem writability.

Each health section is capped independently at `--limit`.
`truncated_sections` names every section with additional rows.

## Backup Runbook

```sh
backup=.coordination/backups/coordination-20260723.sqlite3
"$tool" backup --output "$backup"
```

Backup validates schema identity, integrity, foreign keys, and coordination
invariants, then atomically publishes a mode-`0600` file. It refuses to
overwrite by default, including when two processes race to the same new path.
Confirm `data.verified` is `true`.

## Restore Runbook

Restore replaces the configured database:

1. Stop other writers.
2. End or recover every active session.
3. Verify the input path and active restore actor.
4. Restore with explicit confirmation.
5. Require verification, audit, safety-backup, publication, and rollback
   results to describe a successful atomic publication.
6. Run `doctor`.
7. Retain the safety backup until the restored state is accepted.

```sh
"$tool" restore \
  --input .coordination/backups/coordination-20260723.sqlite3 \
  --actor product-owner \
  --force
"$tool" doctor
```

After path validation, restore takes an exclusive operational lock covering
input verification through final checks. Under that lock it validates the
input, rejects active target sessions, creates and verifies a pre-restore
safety backup, inserts and verifies the restore audit in staged state, and
atomically publishes it. Target database contents remain unchanged until
publication. A successful result reports
`publication: "atomic_replace"`, `audit_recorded: true`,
`rollback_performed: false`, and `verified: true`.

If an existing target is unreadable, restore preserves its database and
available sidecars byte-for-byte and reports
`safety_backup_verified: false`; raw preservation is not described as a
verified SQLite backup.

Expected failures before publication leave the target unchanged. If
post-publication verification fails, restore rolls back from the safety state
and reports the rollback outcome. Preserve every reported recovery file after
an unsuccessful or ambiguous operation.

## Session Recovery

```sh
"$tool" session recover engineering-1-run-001 \
  --actor product-owner \
  --reason "Worker stopped before releasing its claim" \
  --stale-after-seconds 3600
```

The reason must contain non-whitespace text. Recovery atomically blocks claimed
tasks, increments their revisions, appends the reason, removes claims, ends the
stale session, and records audit entries.

## Schema Compatibility

SQLite schema version 1 is the first supported schema. Version 1.1.0 has no
migration framework and does not upgrade pre-release databases. `init` creates
an empty version 1 database or verifies an exact existing version 1 database;
it refuses incomplete, older, newer, or definition-mismatched schemas.

Back up any pre-release data, install into a clean project, and recreate
approved coordination records through the CLI.
