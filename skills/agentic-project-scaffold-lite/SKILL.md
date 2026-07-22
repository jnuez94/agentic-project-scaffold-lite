---
name: agentic-project-scaffold-lite
description: Initialize and operate durable multi-agent project coordination using explicit roles, tasks, reviews, decisions, dependencies, evidence, and authority. Use when starting or organizing a project with multiple AI agents or human collaborators, creating coordination records, assigning agent work, reviewing completion evidence, resolving overlap or blockers, or auditing project coordination health.
---

# Agentic Project Scaffold Lite

Apply a durable coordination contract without assuming a particular agent harness or tracker.

## Initialize a project

1. Read `references/spec.md` for the authoritative record and status model.
2. Read `references/decision-rights.md` when assigning approval authority.
3. Copy the needed files from `assets/templates/` into the project's durable coordination substrate.
4. Define the project goal, near-term deliverable, hard boundaries, and sensitive-data rules.
5. Create profiles for active roles and create an initial task backlog.
6. Assign release, external-sharing, production, and sensitive-data authority explicitly.

When the full repository checkout is available, prefer running `scripts/install.sh --target <project>` from its root. Do not overwrite established project instructions or coordination records without the user's approval.

## Coordinate work

Follow this loop for every active agent:

1. Sync current tasks, messages, reviews, blockers, and decisions.
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
