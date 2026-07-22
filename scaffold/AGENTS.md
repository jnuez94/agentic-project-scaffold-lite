# Agentic Project Coordination

<!-- agentic-project-scaffold-lite -->

This project uses the Agentic Project Scaffold Lite working model.

## Required operating loop

Before doing work:

1. Read `.agents/agentic-project-scaffold-lite/SPEC.md`.
2. Check `.coordination/` for active tasks, decisions, reviews, and blockers.
3. Confirm ownership and dependencies before editing shared artifacts.
4. Announce intent in a durable coordination record when overlap is possible.

While doing work:

- Use only these task states: `todo`, `in_progress`, `review`, `blocked`, `done`.
- Record consequential decisions instead of relying on chat history.
- Keep secrets, credentials, customer data, and regulated data out of coordination records.
- Request review from the role with the relevant decision authority.
- State explicitly what an approval or artifact does not authorize.

Before claiming completion:

- Confirm acceptance criteria are met.
- Link current evidence such as tests, artifacts, commits, or review decisions.
- Move remaining work into explicit follow-up tasks.
- Use `done` only when required review and evidence exist.

Use the record templates in `.coordination/templates/`. Additional guidance is in
`.agents/agentic-project-scaffold-lite/`.
