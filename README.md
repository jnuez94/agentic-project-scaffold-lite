# Agentic Project Scaffold Lite

A harness-agnostic operating model for coordinating multiple AI or human-assisted agents on the same project.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Repository: [jnuez94/agentic-project-scaffold-lite](https://github.com/jnuez94/agentic-project-scaffold-lite)

This project is a portable framework. It does not require a specific agent runtime, chat tool, IDE, database, issue tracker, or repository host.

The core idea is simple:

> Multi-agent work needs a durable coordination contract: roles, tasks, messages, reviews, decisions, dependencies, artifacts, evidence, and clear authority.

## Install Into A Project

Clone or download this repository, then run:

```sh
./scripts/install.sh --target /path/to/your/project --adapter markdown
```

From inside a checkout next to the target project, for example:

```sh
git clone --depth 1 https://github.com/jnuez94/agentic-project-scaffold-lite.git
./agentic-project-scaffold-lite/scripts/install.sh --target ./my-project
```

The installer adds:

- `AGENTS.md`, containing the operating contract agents read automatically
- `.agents/agentic-project-scaffold-lite/`, containing the specification and guidance
- `.coordination/`, containing record directories and copyable templates

Installation is idempotent. Existing `AGENTS.md` content is preserved and the scaffold guidance is appended once. Use `--no-agents-file` when a project manages its root instructions separately.

Choose a coordination backend at installation:

```sh
# Transparent, Git-friendly records
./scripts/install.sh --target /path/to/project --adapter markdown

# Structured, transactional coordination for one local project directory
./scripts/install.sh --target /path/to/project --adapter sqlite
```

Both backends are supported in version 1.1.0; Markdown remains the default.
The SQLite backend requires Python 3.10 or newer and installs a deterministic,
JSON-emitting CLI backed by a project-local database. Durable actor identity is
separate from AI, human, or service type, while each execution session records
its harness and model. Codex, Claude, people, and services all invoke the same
installed executable and database. The installer refuses to switch an existing
project silently between backends.

| Backend | Best For | State Interface |
| --- | --- | --- |
| Markdown | Small teams, direct inspection, Git history | Files under `.coordination/` |
| SQLite | Multiple local agents, validation, queries, atomic writes | Installed `coordination` CLI |

Verify an installed project with:

```sh
./scripts/verify-install.sh /path/to/your/project
```

Run the repository's installation and skill checks with:

```sh
make test
make validate-skill
```

## Install As A Codex Skill

The native skill package lives at `skills/agentic-project-scaffold-lite/`. Install that directory with Codex's skill installer, or ask Codex:

```text
Install the agentic-project-scaffold-lite skill from
https://github.com/jnuez94/agentic-project-scaffold-lite/tree/main/skills/agentic-project-scaffold-lite
```

The skill supports project initialization, ongoing coordination, evidence-based task closure, decision-rights setup, and coordination-health audits.

The skill is guidance-only. Executable Markdown and SQLite installation always
comes from the harness-neutral repository root; the skill does not carry a
Codex-specific copy of the runtime. The root `coordination/` package is the
single source copied into every SQLite installation.

## Who This Is For

Use this model if you are:

- running a project with multiple AI agents
- coordinating AI agents and human reviewers
- using specialized agents for product, design, engineering, security, QA, research, or documentation
- trying to avoid duplicated work, hidden decisions, stale assumptions, and premature completion claims
- building in a regulated, security-sensitive, customer-facing, or production-critical environment

## What This Includes

```text
agentic-project-scaffold-lite/
  README.md
  SPEC.md
  QUICKSTART.md
  PROJECT_BOOTSTRAP.md
  GOVERNANCE.md
  CONTRIBUTING.md
  CODE_OF_CONDUCT.md
  OPEN_SOURCE_READINESS.md
  SECURITY.md
  LICENSE
  CHANGELOG.md
  RELEASING.md
  coordination/
    README.md
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
      sessions.py
      diagnostics.py
      maintenance.py
      reports.py
  sqlite/
    schema.sql
  docs/
    adapters/
      markdown.md
      sqlite.md
      issue_tracker.md
    decision-rights.md
    health-metrics.md
    cli-contract.md
  templates/
    agent_profile.md
    task.md
    message.md
    review.md
    decision_record.md
    artifact_record.md
    escalation.md
    dependency.md
  checklists/
    startup_checklist.md
    conformance_checklist.md
    release_readiness_checklist.md
  examples/
    four-agent-team/
      team.md
      initial_tasks.md
```

See [coordination/README.md](coordination/README.md) for the current SQLite
runtime architecture, installation boundary, and actor identity model.
See [docs/cli-contract.md](docs/cli-contract.md) for the stable CLI
output, error, exit-code, schema, and task-status guarantees.

## Fast Start

1. Read [QUICKSTART.md](QUICKSTART.md).
2. Copy the templates in [templates/](templates/) into your project.
3. Use the installed Markdown records or the SQLite `coordination` CLI as the
   project's one source of truth.
4. Create agent profiles.
5. Create initial tasks.
6. Define who can approve scope, release, external use, production, and sensitive-data access.
7. Start each agent loop with: sync, select work, announce intent if needed, produce evidence, request review, close only with evidence.

## Moving This Into A New Project

Copy this whole directory into a new repository or workspace, then start with:

- [QUICKSTART.md](QUICKSTART.md) for adoption steps
- [PROJECT_BOOTSTRAP.md](PROJECT_BOOTSTRAP.md) for a ready-to-use startup prompt
- [checklists/startup_checklist.md](checklists/startup_checklist.md) for first-session setup
- [templates/](templates/) for reusable working records

The framework is designed to be copied as a directory first, then renamed, edited, and expanded inside the new project.

## Core Concepts

- **Coordination substrate**: the durable place where tasks, messages, reviews, decisions, dependencies, and evidence live.
- **Agent profile**: a role definition with responsibilities, authority, and operating style.
- **Task**: the unit of accountable work.
- **Review**: scoped acceptance or rejection from a role-specific lens.
- **Decision record**: durable rationale for an important choice.
- **Evidence**: proof that work is complete or ready for review.
- **Blocked claim**: something the work explicitly does not approve.

## Harness-Agnostic Contract

Any tool can implement this model if it supports:

- persistent tasks
- persistent messages or comments
- agent or role identity
- artifact references
- status updates
- timestamped history
- review records or equivalent comments
- dependency tracking or dependency notes

The implementation can be as light as markdown or as structured as a database-backed bus.

## Status Model

Use one canonical status set:

| Status | Meaning |
| --- | --- |
| `todo` | Work is identified but not actively started. |
| `in_progress` | An agent is actively working on it. |
| `review` | Work exists and is waiting for review. |
| `blocked` | Work cannot proceed without a named dependency, decision, or external event. |
| `done` | Work is complete and supported by evidence. |

Use `done` as the only terminal success state.

## Design Philosophy

This framework favors:

- explicit ownership
- durable decisions
- evidence-based completion
- small strict status vocabulary
- role-scoped reviews
- clear blocked claims
- sensitive-data hygiene
- portability across agent harnesses

It rejects:

- chat memory as source of truth
- vague ownership
- "done" without evidence
- hidden launch or production claims
- coordination records that accidentally store sensitive data

## Open Source Notes

This MIT-licensed seed includes governance, contribution, security, code-of-conduct, and readiness notes. It deliberately does not require GitHub, GitLab, Linear, Jira, Codex, or any other specific platform.

## Current Status

Version 1.1.0 supports both the Markdown installation path and the
harness-neutral SQLite coordination CLI. SQLite schema version 1 is the first
supported database schema; there are no migrations from pre-release databases.
See [CHANGELOG.md](CHANGELOG.md) for release notes and
[RELEASING.md](RELEASING.md) for release qualification.

The project is licensed under the [MIT License](LICENSE).
