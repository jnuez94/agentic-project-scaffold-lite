# Agentic Project Coordination

<!-- agentic-project-scaffold-lite -->

This project uses the SQLite backend from Agentic Project Scaffold Lite.

## Required tool

Use the deterministic coordination CLI for coordination state:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination --help
```

Do not edit `.coordination/coordination.sqlite3` directly. Do not maintain independent Markdown task records alongside the database.
Treat `docs/cli-contract.md` as the machine-interface contract. Parse the
top-level `ok` field and branch on stable error codes instead of error messages.

## Required operating loop

Before doing work:

1. Register a stable agent identity if needed, then start a unique execution session with `coordination session start`.
2. Run `./.agents/agentic-project-scaffold-lite/bin/coordination task list` and inspect relevant messages, reviews, decisions, and blockers.
3. Confirm ownership and dependencies before editing shared artifacts.
4. Claim assigned work through the tool before starting.

While doing work:

- Pass the active session as the global `--session ID` option before the entity command, or set `COORDINATION_SESSION`.
- Use only `todo`, `in_progress`, `review`, `blocked`, and `done`.
- Record consequential decisions instead of relying on chat history.
- Keep secrets, credentials, customer data, and regulated data out of coordination records.
- Request review from the role with the relevant authority.
- State what an approval or artifact does not authorize.

Before claiming completion:

- Confirm acceptance criteria are met.
- Add current evidence through `./.agents/agentic-project-scaffold-lite/bin/coordination evidence add`.
- Move the task to `review` before `done` when review is required.
- Create explicit follow-up tasks for remaining work.
- End the execution session with `coordination session end ID` when the agent stops participating.

Use `./.agents/agentic-project-scaffold-lite/bin/coordination health` to identify unowned, stale, blocked, or evidence-deficient work. Additional guidance is in `.agents/agentic-project-scaffold-lite/`.
