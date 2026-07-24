# Project Coordination Database

This directory contains the local SQLite coordination state for agents and human collaborators.

Use the installed tool from the project root:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination --help
```

This installation requires Python 3.10 or newer. Do not edit
the database file selected by `config.yml` directly, and do not commit it to
Git. Use `coordination backup` for verified backups and `coordination export`
for human-readable Markdown reports.

Register each durable participant with an actor type (`ai`, `human`, or `service`). Start a unique execution session for each harness run, then pass its ID with the global `--session` option or the `COORDINATION_SESSION` environment variable. Actor identity remains stable when the harness changes; session records capture the harness and model used for individual audit events.

Machine-readable commands return a top-level `ok` field. Expected failures
return stable error codes and exit codes documented in
`.agents/agentic-project-scaffold-lite/docs/cli-contract.md`.

The selected backend and database filename are recorded in `config.yml`. All participating agents must operate against the same local project directory.

The installed launcher and its sibling `lib/coordination` package are the only
executable implementation. Codex, Claude, humans, and services must invoke this
same CLI and configured database; do not copy or import another runtime.

List commands default to `--limit 100 --offset 0` and accept at most 500 rows
per call. Health sections default to 100 rows each; inspect
`truncated_sections` before treating a report as complete.

## Operations

Validate the installation and database:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination doctor
```

Create a verified, no-clobber backup:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination backup \
  --output .coordination/backups/coordination-20260723.sqlite3
```

Restore only during a maintenance window after ending or recovering every
active session:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination restore \
  --input .coordination/backups/coordination-20260723.sqlite3 \
  --actor product-owner \
  --force
./.agents/agentic-project-scaffold-lite/bin/coordination doctor
```

Retain the reported safety backup until the restored state is accepted.
Expected failures before atomic publication leave the target unchanged; an
unsuccessful post-publication verification reports whether rollback completed.
