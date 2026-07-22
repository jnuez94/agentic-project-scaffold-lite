# Project Coordination Records

This directory is the durable coordination layer for agents and human collaborators.

## Layout

- `agents/`: active agent and role profiles
- `tasks/`: accountable units of work
- `messages/`: durable handoffs, requests, and notices
- `reviews/`: scoped review decisions
- `decisions/`: consequential project decisions and rationale
- `artifacts/`: artifact ownership and lifecycle records
- `escalations/`: unresolved authority, risk, or dependency issues
- `indexes/`: lightweight queues and project-health views
- `templates/`: copyable record templates

Start by creating agent profiles, a decision-rights record, and initial tasks. Keep
this directory under version control unless the project has selected another durable
coordination substrate.
