# Upgrade Existing Installations

This guide upgrades an existing Agentic Project Scaffold Lite project to
version 1.2.0. The installer replaces only managed scaffold/runtime content,
preserves project content and coordination configuration, and preserves the
SQLite database when reinstalling the same backend.

Use the 1.2.0 source release for the `scripts/install.sh` and
`scripts/verify-install.sh` commands below. Do not copy `coordination/` into a
project by hand.

## 1. Identify The Existing Backend And Version

From the project:

```sh
project=/path/to/project
cat "$project/.coordination/config.yml"
cat "$project/.agents/agentic-project-scaffold-lite/VERSION"
```

The existing `backend:` value is authoritative. The installer rejects an
implicit Markdown-to-SQLite or SQLite-to-Markdown switch.

## 2. Back Up SQLite State

For an existing SQLite project, create a verified backup with its currently
installed CLI before upgrading:

```sh
project=/path/to/project
tool="$project/.agents/agentic-project-scaffold-lite/bin/coordination"
"$tool" backup \
  --output "$project/.coordination/backups/pre-1.2.0.sqlite3"
```

Keep this backup until the upgraded installation passes verification and
normal coordination operations have been checked. Markdown projects should
commit or otherwise back up their `.coordination/` records before reinstalling.

## 3. Upgrade A Markdown Installation

Run the 1.2.0 installer with the existing backend:

```sh
./scripts/install.sh \
  --target /path/to/project \
  --adapter markdown
./scripts/verify-install.sh /path/to/project
```

This repairs the managed bundle and instruction block while preserving
unmanaged project content and existing Markdown coordination records. MCP is
not available for the Markdown backend.

## 4. Upgrade A 1.1.0 SQLite Installation

Reinstall the same backend from the 1.2.0 source release:

```sh
./scripts/install.sh \
  --target /path/to/project \
  --adapter sqlite
./scripts/verify-install.sh /path/to/project

tool=/path/to/project/.agents/agentic-project-scaffold-lite/bin/coordination
"$tool" version
"$tool" doctor
```

Versions 1.1.0 and 1.2.0 use the same frozen schema version 1. No database
migration is performed or required. Reinstall replaces the managed CLI and
documentation atomically but preserves `.coordination/config.yml`, the
configured SQLite database, backups, actors, sessions, tasks, messages, audit
history, and other records.

Databases created by pre-release builds remain unsupported. Export or back up
needed data, install into a clean project, and recreate approved records
through the stable CLI.

## 5. Enable Or Upgrade Optional MCP

Install the 1.2.0 optional dependency and generic console bootstrap in the
Python environment used by the MCP client:

```sh
python3 -m pip install --upgrade \
  'agentic-project-scaffold-lite[mcp]==1.2.0'
python3 -I -c \
  'import importlib.metadata as m; print(m.version("mcp"))'
```

Then reinstall the existing SQLite project with the explicit MCP option:

```sh
./scripts/install.sh \
  --target /path/to/project \
  --adapter sqlite \
  --with-mcp
./scripts/verify-install.sh \
  --with-mcp \
  /path/to/project
```

The supported SDK range is `mcp>=1.28.1,<2`. Installation and verification both
reject missing or unsupported versions. Verification compares the installed
launcher with trusted canonical source and never executes a launcher that
fails that integrity check.

If the MCP client uses a virtual environment, configure its command as that
environment's absolute `coordination-mcp` path, or ensure the same environment
is active when it starts the project-installed launcher:

```json
{
  "command": "/absolute/path/to/venv/bin/coordination-mcp",
  "args": []
}
```

Restart the MCP client after upgrading so it starts the new bootstrap and
managed runtime. Codex, Claude, and other clients continue to use the same
generic command and project database.

## 6. Verify Preserved State

Run:

```sh
project=/path/to/project
tool="$project/.agents/agentic-project-scaffold-lite/bin/coordination"

./scripts/verify-install.sh --with-mcp "$project"
"$tool" doctor
"$tool" agent list
"$tool" task list
```

Omit `--with-mcp` when MCP is intentionally not installed. Verification must
fail if managed files differ, the database is unhealthy, or the optional SDK
is outside its supported range.

## Rollback

Stop MCP clients and other coordination writers first. For a managed-runtime
rollback, use the prior stable source release to reinstall the same backend,
then run that release's verifier. Schema version 1 remains compatible between
1.1.0 and 1.2.0.

Restore the pre-upgrade database backup only when database state itself must be
rolled back. Use the installed CLI's explicit restore confirmation and recovery
procedure; do not overwrite the live database manually.
