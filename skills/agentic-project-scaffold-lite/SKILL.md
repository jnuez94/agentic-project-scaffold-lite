---
name: agentic-project-scaffold-lite
description: Initialize and operate durable multi-agent project coordination using explicit roles, tasks, reviews, decisions, dependencies, evidence, and authority. Use when starting or organizing a project with multiple AI agents or human collaborators, creating coordination records, assigning agent work, reviewing completion evidence, resolving overlap or blockers, or auditing project coordination health.
---

# Agentic Project Scaffold Lite

Apply a durable coordination contract without assuming a particular agent harness or tracker.

## Initialize a project

1. Read `references/spec.md` for the authoritative record and status model.
2. Read `references/decision-rights.md` when assigning approval authority.
3. Select exactly one coordination backend: Markdown for transparent file records, or SQLite when all agents share one local project directory and need structured enforcement.
4. For Markdown, copy the needed files from `assets/templates/` into the project's durable coordination substrate.
5. For SQLite, use the repository installer or the bundled `scripts/coordination.py` and `assets/sqlite/schema.sql`; route all state access through the deterministic CLI.
6. Define the project goal, near-term deliverable, hard boundaries, and sensitive-data rules.
7. Create profiles for active roles and create an initial task backlog.
8. Assign release, external-sharing, production, and sensitive-data authority explicitly.

When the full repository checkout is available, prefer running `scripts/install.sh --target <project> --adapter <markdown|sqlite>` from its root. Do not overwrite established project instructions, switch existing backends, or create parallel sources of truth without the user's approval.

When only the skill package is available, initialize SQLite with an explicit database path:

```sh
python3 <skill-directory>/scripts/coordination.py --db <project>/.coordination/coordination.sqlite3 init
```

Create `<project>/.coordination/config.yml` with `version: 1`, `backend: sqlite`, and `database: coordination.sqlite3`. Add `.coordination/*.sqlite3*` to the project's ignore rules and direct project agents to invoke the same bundled CLI with `--db`.

## Coordinate work

Follow this loop for every active agent:

1. Sync current tasks, messages, reviews, blockers, and decisions using Markdown records or the SQLite CLI selected at installation.
2. Select work by ownership, priority, dependencies, and project goal.
3. Announce intent when overlap or shared-artifact risk exists.
4. Produce an artifact and evidence.
5. Request a review from the role with appropriate authority.
6. Integrate required changes explicitly.
7. Close work only when acceptance criteria, evidence, and required reviews exist.

Use only `todo`, `in_progress`, `review`, `blocked`, and `done` for task coordination. Treat `done` as the sole successful terminal state.

## Preserve boundaries

- Record consequential decisions durably; do not use chat memory as the source of truth.
- State what each review, decision, or artifact does not approve.
- Keep secrets, credentials, private customer data, regulated data, and unapproved proprietary material out of coordination records.
- Create follow-up tasks for unresolved work instead of hiding it in notes.
- Never infer production, release, external-use, or sensitive-data approval from task completion.

## Audit coordination health

Read `references/health-metrics.md` before major reviews and releases. Check for unowned or stale tasks, hidden dependencies, aging reviews, conflicting authority, done work without evidence, and sensitive data in coordination records.
