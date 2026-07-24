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

The configured database value may use ordinary nested directories, but it must
be relative and cannot contain `..` or another `.coordination` component.
Its first component cannot be the managed `config.yml`, `README.md`, or
`backups` name. Nested `.coordination` and managed-root reservations are
case-insensitive.
Any explicit alternate database inside that coordination root must have a
fully disjoint main, WAL, shared-memory, journal, and advisory-lock namespace.
Installer and verifier accept the same scalar configuration grammar as the
runtime. They canonicalize the target to its physical directory, reject a
final target symbolic link (including trailing slash or `/.` aliases), reject
hard-linked managed destinations, and preserve host-file modes during atomic
managed-block repair. Verification compares the complete selected bundle,
adapter-specific AGENTS block, managed coordination README, managed
`.gitignore` block, configured database, and live CLI diagnostics with the
canonical source. Reinstall repairs a missing or damaged managed coordination
README.

## Invoke

Run the installed executable from the project root:

```sh
tool=./.agents/agentic-project-scaffold-lite/bin/coordination
"$tool" version
"$tool" doctor
```

Without `--db`, the CLI searches the current directory and its parents for the
nearest `.coordination/config.yml`. Every participant must resolve to the same
configured database. Use the explicit global form when needed:

```sh
"$tool" --db /path/to/project/.coordination/coordination.sqlite3 COMMAND
```

Successful machine commands return one `{"ok": true, "data": ...}` JSON value
on standard output. Expected failures return one
`{"ok": false, "error": ...}` value on standard error and a documented
nonzero exit code. The exact public interface is in the
[CLI contract](../cli-contract.md).

## Actor And Session Model

An actor is the durable accountable principal. Keep its ID stable when its
harness or model changes.

- `agents.id`: stable identity
- `agents.actor_type`: `ai`, `human`, or `service`
- `agents.role`: project responsibility
- `agent_sessions.harness`: execution environment for one run
- `agent_sessions.model`: optional model for one run
- `agent_sessions.id`: unique execution session

Example:

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

All mutations have an accountable active actor. Some commands identify that
actor through a domain option such as `--owner`, `--reviewer`, or `--sender`;
others require `--actor`; session heartbeat and normal end derive it from the
session record. When a global session is supplied, it must be active and belong
to the mutation actor.

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

Assignments are planning metadata and may contain multiple actors. A claim is
the exclusive active owner. Claim and status operations require the revision
last observed by the caller. A successful claim or status transition
increments it. Use `task claim`, not `task status`, to enter `in_progress`.

Leaving `in_progress` removes the claim. A session cannot end while it owns a
claim. Transitioning to `done` requires evidence.

## Concurrency And Limits

Initialized connections enforce foreign keys, WAL journal mode, and `FULL`
synchronous durability. Mutations use short immediate transactions. Advisory
file locks coordinate ordinary access with maintenance operations.

Set `COORDINATION_BUSY_TIMEOUT_MS` to the maximum wait for a SQLite or advisory
lock:

```sh
COORDINATION_BUSY_TIMEOUT_MS=10000 "$tool" doctor
```

The default is `5000`; the valid range is `0` through `60000`. A timeout returns
`database_busy` with exit code `6` and no partial mutation.

List commands accept `--limit` (default `100`, maximum `500`) and `--offset`
(default `0`). Identifiers are at most 128 ASCII characters from the documented
token alphabet, text is at most 65,536 characters, and paths are at most 4,096
characters. Required text and paths cannot be empty or whitespace-only; text
and paths must contain valid Unicode scalar values and cannot contain NUL.

## Health And Diagnostics

Use `doctor` to validate installation, exact schema identity, database
integrity, foreign keys, coordination invariants, journal and synchronous
modes, timeout configuration, and filesystem writability:

```sh
"$tool" doctor
```

Use `health` for operational findings:

```sh
"$tool" health \
  --stale-days 7 \
  --stale-session-minutes 60 \
  --limit 100
```

