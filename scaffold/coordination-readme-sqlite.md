# Project Coordination Database

This directory contains the local SQLite coordination state for agents and human collaborators.

Use the installed tool from the project root:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination --help
```

Do not edit `coordination.sqlite3` directly and do not commit it to Git. Use `coordination backup` for consistent backups and `coordination export` for human-readable Markdown reports.

Register each durable participant with an actor type (`ai`, `human`, or `service`). Start a unique execution session for each harness run, then pass its ID with the global `--session` option or the `COORDINATION_SESSION` environment variable. Actor identity remains stable when the harness changes; session records capture the harness and model used for individual audit events.

The selected backend and database filename are recorded in `config.yml`. All participating agents must operate against the same local project directory.
