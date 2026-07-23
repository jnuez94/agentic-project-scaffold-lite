# SQLite Adapter

Status: experimental implementation in version `1.1.0-alpha.1`.

SQLite is the recommended structured backend when all participating agents use the same local project directory. It provides atomic updates, constraints, audit history, health queries, and deterministic access without running a service.

## Install

```sh
./scripts/install.sh --target /path/to/project --adapter sqlite
```

The installer requires Python 3 and creates:

```text
.coordination/
  config.yml
  coordination.sqlite3
  backups/
.agents/agentic-project-scaffold-lite/
  bin/coordination
  sqlite/schema.sql
```

The database and backup directory are added to the target project's `.gitignore`. Do not commit a changing SQLite database or share it between independent Git clones.

## Agent Interface

Agents and humans must use the installed deterministic CLI instead of editing the database directly:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination --help
```

The CLI emits JSON for state-changing and query commands so agents can consume results reliably.

The machine-readable output, error, exit-code, schema, and task-status
guarantees are defined in the [Coordination CLI Contract](../cli-contract.md).

## Implementation Layout

The executable is a thin dispatcher. Behavior is split by coordination entity:

```text
coordination/
  core.py
  cli.py
  entities/
    agents.py
    sessions.py
    tasks.py
    evidence.py
    dependencies.py
    reviews.py
    decisions.py
    messages.py
    artifacts.py
    escalations.py
    maintenance.py
    reports.py
```

Entity modules own their commands and parser registration. Shared database discovery, connections, timestamps, audit logging, and JSON output remain in `core.py`.

This root package is the sole implementation source. Harness-specific guidance packages may explain how to use it, but they do not vendor another runtime copy.

## Typical Workflow

```sh
coordination agent add \
  --id engineering-1 \
  --name "Engineering Agent" \
  --actor-type ai \
  --role engineering

coordination agent add \
  --id security-reviewer \
  --name "Security Reviewer" \
  --actor-type ai \
  --role security

coordination session start \
  --id engineering-1-codex-001 \
  --agent engineering-1 \
  --harness codex \
  --model gpt-5

coordination session start \
  --id security-reviewer-claude-001 \
  --agent security-reviewer \
  --harness claude \
  --model claude

coordination --session engineering-1-codex-001 task create \
  --id TASK-001 \
  --title "Implement feature" \
  --actor engineering-1 \
  --assignee engineering-1 \
  --acceptance "Tests pass"

coordination --session engineering-1-codex-001 task claim TASK-001 --agent engineering-1 --if-revision 1
coordination --session engineering-1-codex-001 evidence add --task TASK-001 --uri "test://suite-passed" --type test --actor engineering-1
coordination --session engineering-1-codex-001 task status TASK-001 review --actor engineering-1 --if-revision 2
coordination --session security-reviewer-claude-001 review add \
  --id REV-001 \
  --task TASK-001 \
  --reviewer security-reviewer \
  --artifact src/feature \
  --scope "Security review" \
  --decision accepted
coordination --session engineering-1-codex-001 task status TASK-001 done --actor engineering-1 --if-revision 3
coordination session end engineering-1-codex-001
coordination session end security-reviewer-claude-001
```

The installed executable is normally invoked with its full project-relative path. The shorter `coordination` form above assumes the user has added the tool to `PATH` or created a shell alias.

Actor IDs identify durable accountable participants. `--actor-type` distinguishes `ai`, `human`, and `service` participants, while sessions record the harness and model used for a particular run. Do not encode `codex` or `claude` in a durable actor ID unless the harness is intentionally part of that participant's permanent identity.

The global `--session ID` option must appear before the entity command. `COORDINATION_SESSION` provides the same attribution without repeating the option.

## Available Commands

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

Run any command with `--help` for complete arguments.

## Enforcement

The schema enforces:

- stable unique IDs
- canonical task and review statuses
- valid priority values
- foreign-key relationships
- valid dependency types
- evidence before a task can transition to `done`
- exclusive task claims tied to active execution sessions
- optimistic task revisions that reject stale status changes
- append-only audit entries for CLI mutations
- actor types and session states
- session-aware audit attribution that rejects actor/session mismatches

The CLI uses immediate write transactions, foreign keys, a configurable busy
timeout, SQLite's write-ahead log, and `FULL` synchronous durability for safe
local coordination. Set `COORDINATION_BUSY_TIMEOUT_MS` to an integer from `0`
through `60000`; the default is `5000`.

Task assignments are planning metadata and may name multiple collaborators.
`task claim` establishes the single active owner. Claims require an active
session and the task revision last returned by `task create`, `task show`, or
`task list`. Each successful claim or status transition increments that
revision. Use `task claim`, not `task status`, to enter `in_progress`.

## Initial Schema

The experimental SQLite adapter has not shipped a previously supported schema. Actor types, execution sessions, and session-aware audits are therefore defined directly in the initial schema version 1.

## Reports And Backups

```sh
coordination health --stale-days 7
coordination export --output coordination-report.md
coordination backup --output .coordination/backups/coordination-20260722.sqlite3
coordination restore \
  --input .coordination/backups/coordination-20260722.sqlite3 \
  --actor product-owner \
  --force
```

Markdown exports are reports, not a second source of coordination truth.
Backups are verified before atomic publication. Restore validates its input,
refuses targets with active sessions, creates a pre-restore safety backup, and
requires explicit `--force` confirmation. Stop other coordination processes
until restore completes. An unreadable target is preserved as an unverified
database-plus-WAL safety copy before replacement.

If a harness stops while holding a task claim, recover it after the agreed
stale threshold:

```sh
coordination session recover engineering-1-codex-001 \
  --actor product-owner \
  --reason "Harness stopped unexpectedly" \
  --stale-after-seconds 3600
```

Recovery blocks claimed work, increments task revisions, ends the session, and
records the intervention in the audit log.

## Limitations

- All agents must access the same local database file.
- The database is not suitable for independent machines or Git clones.
- SQLite serializes concurrent writes; long-running transactions should be avoided.
- A session cannot end while it owns an active task claim; move the task out
  of `in_progress` first.
- Compatibility and upgrade guarantees must be defined before the SQLite adapter is promoted from experimental status.
- The CLI enforces evidence for `done`, but project-specific review requirements still depend on configured decision rights.
