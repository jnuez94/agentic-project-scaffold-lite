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

## Implementation Layout

The executable is a thin dispatcher. Behavior is split by coordination entity:

```text
coordination/
  core.py
  cli.py
  entities/
    agents.py
    tasks.py
    evidence.py
    dependencies.py
    reviews.py
    decisions.py
    messages.py
    artifacts.py
    escalations.py
    reports.py
```

Entity modules own their commands and parser registration. Shared database discovery, connections, timestamps, audit logging, and JSON output remain in `core.py`.

This root package is the sole implementation source. Harness-specific guidance packages may explain how to use it, but they do not vendor another runtime copy.

## Typical Workflow

```sh
coordination agent add --id engineering --name "Engineering Agent" --role engineering

coordination task create \
  --id TASK-001 \
  --title "Implement feature" \
  --actor engineering \
  --assignee engineering \
  --acceptance "Tests pass"

coordination task claim TASK-001 --agent engineering
coordination evidence add --task TASK-001 --uri "test://suite-passed" --type test --actor engineering
coordination task status TASK-001 review --actor engineering
coordination review add \
  --id REV-001 \
  --task TASK-001 \
  --reviewer security \
  --artifact src/feature \
  --scope "Security review" \
  --decision accepted
coordination task status TASK-001 done --actor engineering
```

The installed executable is normally invoked with its full project-relative path. The shorter `coordination` form above assumes the user has added the tool to `PATH` or created a shell alias.

## Available Commands

- `agent add|list`
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

Run any command with `--help` for complete arguments.

## Enforcement

The schema enforces:

- stable unique IDs
- canonical task and review statuses
- valid priority values
- foreign-key relationships
- valid dependency types
- evidence before a task can transition to `done`
- append-only audit entries for CLI mutations

The CLI uses transactions, foreign keys, a busy timeout, and SQLite's write-ahead log for safe local coordination.

## Reports And Backups

```sh
coordination health --stale-days 7
coordination export --output coordination-report.md
coordination backup --output .coordination/backups/coordination-20260722.sqlite3
```

Markdown exports are reports, not a second source of coordination truth.

## Limitations

- All agents must access the same local database file.
- The database is not suitable for independent machines or Git clones.
- SQLite serializes concurrent writes; long-running transactions should be avoided.
- Schema migrations must accompany future breaking database changes.
- The CLI enforces evidence for `done`, but project-specific review requirements still depend on configured decision rights.
