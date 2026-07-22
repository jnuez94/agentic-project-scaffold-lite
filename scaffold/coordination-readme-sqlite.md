# Project Coordination Database

This directory contains the local SQLite coordination state for agents and human collaborators.

Use the installed tool from the project root:

```sh
./.agents/agentic-project-scaffold-lite/bin/coordination --help
```

Do not edit `coordination.sqlite3` directly and do not commit it to Git. Use `coordination backup` for consistent backups and `coordination export` for human-readable Markdown reports.

The selected backend and database filename are recorded in `config.yml`. All participating agents must operate against the same local project directory.
