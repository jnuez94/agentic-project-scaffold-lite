# Agentic Project Coordination

<!-- agentic-project-scaffold-lite:start -->

This project uses the SQLite backend from Agentic Project Scaffold Lite.

## Required coordination interface

Use the deterministic coordination CLI for coordination state, or use an
already configured local MCP peer:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination --help
```

The MCP tools are named `coordination_*` and use the same canonical service
layer, validation, transactions, audit rules, and configured SQLite database as
the CLI. MCP is optional and must be provisioned by a project operator before a
shell-less agent starts; agents must not attempt dependency installation as
part of ordinary coordination work. If neither the CLI nor configured MCP tools
are available, stop and request environment setup instead of creating a second
coordination store.

Do not edit `.coordination/coordination.sqlite3` directly. Do not maintain independent Markdown task records alongside the database.
Treat `docs/cli-contract.md` and `docs/mcp-contract.md` as the machine-interface
contracts. Parse the top-level `ok` field and branch on stable error codes
instead of error messages.

## Required operating loop

Before doing work:

1. Register a stable agent identity if needed, then start a unique execution session through the CLI or equivalent MCP tool.
2. List tasks and inspect relevant messages, reviews, decisions, and blockers through the selected interface.
3. Confirm ownership and dependencies before editing shared artifacts.
4. Claim assigned work through the tool before starting.

While doing work:

- Pass the active session as the global `--session ID` option before the entity command, or set `COORDINATION_SESSION`.
- Heartbeat the session (`session heartbeat` or `coordination_session_heartbeat`) during long silent work. A claim is a lease: a session silent for an hour may be recovered and its claimed tasks reclaimed by another actor.
- Use only `todo`, `in_progress`, `review`, `blocked`, and `done`.
- Record consequential decisions instead of relying on chat history.
- Keep secrets, credentials, customer data, and regulated data out of coordination records.
- Request review from the role with the relevant authority.
- State what an approval or artifact does not authorize.

Before claiming completion:

- Confirm acceptance criteria are met.
- Add current evidence through the CLI or `coordination_evidence_add`.
- Move the task to `review` before `done` when review is required.
- Create explicit follow-up tasks for remaining work.
- End the execution session through the CLI or `coordination_session_end` when the agent stops participating.

Use CLI `health` or MCP `coordination_project_status` to identify unowned,
stale, blocked, or evidence-deficient work. Initialization, version checks,
Markdown export, and raw audit inspection remain CLI-only operational
procedures. Additional guidance is in
`.agents/agentic-project-scaffold-lite/`.

<!-- agentic-project-scaffold-lite:end -->
