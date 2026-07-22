# Open Source Readiness

Use this before publishing the framework publicly.

## Required Before Publishing

- [x] Choose a final repository name: `jnuez94/agentic-project-scaffold-lite`.
- [x] Replace this seed status with the public project status.
- [x] Choose and add the MIT License.
- [x] Confirm all examples are generic.
- [x] Confirm no private project names, customer names, credentials, or sensitive data remain.
- [x] Use maintainer-led contribution review with public issues for significant changes.
- [x] Add GitHub issue and pull request templates.
- [x] Add a semantic release tag policy to `GOVERNANCE.md`.
- [x] Keep local adapters in this repository while they share the core release cycle.

## Good First Issues

- Add a GitHub Issues adapter example.
- Add a Linear adapter example.
- Add a Jira adapter example.
- Add a Notion database adapter example.
- Add a sample markdown coordination folder.
- Add a conformance test checklist for implementations.
- Add example team structures for two-agent, five-agent, and larger teams.

## Project Positioning

Suggested short description:

```text
A harness-agnostic operating model for coordinating multiple AI or human-assisted agents on the same project.
```

Suggested longer description:

```text
The Multi-Agent Working Model gives teams a portable coordination contract for agentic work: roles, tasks, messages, reviews, decisions, dependencies, artifacts, evidence, and decision rights. It can be implemented with markdown, SQLite, issue trackers, or custom agent buses.
```

## Maintainer Bias

Keep the core model small. Let adapters carry tool-specific complexity.