Each health section is capped independently at `--limit`.
`truncated_sections` names every section with additional rows. Treat a section
as complete only when its name is absent from that array.

## Backup Runbook

Create backups only through the CLI:

```sh
backup=.coordination/backups/coordination-20260723.sqlite3
"$tool" backup --output "$backup"
```

Backup validates schema identity, integrity, foreign keys, and coordination
invariants, then atomically publishes a mode-`0600` file. It refuses to
overwrite by default, including when two processes race to the same new path.
It locks the destination database namespace and refuses existing SQLite
sidecars. Backup and file export cannot publish over any operational path of
the database configured by an enclosing coordination project, even when
`--db` explicitly selects an alternate database; configured-state replacement
is performed only by restore.
Use `--force` only when intentional:

```sh
"$tool" backup --output "$backup" --force
```

Confirm `data.verified` is `true` and retain the JSON result with operational
evidence.

## Restore Runbook

Restore replaces the configured database. Coordinate a maintenance window:

1. Stop other writers.
2. End or recover every active session.
3. Verify the input path and the active restore actor.
4. Run restore with explicit confirmation.
5. Require a successful JSON result whose verification, audit, safety-backup,
   publication, and rollback fields describe a fully published restore.
6. Run `doctor`.
7. Retain the pre-restore safety backup until the restored state is accepted.

```sh
"$tool" restore \
  --input .coordination/backups/coordination-20260723.sqlite3 \
  --actor product-owner \
  --force
"$tool" doctor
```

After path validation, restore takes an exclusive operational lock that covers
input verification, staging, publication, and final checks. Under that lock it
validates the input, rejects active target sessions, creates and verifies a
pre-restore safety backup, records restore intent in the replacement state
before publication, and atomically publishes the staged database. Target
database contents remain unchanged until the staged replacement is verified.
If post-publication validation fails, restore attempts an atomic rollback from
the safety backup and reports the rollback outcome.

If an existing target is unreadable, restore preserves its database and
available sidecars byte-for-byte and reports
`safety_backup_verified: false`; it does not mislabel raw preservation as a
healthy SQLite backup. No existing target produces null safety-backup fields.
For discovered project state the safety copy is written under the root
`.coordination/backups/`; for an explicit database outside a
`.coordination/` tree it is written under `backups/` beside the database.
Restore rejects any overlap between the source and target database, WAL,
shared-memory, journal, and advisory-lock namespaces.
It likewise rejects a restore input that reinterprets an enclosing project's
configured sidecar, journal, or lock as a database; the configured main
database itself remains a valid locked source.
An explicit restore target inside a coordination project also cannot alias the
managed configuration, README, or any operational path of that project's
configured database.

Do not delete the safety backup when the result is unsuccessful or ambiguous.
Inspect the error details, run `doctor`, and compare the configured database
with the reported safety and staged paths before another attempt.

## Session Recovery Runbook

If a process stops while it owns a claim, do not edit the database. After the
agreed stale threshold:

```sh
"$tool" session recover engineering-1-run-001 \
  --actor product-owner \
  --reason "Worker stopped before releasing its claim" \
  --stale-after-seconds 3600
```

The reason must contain non-whitespace text. Recovery atomically blocks claimed
tasks, increments their revisions, appends the reason to their notes, removes
the claims, ends the stale session, and records audit entries.

## Schema Compatibility

SQLite schema version 1 is the first supported schema. Version 1.1.0 has no
migration framework and does not upgrade pre-release databases. `init` creates
an empty version 1 database or verifies an exact existing version 1 database;
it refuses incomplete, older, newer, or definition-mismatched schemas.

Back up any pre-release data, install into a clean project, and recreate
approved coordination records through the CLI.

## Limits

- all participants must access the same local database file
- network filesystems and independent clones are unsupported
- SQLite serializes writers; keep transactions short
- Markdown exports are reports, not a second source of truth
- project-specific review policy remains separate from schema enforcement
