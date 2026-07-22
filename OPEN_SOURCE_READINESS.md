# Open Source Readiness

Use this before publishing the framework publicly.

## Required Before Publishing

- [x] Choose a final repository name: `jnuez94/agentic-project-scaffold-lite`.
- [ ] Replace this seed status with the public project status.
- [x] Choose and add the MIT License.
- [ ] Confirm all examples are generic.
- [ ] Confirm no private project names, customer names, credentials, or sensitive data remain.
- [ ] Decide whether contribution review is maintainer-led, community-led, or RFC-led.
- [ ] Add issue templates if using GitHub, GitLab, Linear, or another public tracker.
- [ ] Add a release tag policy.
- [ ] Decide whether adapter implementations belong in this repo or separate repos.

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
