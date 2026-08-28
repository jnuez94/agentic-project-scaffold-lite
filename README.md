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

Both backends are supported in version 2.0.0; Markdown remains the default.
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

## Intended Deployment

This scaffold is for **personal work**: one operator, one machine, one project
directory, and any number of harnesses, agents, people, and services that
operator runs as cooperating principals. It is not designed for shared hosts —
multi-user machines, cloud desktops, shared development servers, or network
filesystems — where a second human or an untrusted process can reach the
project directory. Actor identity is asserted and validated, not
authenticated, and the runtime's guarantees protect cooperating principals from
each other's mistakes and from injected instructions, not from a hostile
co-tenant. A shared-host-capable coordination layer is a separate product
offering. See [ADR 0001](docs/adr/0001-personal-single-operator-deployment.md).

Version 2.0.0 also offers MCP as an optional local `stdio` transport for the
SQLite backend. It uses the same installed `coordination/` service layer and
database as the CLI:

```sh
python3 -m pip install 'agentic-project-scaffold-lite[mcp]==2.0.0'
./scripts/install.sh \
  --target /path/to/project \
  --adapter sqlite \
  --with-mcp
./scripts/verify-install.sh --with-mcp /path/to/project
```

The first command installs only the generic `coordination-mcp` console
bootstrap and the optional MCP SDK. The project installer remains responsible
for installing the canonical runtime. Default CLI installation has no
third-party dependency, and `--with-mcp` is rejected for Markdown.
For an agent without shell access, an operator must complete these steps and
register the server with the client before the agent starts; MCP cannot
bootstrap its own dependency.

Configure any MCP-capable local client to start the same generic server from
the project directory:

```json
{
  "command": "coordination-mcp",
  "args": []
}
```

This applies equally to Codex, Claude, and other clients; the installer never
edits client-specific configuration. Each harness starts its own execution
session, while durable actor IDs remain values such as `engineering`,
`reviewer`, or `owner`. See the [MCP contract](docs/mcp-contract.md).

Verify an installed project with:

```sh
./scripts/verify-install.sh /path/to/your/project
```

For an existing Markdown or SQLite project, including a 1.1.0 SQLite
installation, follow [the upgrade guide](docs/upgrade.md). Version 2.0.0 introduces
schema version 2: same-backend reinstall upgrades managed files, and the
explicit `migrate` command upgrades a version-1 database afterwards. Enabling MCP additionally requires the optional package
extra in the Python environment used by the local client.

Run the repository's lint, type, unit, installation, and skill checks with:

```sh
make check
```

`make check` needs the development extra (`python3 -m pip install '.[dev]'`).
The installation and skill suites alone run with no third-party dependency:

```sh
make test
make validate-skill
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full target list, including
`make coverage`.

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
  pyproject.toml
  Makefile
  MANIFEST.in
  VERSION
  coordination/
    README.md
    core.py
    cli.py
    service.py
    errors.py
    _*.py (implementation modules re-exported by the core and service facades)
    transports/
      mcp.py
      _mcp_*.py (tool registrar modules assembled by the mcp facade)
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
      _*.py (part modules re-exported by the entity facades)
  coordination_mcp_launcher/
    __init__.py
  sqlite/
    schema.sql
  scripts/
    install.sh
    verify-install.sh
    coordination.py
    coordination-mcp.py
    check-mcp-dependency.py
    check-markdown-links.py
    validate-skill.py
  scaffold/
    AGENTS.md
    AGENTS-sqlite.md
    coordination-config.yml
    coordination-config-sqlite.yml
    coordination-readme.md
    coordination-readme-sqlite.md
  tests/
    install.sh
    sqlite.sh
    cli-contract.sh
    sqlite-concurrency.sh
    sqlite-operations.sh
    sqlite-stability.sh
    sqlite-restore-qualification.sh
    release-artifact.sh
    mcp-release-artifact.sh
    service-parity.py
    mcp-version-check.py
    mcp-security.py
    mcp-integration.py
    unit/
  docs/
    adapters/
      markdown.md
      sqlite.md
      issue_tracker.md
    decision-rights.md
    health-metrics.md
    cli-contract.md
    upgrade.md
    mcp-contract.md
    adr/
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
  skills/
    agentic-project-scaffold-lite/
      SKILL.md
      agents/
      assets/
      references/
```

See [coordination/README.md](coordination/README.md) for the current SQLite
runtime architecture, installation boundary, and actor identity model.
See [docs/cli-contract.md](docs/cli-contract.md) for the stable CLI
output, error, exit-code, schema, and task-status guarantees.
See [docs/adr/](docs/adr/README.md) for the architecture decision records,
including the deployment scope and the observability roadmap.
See [docs/mcp-contract.md](docs/mcp-contract.md) for the optional local
stdio tool contract and explicit backup/restore confirmations.

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

Version 2.0.0 supports the Markdown installation path, the harness-neutral
SQLite coordination CLI, and an optional local stdio MCP peer transport.
SQLite schema version 2 adds the append-only audit ledger, the change log,
explicit migration from version 1, and cutoff-based archival; pre-release
databases remain unsupported.
See [CHANGELOG.md](CHANGELOG.md) for release notes and
[RELEASING.md](RELEASING.md) for release qualification.

The project is licensed under the [MIT License](LICENSE).
